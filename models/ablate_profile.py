"""Ablation, (T2 only): what the inputs recorded on player profiles carry, now that recording is suspect.
Profile fields can be completed once a player is known (height and foot are missing for 4-6 % of the players who never
made it and almost never for those who did: audit_missing.py); MatchData's youth national-team stints come from career
pages crawled in 2026. Each variant refits the penalised logistic with T1's C on 2014-2020 and scores 2021-2022, with
the paired bootstrap against the current inputs.

    python models/ablate_profile.py     (Promesse venv) -> lake/models/ablate_profile.json
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ladder  # noqa: E402

OUT = Path((DATA_ROOT + "/lake/models/ablate_profile.json"))
YOUTH = ("yi_apps", "yi_top_level", "yi_selected", "senior_cap")
PROFILE = ("height", "left_foot")


class NoFlag(ladder.Logit):
    """The same model, without the missing flags of the profile fields (their value imputed, their absence silent)."""

    def fit(self, d, y):
        super().fit(d, y)
        self.flagged = [c for c in self.flagged if c not in PROFILE]
        self.m = ladder.LogisticRegression(C=self.C, max_iter=2000).fit(self._x(d), y)
        return self


def main() -> None:
    d = ladder.frame("y_reg3")
    lad = json.loads((ladder.OUT / "ladder_y_reg3.json").read_text(encoding="utf-8"))
    C = lad["settings_chosen_on_T1"]["C"]
    (a0, a1), (b0, b1) = ladder.T2
    tr, te = d[d.snapshot.between(a0, a1)], d[d.snapshot.between(b0, b1)]
    y_tr, y_te = tr.y_reg3.to_numpy(), te.y_reg3.to_numpy().astype(int)
    cols = ladder.features(d)
    variants = {"current inputs": (ladder.Logit, cols),
                "no youth national-team inputs": (ladder.Logit, [c for c in cols if c not in YOUTH]),
                "no missing flags on height and foot": (NoFlag, cols),
                "both": (NoFlag, [c for c in cols if c not in YOUTH])}
    p = {k: cls(cs, C).fit(tr, y_tr).predict(te) for k, (cls, cs) in variants.items()}
    rng = np.random.default_rng(7)
    idx = [rng.integers(0, len(te), len(te)) for _ in range(1000)]
    base = p["current inputs"]
    out = {"T2": {"train": [a0, a1], "test": [b0, b1], "n_test": int(len(te))}, "variants": {}}
    for k, v in p.items():
        diff = [roc_auc_score(y_te[i], v[i]) - roc_auc_score(y_te[i], base[i]) for i in idx]
        out["variants"][k] = {"auc": round(float(roc_auc_score(y_te, v)), 4),
                              "minus_current": round(float(np.mean(diff)), 4),
                              "ci95": [round(float(np.percentile(diff, 2.5)), 4), round(float(np.percentile(diff, 97.5)), 4)]}
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out["variants"], indent=1))


if __name__ == "__main__":
    main()
