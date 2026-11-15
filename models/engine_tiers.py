"""Track 2 of the project notes: evidence tiers and ensembles on the engine's inputs (A = ProEngine 0.1 inputs, B = ProEngine 0.2 inputs).

    python models/engine_tiers.py t1                  -> lake/models/engine_tiers_t1.json
    python models/engine_tiers.py t2 <version> <A|B>  -> lake/models/engine_tiers_t2.json   (once)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine_v2 as E  # noqa: E402
import ladder  # noqa: E402

SHAPE = ["growth_q", "share_trend", "level_step", "cohort_pct"]
RICH_LOG = float(np.log1p(900))


def tier_of(d) -> np.ndarray:
    m = d.min_365.fillna(0).to_numpy()                # min_365 is log1p already (ladder.frame)
    return np.where(m <= 0, 0, np.where(m < RICH_LOG, 1, 2))


def tiered_logit(tr, te, cols, y, tune: bool, cfg=None, drop_shape=False):
    """One penalised logistic per tier. C per tier chosen on the validation years or taken from cfg (the test)."""
    ttr, tte = tier_of(tr), tier_of(te)
    p, cs = np.zeros(len(te)), {}
    for k in (0, 1, 2):
        cc = [c for c in cols if not (drop_shape and k == 2 and c in SHAPE)]
        a, b = ttr == k, tte == k
        if not b.any():
            continue
        if tune:
            yv = te.y_reg3.to_numpy()[b]
            cs[k] = max((0.01, 0.03, 0.1, 0.3, 1.0), key=lambda C: roc_auc_score(yv, ladder.Logit(cc, C).fit(tr[a], y[a]).predict(te[b])))
        else:
            cs[k] = cfg[str(k)]
        p[b] = ladder.Logit(cc, cs[k]).fit(tr[a], y[a]).predict(te[b])
    return p, cs


def predictions(d, ver: str, inputs: str, tm, cfg=None):
    tr, te = ladder.split(d, tm)
    v = "v2a" if inputs == "B" else "v1"
    cols = E.cols_of(d, v)
    tr, te = E.silence_fm(tr, te, cols)
    y = tr.y_reg3.to_numpy()
    E._VERSION = v
    gcfg = E._tune(tr, te, cols, tm)
    p_log = ladder.Logit(cols, gcfg["C"]).fit(tr, y).predict(te)
    p_gbm = ladder.gbm(cols, gcfg["leaves"], gcfg["rounds"]).fit(tr[cols], y).predict_proba(te[cols])[:, 1]
    out = {"baseline_logistic": p_log, "baseline_gbm": p_gbm}
    tcfg = {}
    if ver in ("v3a", "v3b", "v3d"):
        p_t, tcfg = tiered_logit(tr, te, cols, y, tune=tm == ladder.T1, cfg=cfg, drop_shape=(ver == "v3b"))
        out["version"] = (p_t + p_gbm) / 2 if ver == "v3d" else p_t
    elif ver == "v3c":
        out["version"] = (p_log + p_gbm) / 2
    return te, out, {"gbm": gcfg, "tiers": tcfg}


def main() -> None:
    stage = sys.argv[1]
    d = E.build()
    if stage == "t1":
        res = {}
        for inputs in ("A", "B"):
            for ver in ("v3a", "v3b", "v3c", "v3d"):
                te, out, cfg = predictions(d, ver, inputs, ladder.T1)
                b_name = "baseline_logistic" if inputs == "A" else "baseline_gbm"      # as chosen on T1 (engine_v2_t1.json)
                g, lo, hi = ladder.boot_gain(te, "y_reg3", out["version"], out[b_name])
                key = f"{inputs}/{ver}"
                res[key] = {"auc": round(float(roc_auc_score(te.y_reg3, out["version"])), 4), "baseline": b_name,
                            "baseline_auc": round(float(roc_auc_score(te.y_reg3, out[b_name])), 4),
                            "gain": {"mean": round(g, 4), "ci95": [round(lo, 4), round(hi, 4)]}, "cfg": cfg}
                print(key, res[key], flush=True)
        json.dump(res, open(E.OUT / "engine_tiers_t1.json", "w"), indent=1)
    else:
        ver, inputs = sys.argv[2], sys.argv[3]
        cfg = json.load(open(E.OUT / "engine_tiers_t1.json"))[f"{inputs}/{ver}"]["cfg"]
        te, out, _ = predictions(d, ver, inputs, ladder.T2, cfg=cfg["tiers"])
        b_name = "baseline_logistic" if inputs == "A" else "baseline_gbm"
        g, lo, hi = ladder.boot_gain(te, "y_reg3", out["version"], out[b_name])
        lad = json.load(open(E.OUT / "ladder_y_reg3.json"))["T2 (test)"]
        tr_ = ladder.split(d, ladder.T2)[0]
        mv = ladder.Logit(["mv_last"]).fit(tr_, tr_.y_reg3.to_numpy()).predict(te)
        g2, lo2, hi2 = ladder.boot_gain(te, "y_reg3", out["version"], mv)
        res = {"version": ver, "inputs": inputs, "auc": float(roc_auc_score(te.y_reg3, out["version"])),
               "baseline": b_name, "baseline_auc": float(roc_auc_score(te.y_reg3, out[b_name])),
               "gain_over_baseline": {"mean": g, "ci95": [lo, hi]}, "gap_to_market_value": {"mean": g2, "ci95": [lo2, hi2]},
               "market_value_auc_stored": lad["rungs"]["1a. benchmark: market value"]["auc"]}
        json.dump(res, open(E.OUT / "engine_tiers_t2.json", "w"), indent=1)
        print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
