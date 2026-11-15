"""Audit, after the moves leak, every engine input checked for the same signature. A recording leak shows as
missingness that tracks the outcome: a value filled in for players who went on to make it (a profile completed once
they're notable) and left empty for the others. For each input, on the fitting and test years (2014-2022): how often it
is missing for future regulars and for the others, and the AUC of "missing" alone. Large gaps are then checked by hand
against how the input is recorded (dated at the time, or filled in later).

Read-only.  python models/audit_missing.py   (Promesse venv) -> lake/models/audit_missing.json
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

OUT = Path((DATA_ROOT + "/lake/models/audit_missing.json"))


def main() -> None:
    d = ladder.frame("y_reg3")
    d = d[d.snapshot.between(2014, 2022) & d.y_reg3.notna()]
    y = d.y_reg3.astype(int).to_numpy()
    rows = []
    for c in ladder.features(d):
        if c.endswith("_na"):
            continue
        miss = d[c].isna().to_numpy()
        if miss.mean() in (0.0, 1.0):
            rows.append({"input": c, "missing": round(float(miss.mean()), 3)})
            continue
        # AUC of "present" (1 - missing) as a score for becoming a regular; 0.5 = no information
        auc = roc_auc_score(y, (~miss).astype(float))
        # does the gap move with the cohort? early (2014-2017) against late (2018-2022)
        early, late = d.snapshot <= 2017, d.snapshot >= 2018
        gap = lambda m: float(d.loc[m & (d.y_reg3 == 0), c].isna().mean() - d.loc[m & (d.y_reg3 == 1), c].isna().mean())  # noqa: E731
        rows.append({"input": c, "missing": round(float(miss.mean()), 3),
                     "missing_if_regular": round(float(miss[y == 1].mean()), 3), "missing_if_not": round(float(miss[y == 0].mean()), 3),
                     "auc_of_presence": round(float(auc), 3), "gap_early": round(gap(early), 3), "gap_late": round(gap(late), 3)})
    rows.sort(key=lambda r: -abs(r.get("auc_of_presence", 0.5) - 0.5))
    OUT.write_text(json.dumps({"rows": int(len(d)), "base_rate": round(float(y.mean()), 3), "inputs": rows}, indent=1), encoding="utf-8")
    print(f"{len(d)} rows, base rate {y.mean():.3f}")
    for r in rows[:16]:
        print(r)


if __name__ == "__main__":
    main()
