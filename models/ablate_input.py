"""Ablation on T2 for one group of inputs (by prefix): the penalised logistic with T1's C, fitted 2014-2020 and scored
on 2021-2022, with and without the group, paired bootstrap. Plus the recording check: the group's rate among future
regulars and the others, early cohorts (2014-2017) against late (2018-2022); a ratio that drifts points at recording.

    python models/ablate_input.py yt_      (Promesse venv) -> lake/models/ablate_<prefix>.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ladder  # noqa: E402


def main(prefix: str) -> None:
    d = ladder.frame("y_reg3")
    lad = json.loads((ladder.OUT / "ladder_y_reg3.json").read_text(encoding="utf-8"))
    C = lad["settings_chosen_on_T1"]["C"]
    (a0, a1), (b0, b1) = ladder.T2
    tr, te = d[d.snapshot.between(a0, a1)], d[d.snapshot.between(b0, b1)]
    y_te = te.y_reg3.to_numpy().astype(int)
    cols = ladder.features(d)
    group = [c for c in cols if c.startswith(prefix)]
    p_with = ladder.Logit(cols, C).fit(tr, tr.y_reg3.to_numpy()).predict(te)
    p_without = ladder.Logit([c for c in cols if c not in group], C).fit(tr, tr.y_reg3.to_numpy()).predict(te)
    rng = np.random.default_rng(7)
    diff = []
    for _ in range(1000):
        i = rng.integers(0, len(te), len(te))
        diff.append(roc_auc_score(y_te[i], p_with[i]) - roc_auc_score(y_te[i], p_without[i]))
    first = group[0]
    rec = {}
    for name, m in (("2014-2017", d.snapshot.between(2014, 2017)), ("2018-2022", d.snapshot.between(2018, 2022))):
        part = d[m]
        r1, r0 = float((part.loc[part.y_reg3 == 1, first] > 0).mean()), float((part.loc[part.y_reg3 == 0, first] > 0).mean())
        rec[name] = {"rate_if_regular": round(r1, 4), "rate_if_not": round(r0, 4), "ratio": round(r1 / r0, 2) if r0 else None}
    out = {"group": group, "auc_with": round(float(roc_auc_score(y_te, p_with)), 4),
           "auc_without": round(float(roc_auc_score(y_te, p_without)), 4),
           "gain": round(float(np.mean(diff)), 4), "ci95": [round(float(np.percentile(diff, 2.5)), 4), round(float(np.percentile(diff, 97.5)), 4)],
           "recording_check": rec}
    (ladder.OUT / f"ablate_{prefix.rstrip('_')}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
