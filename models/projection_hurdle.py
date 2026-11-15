"""Promesse, Phase 6 v3 (candidate): the hurdle projection. Same target, population, years, tiers, conformal layer and
gate as models/projection.py v2, so the two compare directly; judged on T2 only.

Why: the outcome (log(1 + quality minutes over the next three seasons)) is two things at once, whether he plays senior
football at all and how much if he does. One set of quantiles fits that badly: v2's bands for players with no senior
minutes in two years are 7.8 log units wide and hold 87 % on T2 (23 % of them play nothing, 77 % something).
  stage 1  P(he plays): LightGBM classifier (five seeds averaged), calibrated by isotonic regression on the calibration
           years.
  stage 2  how much, given he plays: LightGBM quantile models at 13 levels on the fitting years' players who played.
  band     from the mixture: with p = P(plays), its quantile at t is 0 when t <= 1 - p, else the stage-2 quantile at
           (t - (1 - p)) / p (levels interpolated, crossing removed). The 80 % band is the 10th to 90th percentile when
           he plays with more than 90 % probability; otherwise his 10th percentile is the zero itself, the central band
           [0, 90th] would hold 90 %, and the 80 % band is [0, 80th]. When his chance of playing is below 20 %, the
           band is the zero alone and holds 1 - p: no honest band does better, so the report gives each tier's best
           achievable coverage beside the measured one. Then v2's conformal layer.

    python models/projection_hurdle.py              (Promesse venv) -> lake/models/projection_hurdle.json, PROJECTION_HURDLE.md
    python models/projection_hurdle.py --open-t3    T3 once, only when the maintainer asks for it: fit 2014-2020, calibrate 2021-2022,
                                                    test 2023 -> projection_hurdle_t3.json, PROJECTION_HURDLE_T3.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
from sklearn.isotonic import IsotonicRegression

sys.path.insert(0, str(Path(__file__).resolve().parent))
import projection as P  # noqa: E402

LEVELS = np.array([0.02, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.98])


def classifier(seed: int) -> lgb.LGBMClassifier:
    return lgb.LGBMClassifier(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=40, subsample=0.8,
                              subsample_freq=1, colsample_bytree=0.8, random_state=seed, verbose=-1)


def mixture_quantile(t: float, p: np.ndarray, g: np.ndarray) -> np.ndarray:
    """Per player: the mixture's quantile at t, with p = P(plays) and g = his stage-2 quantiles at LEVELS."""
    out = np.zeros(len(p))
    on = t > 1 - p
    u = np.clip((t - (1 - p[on])) / np.maximum(p[on], 1e-9), LEVELS[0], LEVELS[-1])
    out[on] = [np.interp(ui, LEVELS, gi) for ui, gi in zip(u, g[on])]
    return out


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--open-t3", action="store_true")   # once, only when the maintainer asks for it
    ap.add_argument("--settled", action="store_true")   # calibrate on years settled when the test starts
    args = ap.parse_args()
    open_t3 = args.open_t3
    windows = P.T3 if open_t3 else ((2014, 2016), (2017, 2018), P.TEST) if args.settled else (P.FIT, P.CAL, P.TEST)
    suffix = "_t3" if open_t3 else "_settled" if args.settled else ""
    d = P.frame()
    # the moves inputs are out (inputs.LEAKY,). Seen first here: with them, the least-evidence tier held 91 %
    # on T2 (P(he plays) 7 points high); out of stage 1 only, 86.6 %; out of both, 80.9 %
    cols = P.cols_of(d)
    fit, cal, test = (d[d.snapshot.between(*w)] for w in windows)
    edges = P.tier_edges(fit)
    played_fit = (fit.qmin3 > 0).astype(int)
    clfs = [classifier(s).fit(fit[cols], played_fit) for s in P.SEEDS]
    raw = lambda part: np.mean([c.predict_proba(part[cols])[:, 1] for c in clfs], axis=0)  # noqa: E731
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw(cal), (cal.qmin3 > 0).astype(int))
    pos = fit[fit.qmin3 > 0]
    stage2 = {a: P.Averaged(a).fit(pos[cols], pos.qmin3) for a in LEVELS}

    def bands(part):
        p = iso.predict(raw(part))
        g = np.maximum.accumulate(np.column_stack([stage2[a].predict(part[cols]) for a in LEVELS]), axis=1)
        q = {t: mixture_quantile(t, p, g) for t in (P.LO, P.MID, P.HI, 0.8)}
        # a zero at the 10th percentile: the 80 % band is [0, 80th], not [0, 90th]
        q[P.HI] = np.where(q[P.LO] <= 0, q[0.8], q[P.HI])
        return p, q
    p_cal, q_cal = bands(cal)
    p_test, q_test = bands(test)
    y_cal, y_test = cal.qmin3.to_numpy(), test.qmin3.to_numpy()
    t_cal, t_test = P.tiers(cal, edges), P.tiers(test, edges)
    score = np.maximum(q_cal[P.LO] - y_cal, y_cal - q_cal[P.HI])

    def q80(x: np.ndarray) -> float:
        x = np.sort(x)
        return float(x[min(len(x) - 1, int(np.ceil((len(x) + 1) * 0.8)) - 1)])
    pooled = q80(score)
    widen = {k: (q80(score[t_cal == k]) if (t_cal == k).sum() >= P.MIN_CAL else pooled) for k in range(4)}
    w = np.array([widen.get(int(k), 0.0) for k in t_test])
    lo, hi = np.maximum(q_test[P.LO] - w, 0.0), q_test[P.HI] + w
    raw_in = (y_test >= q_test[P.LO]) & (y_test <= q_test[P.HI])
    cal_in = (y_test >= lo) & (y_test <= hi)
    names = {0: "least senior evidence", 1: "middle evidence", 2: "most evidence", 3: "no senior minutes in two years"}

    def wilson(c: float, n: int, z: float = 1.96) -> list[float]:
        mid = (c + z * z / (2 * n)) / (1 + z * z / n)
        half = z * ((c * (1 - c) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
        return [round(mid - half, 3), round(mid + half, 3)]
    by_tier = {}
    for k in np.unique(t_test):
        m = t_test == k
        c = float(cal_in[m].mean())
        ci = wilson(c, int(m.sum()))
        by_tier[names[int(k)]] = {"n": int(m.sum()), "raw_80": round(float(raw_in[m].mean()), 3), "calibrated_80": round(c, 3),
                                  "interval_95": ci, "width": round(float(np.median((hi - lo)[m])), 2),
                                  "plays_predicted": round(float(p_test[m].mean()), 3),
                                  "best_achievable": round(float(np.maximum(0.8, 1 - p_test[m]).mean()), 3),
                                  "plays_observed": round(float((y_test[m] > 0).mean()), 3),
                                  "ok": (0.77 <= c <= 0.83) if m.sum() >= 500 else (ci[0] <= 0.80 <= ci[1])}
    pin = round(sum(P.pinball(y_test, q_test[a], a) for a in (P.LO, P.MID, P.HI)) / 3, 4)
    v2 = json.loads((P.OUT / "projection_qmin3.json").read_text(encoding="utf-8"))
    res = {"version": "v3 candidate (hurdle)", "fit": windows[0], "calibrate": windows[1], "test": windows[2], "t3_opened": open_t3,
           "coverage_80": {"raw": round(float(raw_in.mean()), 3), "calibrated": round(float(cal_in.mean()), 3)},
           "by_tier": by_tier, "mean_pinball": {"hurdle": pin, "v2": v2.get("mean_pinball", {}).get("model")},
           "plays_brier": round(float(np.mean((p_test - (y_test > 0)) ** 2)), 4),
           "gate_phase6": {"rule": "v1.3's: tiers of 500+ players hold 77-83 %; a smaller tier's 95 % interval contains 80 %",
                           "passed": all(v["ok"] for v in by_tier.values())}}
    (P.OUT / f"projection_hurdle{suffix}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    lines = ["# Projection v3 candidate: the hurdle", "",
             f"Fit {windows[0][0]}-{windows[0][1]}, calibrate {windows[1][0]}-{windows[1][1]}, test {windows[2][0]}-{windows[2][1]}"
             f"{' (T3, opened once)' if open_t3 else ' (T2 only; T3 closed)'}.", "",
             "| Tier | Players | Before | After | 95 % | Best achievable | Width | Plays: predicted / observed |", "|---|---|---|---|---|---|---|---|"]
    lines += [f"| {k} | {v['n']} | {v['raw_80']:.1%} | {v['calibrated_80']:.1%} | {v['interval_95'][0]:.0%}-{v['interval_95'][1]:.0%} | {v['best_achievable']:.1%} | "
              f"{v['width']} | {v['plays_predicted']:.1%} / {v['plays_observed']:.1%} |" for k, v in by_tier.items()]
    lines += ["", f"Mean pinball: hurdle {pin}, v2 {res['mean_pinball']['v2']}. Brier of 'he plays': {res['plays_brier']}.",
              "", f"**Phase 6 gate** (v1.3 rule): {'passed' if res['gate_phase6']['passed'] else 'not passed'}."]
    (P.OUT / f"PROJECTION_HURDLE{suffix.upper()}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
