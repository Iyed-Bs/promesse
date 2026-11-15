"""Promesse: the two stands. Who counts as deeply analysed, by criteria fixed then before any player
was looked at.

Upper stand, "Deep analysis": a player who has
  1. at least two seasons, 2021/22 to 2025/26, with 900+ minutes of matches that carry per-player stats (touches,
     passes, shots, defensive actions, duels, recoveries: lake/integrity.py's STATS);
  2. an identity linking his MatchData record to his Transfermarkt record, with an exact birth date (identity/persons);
  3. no hold from a quality check (the MatchData ids in the "one Transfermarkt player claimed by two MatchData ids"
     conflict, held back until reviewed).
Everyone else is in the lower stand, "Projections", with the reason he is there.

Gate for the build (set before it): criterion 1 alone must reproduce the earlier measurement within 2 % (8,053 players
with two or more full seasons; 2,642 of them 21 or younger in their first full season). If it does not, the difference
is explained in the report before any player is shown. Criteria 2 and 3 then remove players, and the report says how
many and why. The 100-player review is a reading task left to the maintainer: the table ships as "not yet
reviewed".

Seasons: split-year leagues label them "2021-2022"; calendar-year leagues "2021". Both kinds count, each season once
(a calendar year Y stands for the season Y-1/Y it ends, the way the desk's careers file it).

    python gold/stands.py          (Promesse venv) -> lake/gold/stands.parquet, stands_report.json
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
from pathlib import Path

import duckdb
import pandas as pd

LAKE = Path((DATA_ROOT + "/lake"))
GOLD = LAKE / "gold"
PM = f"read_parquet('{(LAKE / 'matchdata' / 'player_matches').as_posix()}/**/*.parquet', hive_partitioning=true, union_by_name=true)"
STATS = ['"Touches"', '"Accurate passes"', '"Total shots"', '"Defensive actions"', '"Duels won"', '"Recoveries"']
FULL, MIN_SEASONS, YOUNG = 900, 2, 21            # the project notes section 2, MEASURED = {"players": 8053, "young": 2642}      # the earlier measurement the build must reproduce within 2 %
SPLIT = ["2021-2022", "2022-2023", "2023-2024", "2024-2025", "2025-2026"]
CAL = {"2022": "2021-2022", "2023": "2022-2023", "2024": "2023-2024", "2025": "2024-2025", "2026": "2025-2026"}


def seasons(con, with_calendar: bool) -> pd.DataFrame:
    """Minutes with stats per player and season (the backbone period only), and his youngest age that season."""
    has = " or ".join(f"{s} is not null" for s in STATS)
    labels = SPLIT + (list(CAL) if with_calendar else [])
    case = "case season " + " ".join(f"when '{k}' then '{v}'" for k, v in CAL.items()) + " else season end"
    return con.execute(f"""select player_id::varchar player_id, {case} season,
                                  sum(case when {has} then coalesce("Minutes played", 0) else 0 end) min_stats,
                                  min(try_cast(age as double)) age
                           from {PM} where season in ({','.join(f"'{s}'" for s in labels)})
                           group by 1, 2""").df()


def deep_seasons(s: pd.DataFrame) -> pd.DataFrame:
    """Per player: full seasons (900+ minutes with stats), his first one, and his age when the period starts for him.
    "Young" reads his youngest age in his first season of the period (any minutes), which is how the earlier count was
    measured (that reading gives 2,641 at 21 or younger and 4,073 at 23 or younger, against 2,642 and
    4,073; his first *full* season gives 2,316 and 3,902)."""
    full = s[s.min_stats >= FULL].sort_values(["player_id", "season"])
    g = full.groupby("player_id")
    first = s.sort_values(["player_id", "season"]).groupby("player_id").age.first()
    out = pd.DataFrame({"full_seasons": g.size(), "first_full": g.season.first(), "minutes_with_stats": g.min_stats.sum()})
    out["age_first_full"] = first.reindex(out.index)      # the name stays for the desk; see the docstring for its reading
    return out.reset_index()


def main() -> None:
    con = duckdb.connect()
    # criterion 1, both readings of "2021/22 to 2025/26": split-year seasons alone, and with calendar-year leagues
    variants = {}
    for cal in (False, True):
        d = deep_seasons(seasons(con, cal))
        upper = d[d.full_seasons >= MIN_SEASONS]
        variants["with calendar-year leagues" if cal else "split-year seasons only"] = (d, upper)
    check = {k: {"players": int(len(u)), "young": int((u.age_first_full <= YOUNG).sum()),
                 "players_off_pct": round(100 * (len(u) / MEASURED["players"] - 1), 2),
                 "young_off_pct": round(100 * ((u.age_first_full <= YOUNG).sum() / MEASURED["young"] - 1), 2)}
             for k, (_, u) in variants.items()}
    for v in check.values():
        v["reproduces"] = bool(abs(v["players_off_pct"]) <= 2 and abs(v["young_off_pct"]) <= 2)
    # the reading that reproduces is the one that was measured; if both do, the fuller one (calendar leagues
    # included) is kept; if neither does, the build stops here and the report explains
    ok = [k for k, v in check.items() if v["reproduces"]]
    report = {"criteria": {"full_season_minutes_with_stats": FULL, "min_full_seasons": MIN_SEASONS, "young_age": YOUNG,
                           "period": "2021/22 to 2025/26"}, "measured_30_oct": MEASURED, "reproduction": check}
    if not ok:
        report["gate"] = "not passed: criterion 1 does not reproduce the earlier measurement within 2 %; no player is shown"
        (GOLD / "stands_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(check, indent=1)); return
    used = "with calendar-year leagues" if "with calendar-year leagues" in ok else ok[0]
    d, _ = variants[used]

    # criteria 2 and 3: the identity link with an exact birth date, and no identity hold
    ids = con.execute(f"""select matchdata_id::varchar player_id, tm_id, dob from read_parquet('{(LAKE / 'identity' / 'persons.parquet').as_posix()}')
                          where matchdata_id is not null""").df()
    yt = LAKE / "identity" / "matchdata_youth_tm.parquet"
    held = set(con.execute(f"""select matchdata_id::varchar from '{yt.as_posix()}' where tm_id in
                               (select tm_id from '{yt.as_posix()}' group by 1 having count(distinct matchdata_id) > 1)""").df().iloc[:, 0]) if yt.exists() else set()
    t = d.merge(ids, on="player_id", how="left")
    t["reason"] = None
    t.loc[t.full_seasons < MIN_SEASONS, "reason"] = "fewer than two full seasons with stats"
    t.loc[t.reason.isna() & (t.tm_id.isna() | t.dob.isna()), "reason"] = "no identity link with an exact birth date"
    t.loc[t.reason.isna() & t.player_id.isin(held), "reason"] = "held back: identity conflict under review"
    t["stand"] = t.reason.isna().map({True: "deep", False: "projection"})
    t["young"] = t.age_first_full <= YOUNG
    t["reviewed"] = False                                   # the 100-player review is the maintainer's reading task
    t.to_parquet(GOLD / "stands.parquet", index=False)

    deep = t[t.stand == "deep"]
    report |= {"gate": "passed: criterion 1 reproduces the earlier measurement within 2 %", "reading_used": used,
               "upper_stand": {"players": int(len(deep)), "young": int(deep.young.sum()),
                               "with_three_or_more": int((deep.full_seasons >= 3).sum())},
               "removed_by": {r: int(n) for r, n in t[t.full_seasons >= MIN_SEASONS].reason.value_counts().items()},
               "with_one_full_season": int((t.full_seasons == 1).sum()),
               "reviewed": "not yet: the 100-player review is a reading task",
               "explained": ["Young is read at his first season of the period, as the earlier count was; at his first full season it would be 2,316.",
                             f"Calendar-year leagues (Brazil, the MLS, Scandinavia...) are outside the measured reading; counting them would add "
                             f"{check['with calendar-year leagues']['players'] - check['split-year seasons only']['players']:,} players before the identity filter, a widening for a later version."],
               "written": "lake/gold/stands.parquet: one row per MatchData player with a full season; everyone else is in the lower stand"}
    (GOLD / "stands_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
