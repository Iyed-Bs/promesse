"""What Promesse adds to the market's view (the author's reframing, 2026), on T2 of the baseline ladder.

Not a gate: the Phase 4 gate in ladder.py stays as it is (engine vs the strongest benchmark: not passed). Here the
question is what public match records add on top of what the market already knows, so the ablation (engine + raters,
never shipped) is set against market value and against every rater together. Same frame, same settings chosen on T1
(read from the ladder's own json), same bootstrap of players; the T2 predictions are refitted and checked against the
json before anything is written.

    python models/ladder_adds.py   (Promesse venv) -> new key "promesse_adds_to_market" in lake/models/ladder_y_reg3.json
"""
import json

import numpy as np
from sklearn.metrics import roc_auc_score

import ladder as L

TARGET = "y_reg3"
PATH = L.OUT / f"ladder_{TARGET}.json"


def main() -> None:
    res = json.loads(PATH.read_text(encoding="utf-8"))
    d = L.frame(TARGET)
    cols = L.features(d)
    cfg = dict(res["settings_chosen_on_T1"])
    cfg["rater_cols"], cfg["ablation_cols"] = L.rater_cols(d), L.features(d, raters=True)
    tr, te = L.split(d, L.T2)
    preds = L.rungs(tr, te, TARGET, cols, cfg)
    y = te[TARGET].to_numpy()
    # the refit must reproduce the stored T2 numbers, or nothing is written
    for k, v in preds.items():
        stored = res["T2 (test)"]["rungs"][k]["auc"]
        assert abs(roc_auc_score(y, v) - stored) < 5e-4, (k, roc_auc_score(y, v), stored)
    abl = preds["6. ablation: gradient boosting + raters"]
    mv, raters = preds["1a. benchmark: market value"], preds["1c. benchmark: every rater together"]
    out = {"what": "T2 AUC differences with 95 % bootstrap intervals over players (1000 resamples, seed 7). The engine + raters "
                   "model is an ablation, never shipped: it says what public match records add once what the raters know "
                   "is in. The Phase 4 gate (engine alone vs the strongest benchmark) is unchanged and reported as not passed.",
           "t2_auc": {"engine_plus_raters": round(float(roc_auc_score(y, abl)), 4),
                      "market_value": round(float(roc_auc_score(y, mv)), 4),
                      "every_rater_together": round(float(roc_auc_score(y, raters)), 4),
                      "engine_gbm": res["T2 (test)"]["rungs"]["3. gradient boosting"]["auc"]},
           "n_test": int(len(te)), "n_players": int(te.player_id.nunique())}
    for key, lo_p in (("engine_plus_raters_minus_market_value", mv), ("engine_plus_raters_minus_every_rater", raters)):
        m, lo, hi = L.boot_gain(te, TARGET, abl, lo_p)
        out[key] = {"point": round(float(roc_auc_score(y, abl) - roc_auc_score(y, lo_p)), 4), "boot_mean": round(m, 4),
                    "ci95": [round(lo, 4), round(hi, 4)], "excludes_zero": bool(lo > 0)}
    res["promesse_adds_to_market"] = out
    PATH.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
