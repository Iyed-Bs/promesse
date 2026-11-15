"""Gate A of the project notes track 1: does the presence of MatchData stats track the outcome among players who played?

Snapshots 2017-2022, players with Transfermarkt minutes in the window (min_365 > 0): AUC of "has MatchData stats" for y_reg3,
per snapshot year, plus the missingness audit's usual presence gap on every new input.  Pass: each year's AUC in 0.45-0.55.
Read-only.  python models/audit_fm.py  (Promesse venv) -> lake/models/audit_fm.json
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ladder  # noqa: E402

OUT = Path((DATA_ROOT + "/lake/models/audit_fm.json"))


def main() -> None:
    d = ladder.frame("y_reg3")
    f = pd.read_parquet(OUT.parent / "fm_feats.parquet")
    d = d.merge(f, on=["player_id", "snapshot"], how="left")
    d = d[d.snapshot.between(2017, 2022) & (d.min_365.fillna(0) > 0)]
    d["has_stats"] = d.fm2_chances90.notna()
    d["has_fm"] = d.fm2_min_365.notna()
    res = {"years": {}, "inputs": {}}
    for y, g in d.groupby("snapshot"):
        row = {"n": int(len(g)), "has_stats": round(float(g.has_stats.mean()), 3), "has_fm": round(float(g.has_fm.mean()), 3)}
        for c in ("has_stats", "has_fm"):
            row["auc_" + c] = round(float(roc_auc_score(g.y_reg3, g[c].astype(float))), 3) if g[c].nunique() > 1 else None
        res["years"][int(y)] = row
        print(y, row)
    for c in [c for c in d.columns if c.startswith("fm2_") and not c.endswith("_adj")]:
        miss = d[c].isna()
        if miss.nunique() > 1:
            res["inputs"][c] = {"missing": round(float(miss.mean()), 3), "auc_of_presence": round(float(roc_auc_score(d.y_reg3, (~miss).astype(float))), 3)}
    ys = [v["auc_has_stats"] for v in res["years"].values() if v["auc_has_stats"] is not None]
    res["gate_A_pass"] = bool(all(0.45 <= a <= 0.55 for a in ys))
    OUT.write_text(json.dumps(res, indent=1))
    print("gate A (every year's presence AUC in 0.45-0.55):", res["gate_A_pass"])


if __name__ == "__main__":
    main()
