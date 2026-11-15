"""Promesse, Phase 3: the targets, frozen (ARCHITECTURE D1). Changed only with a new version number.

Outcomes come from careers, never from ratings. For a snapshot at the start of July of year Y, from the player-club-seasons of
gold/careers.py (31 first divisions; "regular" = at least half his team's league minutes in a season):

  y_reg1     a regular in season Y (the season about to start)                  labelled for Y <= LAST
  y_reg3     a regular in at least one of seasons Y, Y+1, Y+2                     labelled for Y + 2 <= LAST
  y_strong3  the same, at a club whose level is within 100 Elo of the big five's average that season
  level3     the best level (Elo vs the big five's average) where he held 40 % or more, seasons Y..Y+2
  y_est      established: two consecutive regular seasons starting at ages 23-26 (needs a known birth date;
             labelled when the whole window is in the data)
  qmin3      (v1.1) log(1 + quality minutes played in seasons Y..Y+2): 0 for a player who doesn't make it, so no
             career drops out; labelled for Y + 2 <= LAST. (v1.3) Only competitions recorded in every season from 2014
             to LAST count: three first recorded in 2025/26 and the Conference League qualifiers (from 2021/22) made
             the 2023 cohort look as if more of it played (models/audit_stage1.py)

LAST is the last complete season (2025/26). A player who leaves the 31 leagues counts as not a regular: the targets
measure "made it in these leagues", and the report says so. Censored rows keep the target empty, never zero.

v1.2, a population fix, the definitions unchanged: every Transfermarkt player gets a row for every
snapshot. Before, rows were built only for players with a season in the 31 leagues at some point up to 2025/26, so a
youth player who never made it had no target and dropped out of every model: a selection on the future, growing as the
snapshot nears the present (29 % of under-21 spine rows in 2014, 50 % in 2022), which lifted recent base rates.

    python gold/targets.py      (Promesse venv) -> lake/gold/targets.parquet, targets_v1.json
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

DATA = Path(DATA_ROOT)
TM = DATA / "transfermarkt-datasets.duckdb"
GOLD = DATA / "lake" / "gold"
VERSION = ("targets v1.3, 2026-10-24 (v1.3: qmin3 on the competitions recorded in every season; v1.2: every Transfermarkt "
           "player gets a row; v1.1 adds qmin3)")
STABLE_FROM = 2014          # the first snapshot the models fit on: a competition counts for qmin3 if recorded every season since
LAST = 2025                 # last complete season (2025/26)
FIRST_SNAPSHOT, LAST_SNAPSHOT = 2014, 2025
REGULAR, HELD, STRONG = 0.5, 0.4, -100.0


def main() -> None:
    pcs = pd.read_parquet(GOLD / "player_club_seasons.parquet")
    pcs["regular"] = pcs.share >= REGULAR
    pcs["regular_strong"] = pcs.regular & (pcs.team_level_rel >= STRONG)
    pcs["held_level"] = np.where(pcs.share >= HELD, pcs.team_level_rel, np.nan)
    per = pcs.groupby(["player_id", "season"]).agg(regular=("regular", "max"), strong=("regular_strong", "max"),
                                                   level=("held_level", "max")).reset_index()
    # every Transfermarkt player, not only those who later played a season here (v1.2: no selection on the future)
    c = duckdb.connect(str(TM), read_only=True)
    every = c.sql("select distinct player_id::bigint as player_id from players").df().player_id
    c.close()
    players = np.union1d(per.player_id.unique(), every.to_numpy())
    rows = []
    reg = {(p, s): (r, st, lv) for p, s, r, st, lv in per.itertuples(index=False)}
    for p in players:
        for y in range(FIRST_SNAPSHOT, LAST_SNAPSHOT + 1):
            nxt = [reg.get((p, s)) for s in (y, y + 1, y + 2)]
            r1 = bool(nxt[0][0]) if nxt[0] else False
            done3 = y + 2 <= LAST
            r3 = any(x and x[0] for x in nxt) if done3 else None
            s3 = any(x and x[1] for x in nxt) if done3 else None
            lv = [x[2] for x in nxt if x and not pd.isna(x[2])]
            rows.append((p, y, r1, r3, s3, max(lv) if (lv and done3) else np.nan))
    t = pd.DataFrame(rows, columns=["player_id", "snapshot", "y_reg1", "y_reg3", "y_strong3", "level3"])

    # established at 23-26, from the birth date
    c = duckdb.connect(str(TM), read_only=True)
    dob = c.sql("select player_id::bigint as player_id, date_of_birth::date as dob from players").df()
    c.close()
    dob["dob"] = pd.to_datetime(dob["dob"])
    reg_seasons = per[per.regular].groupby("player_id")["season"].apply(set).to_dict()
    est = {}
    for p, d in zip(dob.player_id, dob.dob):
        if pd.isna(d):
            continue
        # seasons starting when he is 23 to 26
        window = [s for s in range(2012, LAST + 1) if 23 <= (pd.Timestamp(s, 7, 1) - d).days / 365.25 < 27]
        complete =(pd.Timestamp(LAST, 7, 1) - d).days / 365.25 >= 27   # the whole 23-26 window has been played
        if not complete:
            continue
        rs = reg_seasons.get(p, set())
        est[p] = any(s in rs and s + 1 in rs for s in window)
    t["y_est"] = t.player_id.map(est)
    aq = pd.read_parquet(GOLD / "appearance_quality.parquet", columns=["player_id", "season", "competition_id", "qmin"])
    every = set(range(STABLE_FROM, LAST + 1))
    stable = [c for c, s in aq.groupby("competition_id").season.unique().items() if every <= set(s)]
    qs = aq[aq.competition_id.isin(stable)].groupby(["player_id", "season"]).qmin.sum()
    q3 = {(p, y): sum(qs.get((p, s), 0.0) for s in (y, y + 1, y + 2)) for p, y in zip(t.player_id, t.snapshot)}
    t["qmin3"] = [np.log1p(q3[(p, y)]) if y + 2 <= LAST else np.nan for p, y in zip(t.player_id, t.snapshot)]
    t["y_reg1"] = t.y_reg1.where(t.snapshot <= LAST)
    GOLD.mkdir(parents=True, exist_ok=True)
    t.to_parquet(GOLD / "targets.parquet", index=False)
    spec = {"version": VERSION, "last_complete_season": LAST,
            "definitions": {"y_reg1": "regular (>= 50 % of team league minutes) in season Y",
                            "y_reg3": "regular in at least one of seasons Y..Y+2",
                            "y_strong3": "regular in Y..Y+2 at a club within 100 Elo of the big-five average",
                            "level3": "best club level (Elo vs big-five average) held at >= 40 % in Y..Y+2",
                            "y_est": "two consecutive regular seasons starting at ages 23-26",
                            "qmin3": "log(1 + quality minutes in seasons Y..Y+2), competitions recorded every season "
                                     f"since {STABLE_FROM} ({len(stable)} of {aq.competition_id.nunique()}; v1.3)"},
            "coverage_note": "31 first divisions in Transfermarkt's datasets; leaving them counts as not regular",
            "rows": int(len(t)), "labelled": {k: int(t[k].notna().sum()) for k in ("y_reg1", "y_reg3", "y_strong3", "y_est")},
            "base_rates": {k: round(float(t[k].dropna().astype(float).mean()), 4) for k in ("y_reg1", "y_reg3", "y_strong3", "y_est")}}
    (GOLD / "targets_v1.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
    print(json.dumps(spec, indent=1))


if __name__ == "__main__":
    main()
