"""Promesse, Phase 3: the spine. One row per player per snapshot (2014-2025), built only from what was known
before the snapshot (ARCHITECTURE D3), with a leakage audit and a coverage report.

Population at each snapshot: Transfermarkt players with a birth date, aged 16 to 21, who played in the 31 leagues in
the two years before it or had a market value set in the year before it.

Feature groups, each with the latest date it used (kt_*), which the audit checks against the snapshot:
  static     age, birth quarter, position group, height, left foot
  app        minutes and quality minutes (365 / 730 days), league and European minutes, appearances, age at first
             appearance, last club and its level                                  (gold/appearance_quality)
  season     last season's best share and club level, best share and level so far (gold/player_club_seasons)
  mv         last market value, its age, the highest so far, the value a year earlier
  ea         EA overall and potential, the latest update before the snapshot      (identity v3: tm -> ea)
  pes        the latest PES edition released before the snapshot: mean of its main abilities (tm -> konami)
  fm         MatchData rating (minutes-weighted) and youth-competition minutes, 365 days (tm -> matchdata; 2021 on)

    python gold/spine.py      (Promesse venv) -> lake/gold/spine.parquet, leakage_audit.json, the project notes
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import glob
import json
import re
from pathlib import Path

import duckdb
import pandas as pd

DATA = Path(DATA_ROOT)
TM = DATA / "transfermarkt-datasets.duckdb"
LAKE = DATA / "lake"
GOLD = LAKE / "gold"
FIRST, LAST = 2014, 2025
SCORE = 2026          # the scoring snapshot: built the same way, saved apart, never trained on
PES_MAIN = ["Attacking Prowess", "Ball Control", "Dribbling", "Low Pass", "Lofted Pass", "Finishing", "Header",
            "Defensive Prowess", "Ball Winning", "Kicking Power", "Speed", "Explosive Power", "Body Control",
            "Physical Contact", "Jump", "Stamina"]
YOUTH = r"U1[6-9]|U2[0-3]|Youth|Premier League 2|Primavera|Juvenil"


def load(con: duckdb.DuckDBPyConnection) -> None:
    """Every input registered as a DuckDB view or table, ids cast to one type."""
    tm = duckdb.connect(str(TM), read_only=True)
    con.register("players_df", tm.sql("""
        select player_id::bigint as player_id, date_of_birth::date as dob, position, sub_position, foot,
               height_in_cm::double as height from players where date_of_birth is not null""").df())
    con.register("mv_df", tm.sql("""
        select player_id::bigint as player_id, date::date as date, market_value_in_eur::double as mv
        from player_valuations""").df())
    tm.close()
    con.execute(f"create view aq as select * from read_parquet('{(GOLD / 'appearance_quality.parquet').as_posix()}')")
    con.execute(f"create view pcs as select * from read_parquet('{(GOLD / 'player_club_seasons.parquet').as_posix()}')")
    con.execute(f"""create view persons as select try_cast(tm_id as bigint) as tm_id, try_cast(ea_id as bigint) as ea_id,
                    try_cast(konami_id as bigint) as konami_id, matchdata_id::varchar as matchdata_id
                    from read_parquet('{(LAKE / 'identity' / 'persons.parquet').as_posix()}') where tm_id is not null""")
    # every EA rating, each dated by when it was known (gold/ea_ratings.py: FIFA 15 to FC 26)
    con.execute(f"""create view ea as select ea_id, date::date as date, overall::double as overall,
                    potential::double as potential from read_parquet('{(GOLD / 'ea_ratings.parquet').as_posix()}')""")
    # PES: one row per player and edition, the mean of the main abilities; known from the edition's release
    # (mid-September of the year before the edition's name)
    pes = []
    for f in sorted(glob.glob(str(DATA / "gamerating_b_pes*.parquet"))):
        d = pd.read_parquet(f)
        cols = [c for c in PES_MAIN if c in d.columns]
        if "pes_id" not in d.columns or not cols:
            continue
        year = int(re.search(r"(\d{4})", str(d["edition"].iloc[0])).group(1))
        vals = d[cols].apply(pd.to_numeric, errors="coerce")
        pes.append(pd.DataFrame({"konami_id": pd.to_numeric(d["pes_id"], errors="coerce"),
                                 "known": pd.Timestamp(year - 1, 9, 15), "pes_mean": vals.mean(axis=1)}))
    con.register("pes_df", pd.concat(pes).dropna(subset=["konami_id"]) if pes else
                 pd.DataFrame({"konami_id": [], "known": [], "pes_mean": []}))
    fm_files = (LAKE / "matchdata" / "player_matches").as_posix() + "/**/*.parquet"
    con.execute(f"""create view fm as select player_id::varchar as matchdata_id, try_cast(left(date, 10) as date) as date,
                    "matchdata rating" as rating, "Minutes played" as minutes, league
                    from read_parquet('{fm_files}', union_by_name=true)""")
    con.execute(f"""create view fmy as select player_id::varchar as matchdata_id, try_cast(left(date::varchar, 10) as date) as date,
                    "Minutes played" as minutes, league
                    from read_parquet('{(DATA / 'matchdata_youth_match_players.parquet').as_posix()}')""")


def snapshot(con: duckdb.DuckDBPyConnection, y: int) -> pd.DataFrame:
    snap = f"DATE '{y}-07-01'"
    return con.execute(f"""
    with pop as (
      select p.*, date_diff('day', p.dob, {snap}) / 365.25 as age
      from players_df p
      where date_diff('day', p.dob, {snap}) / 365.25 between 16 and 21.999
        and (exists (select 1 from aq where aq.player_id = p.player_id and aq.date < {snap}
                     and aq.date >= {snap} - interval 730 day)
             or exists (select 1 from mv_df m where m.player_id = p.player_id and m.date < {snap}
                        and m.date >= {snap} - interval 365 day))
    ), app as (
      select a.player_id,
             sum(minutes) filter (where date >= {snap} - interval 365 day) as min_365,
             sum(minutes) filter (where date >= {snap} - interval 730 day) as min_730,
             sum(qmin) filter (where date >= {snap} - interval 365 day) as qmin_365,
             sum(qmin) filter (where date >= {snap} - interval 730 day) as qmin_730,
             sum(minutes) filter (where ctype = 'domestic_league' and date >= {snap} - interval 365 day) as league_min_365,
             sum(minutes) filter (where ctype in ('international_cup', 'other') and date >= {snap} - interval 730 day) as europe_min_730,
             count(*) filter (where date >= {snap} - interval 365 day) as apps_365,
             min(date) as first_app, arg_max(club_id, date) as last_club, max(date) as kt_app
      from aq a join pop using (player_id) where a.date < {snap} group by 1
    ), seas as (
      select c.player_id,
             max(share) filter (where season = {y - 1}) as last_share,
             arg_max(team_level_rel, share) filter (where season = {y - 1}) as last_level,
             max(share) as best_share,
             max(team_level_rel) filter (where share >= 0.4) as best_level,
             count(distinct club_id) filter (where season >= {y - 2}) as clubs_2y
      from pcs c join pop using (player_id) where c.season < {y} group by 1
    ), club as (
      select a.player_id, c.team_level_rel as last_club_level
      from app a left join pcs c on c.player_id = a.player_id and c.club_id = a.last_club and c.season = {y - 1}
    ), mv as (
      select m.player_id, arg_max(mv, m.date) as mv_last, max(m.date) as kt_mv, max(mv) as mv_max,
             arg_max(mv, m.date) filter (where m.date < {snap} - interval 365 day) as mv_1y
      from mv_df m join pop using (player_id) where m.date < {snap} group by 1
    ), ea_f as (
      select pr.tm_id as player_id, arg_max(e.overall, e.date) as ea_overall, arg_max(e.potential, e.date) as ea_potential,
             max(e.date) as kt_ea
      from persons pr join ea e on e.ea_id = pr.ea_id where e.date < {snap} group by 1
    ), pes_f as (
      select pr.tm_id as player_id, arg_max(s.pes_mean, s.known) as pes_mean, max(s.known) as kt_pes
      from persons pr join pes_df s on s.konami_id = pr.konami_id where s.known < {snap} group by 1
    ), fm_f as (
      select pr.tm_id as player_id,
             sum(f.rating * f.minutes) / nullif(sum(f.minutes) filter (where f.rating is not null), 0) as fm_rating_365,
             sum(f.minutes) as fm_min_365, max(f.date) as kt_fm
      from persons pr join fm f on f.matchdata_id = pr.matchdata_id
      where f.date < {snap} and f.date >= {snap} - interval 365 day group by 1
    ), fmy_f as (
      select pr.tm_id as player_id, sum(f.minutes) as fm_youth_min_365, max(f.date) as kt_fmy
      from persons pr join fmy f on f.matchdata_id = pr.matchdata_id
      where f.date < {snap} and f.date >= {snap} - interval 365 day and regexp_matches(f.league, '{YOUTH}') group by 1
    )
    select {y} as snapshot, pop.player_id, pop.age, quarter(pop.dob) as birth_quarter,
           case when pop.position = 'Goalkeeper' then 'GK' when pop.position = 'Defender' then 'DEF'
                when pop.position = 'Midfield' then 'MID' when pop.position = 'Attack' then 'ATT' end as pos,
           pop.height, (pop.foot = 'left')::int as left_foot,
           app.min_365, app.min_730, app.qmin_365, app.qmin_730, app.league_min_365, app.europe_min_730, app.apps_365,
           date_diff('day', pop.dob, app.first_app) / 365.25 as age_first_app, club.last_club_level,
           seas.last_share, seas.last_level, seas.best_share, seas.best_level, seas.clubs_2y,
           mv.mv_last, date_diff('day', mv.kt_mv, {snap}) as mv_days, mv.mv_max, mv.mv_1y,
           ea_f.ea_overall, ea_f.ea_potential, pes_f.pes_mean, fm_f.fm_rating_365, fm_f.fm_min_365, fmy_f.fm_youth_min_365,
           app.kt_app, mv.kt_mv, ea_f.kt_ea, pes_f.kt_pes, fm_f.kt_fm, fmy_f.kt_fmy
    from pop left join app using (player_id) left join seas using (player_id) left join club using (player_id)
         left join mv using (player_id) left join ea_f using (player_id) left join pes_f using (player_id)
         left join fm_f using (player_id) left join fmy_f using (player_id)
    """).df()


KT = ["kt_app", "kt_mv", "kt_ea", "kt_pes", "kt_fm", "kt_fmy"]


def audit(sp: pd.DataFrame) -> dict:
    """Every knowledge date strictly before its snapshot; no target column among the features."""
    snapdate = pd.to_datetime(sp.snapshot.astype(str) + "-07-01")
    checks = {}
    for k in KT:
        v = pd.to_datetime(sp[k])
        bad = int(((v >= snapdate) & v.notna()).sum())
        checks[k] = {"rows_with_value": int(v.notna().sum()), "after_snapshot": bad}
    leaked_targets = [c for c in sp.columns if c.startswith("y_") or c in ("level3",)]
    passed = all(c["after_snapshot"] == 0 for c in checks.values()) and not leaked_targets
    return {"passed": passed, "checks": checks, "target_columns_in_features": leaked_targets}


def coverage(sp: pd.DataFrame) -> str:
    feats = ["min_365", "qmin_365", "last_share", "mv_last", "ea_overall", "pes_mean", "fm_rating_365", "fm_youth_min_365"]
    g = sp.groupby("snapshot")
    rows = ["| Snapshot | Players | " + " | ".join(feats) + " |", "|---|---|" + "---|" * len(feats)]
    for s, d in g:
        rows.append(f"| {s} | {len(d)} | " + " | ".join(f"{100 * d[f].notna().mean():.0f} %" for f in feats) + " |")
    return "\n".join(["# The spine: coverage by snapshot", "",
                      "Share of players with each feature known at the snapshot (built by `gold/spine.py`).", "", *rows, "",
                      "EA starts with FIFA 15 (Sep 2014); MatchData in 2021; PES editions as the crawl brings them in.", ""])


def main() -> None:
    con = duckdb.connect()
    load(con)
    sp = pd.concat([snapshot(con, y) for y in range(FIRST, LAST + 1)], ignore_index=True)
    a = audit(sp)
    GOLD.mkdir(parents=True, exist_ok=True)
    sp.to_parquet(GOLD / "spine.parquet", index=False)
    (GOLD / "leakage_audit.json").write_text(json.dumps(a, indent=1), encoding="utf-8").write_text(coverage(sp), encoding="utf-8")
    # the scoring snapshot: the start of July of the last complete season's end, no targets yet; the models whose gates passed
    # score it for the Scout Desk (models/score_current.py)
    cur = snapshot(con, SCORE)
    ac = audit(cur)
    cur.to_parquet(GOLD / "spine_current.parquet", index=False)
    print(json.dumps({"rows": int(len(sp)), "players": int(sp.player_id.nunique()), "leakage_audit_passed": a["passed"],
                      "by_snapshot": sp.groupby("snapshot").size().to_dict(),
                      "scoring_snapshot": {"year": SCORE, "rows": int(len(cur)), "audit_passed": ac["passed"]}}, indent=1))


if __name__ == "__main__":
    main()
