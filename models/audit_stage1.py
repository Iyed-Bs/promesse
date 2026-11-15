"""Audit, why did the hurdle's stage 1 under-predict 2023 (no-minutes players: 30.8 % predicted to play, 40.5 %
observed)? Two readings, told apart before anything is recalibrated:
  football    more young players without senior minutes really did break through from the 2023 snapshot on;
  coverage    the minutes source sees more of the later seasons (more competitions or more matches recorded), so the
              same careers count as "played" more often.
Read-only: it reads the spine, the targets and appearance_quality; it fits nothing and opens no test.

    python models/audit_stage1.py      (Promesse venv) -> lake/models/audit_stage1.json, printed summary
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import projection as P  # noqa: E402

GOLD = P.GOLD
OUT = P.DATA / "lake" / "models" / "audit_stage1.json"


def main() -> None:
    d = P.frame()
    edges = P.tier_edges(d[d.snapshot.between(*P.FIT)])
    d["tier"] = P.tiers(d, edges)
    nm = d[d.tier == 3]
    # 1. the share who go on to play, by snapshot, in the no-minutes tier and in the others
    by_year = (d.assign(plays=d.qmin3 > 0).groupby(["snapshot", "tier"]).plays.mean().unstack().round(3))
    # 2. the minutes source, season by season: rows, players, competitions, quality minutes
    aq = pd.read_parquet(GOLD / "appearance_quality.parquet")
    comp = next((c for c in ("competition_id", "comp_id", "league_id", "competition") if c in aq.columns), None)
    src = aq.groupby("season").agg(rows=("qmin", "size"), players=("player_id", "nunique"), qmin=("qmin", "sum"))
    if comp:
        src["competitions"] = aq.groupby("season")[comp].nunique()
    # 3. where the no-minutes players who played got their first quality minutes, cohort by cohort
    first = {}
    if comp:
        a = aq[aq.qmin > 0][["player_id", "season", comp, "qmin"]]
        for y in range(2019, 2024):
            ids = nm[(nm.snapshot == y) & (nm.qmin3 > 0)].player_id.unique()
            w = a[a.player_id.isin(ids) & a.season.between(y, y + 2)].sort_values("season")
            f = w.groupby("player_id").head(1)
            first[y] = f[comp].value_counts(normalize=True).round(3).head(12).to_dict()
        # competitions whose first season in the source is recent: new coverage, not new football
        start = aq.groupby(comp).season.min()
        new = start[start >= 2021]
        share_new = {}
        for y in range(2017, 2024):
            ids = nm[(nm.snapshot == y) & (nm.qmin3 > 0)].player_id.unique()
            w = a[a.player_id.isin(ids) & a.season.between(y, y + 2)]
            only_new = w.groupby("player_id")[comp].apply(lambda s: s.isin(new.index).all())
            share_new[y] = {"players_who_played": int(len(ids)),
                            "only_in_competitions_first_seen_2021_on": round(float(only_new.mean()), 3) if len(only_new) else None}
    rep = {"question": "stage 1 drift on 2023: football or coverage?",
           "plays_by_snapshot_and_tier": {str(k): v for k, v in by_year.to_dict(orient="index").items()},
           "tier_names": {0: "least senior evidence", 1: "middle", 2: "most", 3: "no senior minutes in two years"},
           "no_minutes_tier_n": nm.groupby("snapshot").size().to_dict(),
           "source_by_season": {str(k): {kk: (int(vv) if isinstance(vv, (int, np.integer)) else round(float(vv), 1))
                                         for kk, vv in v.items()} for k, v in src.to_dict(orient="index").items()},
           "competition_column": comp,
           "first_minutes_where_by_cohort": {str(k): {str(kk): vv for kk, vv in v.items()} for k, v in first.items()},
           "competitions_first_seen_2021_on": ({str(k): int(v) for k, v in new.items()} if comp else None),
           "played_only_in_new_competitions": share_new if comp else None}
    OUT.write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("plays_by_snapshot_and_tier", "no_minutes_tier_n", "source_by_season",
                                          "competition_column", "played_only_in_new_competitions")}, indent=0, default=str)[:4000])


if __name__ == "__main__":
    main()
