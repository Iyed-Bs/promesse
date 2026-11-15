"""Projection v4: cross-fitted calibration and normalised widening on the v3 hurdle.

    python models/projection_v4.py t1                -> lake/models/projection_v4_t1_round2.json
    python models/projection_v4.py t2 <v3|v4a|v4b|v4c>  -> lake/models/projection_v4_t2.json   (once)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import GroupKFold

sys.path.insert(0, str(Path(__file__).resolve().parent))
import projection as P  # noqa: E402
import projection_hurdle as H  # noqa: E402

LEVELS = H.LEVELS
EPS = 1.0                                          # log units added to a band's width in the normalised score
NAMES = {0: "least senior evidence", 1: "middle evidence", 2: "most evidence", 3: "no senior minutes in two years"}


def fit_models(train, cols):
    played = (train.qmin3 > 0).astype(int)
    clfs = [H.classifier(s).fit(train[cols], played) for s in P.SEEDS]
    pos = train[train.qmin3 > 0]
    stage2 = {a: P.Averaged(a).fit(pos[cols], pos.qmin3) for a in LEVELS}
    return clfs, stage2


def predict_raw(models, part, cols):
    clfs, stage2 = models
    p = np.mean([c.predict_proba(part[cols])[:, 1] for c in clfs], axis=0)
    g = np.maximum.accumulate(np.column_stack([stage2[a].predict(part[cols]) for a in LEVELS]), axis=1)
    return p, g


def bands(p, g):
    q = {t: H.mixture_quantile(t, p, g) for t in (P.LO, P.MID, P.HI, 0.8)}
    q[P.HI] = np.where(q[P.LO] <= 0, q[0.8], q[P.HI])
    return q


def q80(x):
    x = np.sort(x)
    return float(x[min(len(x) - 1, int(np.ceil((len(x) + 1) * 0.8)) - 1)])


def wilson(c, n, z=1.96):
    mid = (c + z * z / (2 * n)) / (1 + z * z / n)
    half = z * ((c * (1 - c) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
    return [round(mid - half, 3), round(mid + half, 3)]


def evaluate(version, d, cols, fit_years, cal_years, test_years, crossfit, normalised):
    test = d[d.snapshot.between(*test_years)]
    if crossfit:
        data = d[d.snapshot.between(fit_years[0], cal_years[1])]
        oof_p, oof_g = np.zeros(len(data)), np.zeros((len(data), len(LEVELS)))
        for tr_i, va_i in GroupKFold(n_splits=4).split(data, groups=data.player_id):
            m = fit_models(data.iloc[tr_i], cols)
            oof_p[va_i], oof_g[va_i] = predict_raw(m, data.iloc[va_i], cols)
        cal = data
        raw_cal, g_cal = oof_p, oof_g
        final = fit_models(data, cols)
        fit_for_edges = data
    else:
        fit = d[d.snapshot.between(*fit_years)]
        cal = d[d.snapshot.between(*cal_years)]
        final = fit_models(fit, cols)
        raw_cal, g_cal = predict_raw(final, cal, cols)
        fit_for_edges = fit
    p_te_raw, g_te = predict_raw(final, test, cols)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw_cal, (cal.qmin3 > 0).astype(int))
    p_cal, p_te = iso.predict(raw_cal), iso.predict(p_te_raw)
    q_cal, q_te = bands(p_cal, g_cal), bands(p_te, g_te)
    edges = P.tier_edges(fit_for_edges)
    t_cal, t_te = P.tiers(cal, edges), P.tiers(test, edges)
    y_cal, y_te = cal.qmin3.to_numpy(), test.qmin3.to_numpy()
    miss = np.maximum(q_cal[P.LO] - y_cal, y_cal - q_cal[P.HI])
    w_cal, w_te = q_cal[P.HI] - q_cal[P.LO] + EPS, q_te[P.HI] - q_te[P.LO] + EPS
    score = miss / w_cal if normalised else miss
    pooled = q80(score)
    widen = {k: (q80(score[t_cal == k]) if (t_cal == k).sum() >= P.MIN_CAL else pooled) for k in range(4)}
    w = np.array([widen.get(int(k), 0.0) for k in t_te]) * (w_te if normalised else 1.0)
    lo, hi = np.maximum(q_te[P.LO] - w, 0.0), q_te[P.HI] + w
    inside = (y_te >= lo) & (y_te <= hi)
    by_tier = {}
    for k in np.unique(t_te):
        m = t_te == k
        c = float(inside[m].mean())
        ci = wilson(c, int(m.sum()))
        by_tier[NAMES[int(k)]] = {"n": int(m.sum()), "coverage": round(c, 3), "interval_95": ci,
                                  "width": round(float(np.median((hi - lo)[m])), 2),
                                  "ok": (0.77 <= c <= 0.83) if m.sum() >= 500 else (ci[0] <= 0.80 <= ci[1])}
    pin = sum(P.pinball(y_te, q_te[a], a) for a in (P.LO, P.MID, P.HI)) / 3
    interval = float(np.mean((hi - lo) + 10 * np.maximum(lo - y_te, 0) + 10 * np.maximum(y_te - hi, 0)))
    return {"version": version, "mean_pinball": round(pin, 4), "mean_interval_score": round(interval, 3),
            "coverage_80": round(float(inside.mean()), 3), "by_tier": by_tier, "gate_coverage": all(v["ok"] for v in by_tier.values()),
            "n_test": int(len(test))}


VERSIONS = {"v3": (False, False), "v4a": (True, False), "v4b": (False, True), "v4c": (True, True)}


def main() -> None:
    stage = sys.argv[1]
    d = P.frame()
    cols = P.cols_of(d)
    if stage == "t1":
        out = {}
        for v, (cf, nm) in VERSIONS.items():
            out[v] = evaluate(v, d, cols, (2014, 2015), (2016, 2017), (2020, 2020), cf, nm)
            print(json.dumps({k: x for k, x in out[v].items() if k != "by_tier"}), flush=True)
            for t, x in out[v]["by_tier"].items():
                print("   ", t, x, flush=True)
        (P.OUT / "projection_v4_t1_round2.json").write_text(json.dumps(out, indent=1))
    else:
        v = sys.argv[2]
        cf, nm = VERSIONS[v]
        r = evaluate(v, d, cols, (2014, 2016), (2017, 2018), (2021, 2022), cf, nm)
        (P.OUT / "projection_v4_t2.json").write_text(json.dumps(r, indent=1))
        print(json.dumps(r, indent=1))


if __name__ == "__main__":
    main()
