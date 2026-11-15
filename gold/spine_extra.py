"""ProEngine: the shape of a career, point in time (inputs rule: what happened only).

For every player and snapshot Y (the start of July of year Y), from the seasons that ended before it (Transfermarkt seasons
<= Y-1, so nothing after the snapshot is read):
  growth_q          log quality minutes last season minus the season before: is he rising?
  share_trend       his best share of team minutes last season minus the season before
  level_step        the level of his main club last season minus the season before (Elo vs the big five): a move up?
  seasons_senior    how many seasons he has had first-division minutes
  qmin_cum          quality minutes so far
  cohort_pct        his quality minutes so far, as a percentile among every player born the same year with senior
                    minutes by then: the age-peer comparison (Yamal at 17 is first of his year)
Injuries, youth caps and the tactical layer start in 2021 in our data, after the training years (2014-2020): they wait
until enough seasons accumulate for an out-of-time test.

    python gold/spine_extra.py     (Promesse venv) -> lake/gold/spine_extra.parquet
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

DATA = Path(DATA_ROOT)
GOLD = DATA / "lake" / "gold"
TM = (DATA / "transfermarkt-datasets.duckdb").as_posix()
SNAPSHOTS = range(2014, 2027)


def main() -> None:
    ps = pd.read_parquet(GOLD / "player_seasons.parquet")[["player_id", "season", "minutes", "qmin", "best_share", "best_share_level"]]
    con = duckdb.connect()
    con.execute(f"attach '{TM}' as tm (read_only)")
    born = con.execute("select player_id::bigint player_id, year(date_of_birth) born from tm.players where date_of_birth is not null").df()
    ps = ps.merge(born, on="player_id")
    rows = []
    for y in SNAPSHOTS:
        past = ps[ps.season <= y - 1]
        last, prev = past[past.season == y - 1].set_index("player_id"), past[past.season == y - 2].set_index("player_id")
        cum = past.groupby("player_id").agg(qmin_cum=("qmin", "sum"), seasons_senior=("minutes", lambda m: int((m > 0).sum())),
                                             born=("born", "first"))
        df = cum.copy()
        df["growth_q"] = np.log1p(last.qmin.reindex(df.index).fillna(0)) - np.log1p(prev.qmin.reindex(df.index).fillna(0))
        df["share_trend"] = last.best_share.reindex(df.index) - prev.best_share.reindex(df.index)
        df["level_step"] = last.best_share_level.reindex(df.index) - prev.best_share_level.reindex(df.index)
        df["cohort_pct"] = df.groupby("born").qmin_cum.rank(pct=True)
        df["snapshot"] = y
        rows.append(df.drop(columns=["born"]).reset_index())
    out = pd.concat(rows, ignore_index=True)
    out["qmin_cum"] = np.log1p(out.qmin_cum)
    out.to_parquet(GOLD / "spine_extra.parquet", index=False)
    print(f"{len(out):,} player-snapshots; coverage:", {c: f"{out[c].notna().mean():.0%}" for c in ("growth_q", "share_trend", "level_step", "cohort_pct")})


if __name__ == "__main__":
    main()
