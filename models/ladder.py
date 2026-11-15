"""Promesse, Phase 4: the baseline ladder on the frozen targets (ARCHITECTURE D5).

The engines read what happened only; what others think of a player is a benchmark (models/inputs.py, 2026):
  0. base rate                    the training mean
  1a-c. benchmarks                market value, EA ratings, every rater together, each as a logistic forecast
  2. penalised logistic           every engine feature, standardised, median-imputed with missing flags; C chosen on T1
  3. gradient boosting            LightGBM on every engine feature, monotone where football says so (more quality
                                  minutes or a bigger share never lowers the chance); depth and rounds chosen on T1
  6. ablation                     gradient boosting + the raters: what their opinions add (reported, never shipped)

Time machines: T1 tunes (train snapshots 2014-2018, validate 2019-2020); T2 tests once (train 2014-2020, test 2021-2022);
T3 (2023) stays locked unless --open-t3. Population: under 21 at the snapshot. Target: y_reg3 by default.
Gate (Phase 4): the engine chosen on T1 beats the strongest benchmark on T2, the 95 % interval of the AUC gain above zero
(grouped by player).

    python models/ladder.py [--target y_reg3] [--open-t3]   (Promesse venv) -> lake/models/ladder_<target>.json, the project notes
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import argparse
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from inputs import RATERS, is_leaky, is_rater, silence

DATA = Path(DATA_ROOT)
GOLD = DATA / "lake" / "gold"
OUT = DATA / "lake" / "models"
T1 = ((2014, 2018), (2019, 2020))
T2 = ((2014, 2020), (2021, 2022))
T3 = ((2014, 2022), (2023, 2023))
LOGS = ["min_365", "min_730", "qmin_365", "qmin_730", "league_min_365", "europe_min_730", "apps_365", "mv_last", "mv_max",
        "mv_1y", "fm_min_365", "fm_youth_min_365"]
MONOTONE_UP = {"qmin_365", "qmin_730", "last_share", "best_share"}


def frame(target: str) -> pd.DataFrame:
    sp = pd.read_parquet(GOLD / "spine.parquet")
    t = pd.read_parquet(GOLD / "targets.parquet")[["player_id", "snapshot", target]]
    d = sp.merge(t, on=["player_id", "snapshot"], how="left")
    extra = GOLD / "spine_extra.parquet"                          # ProEngine: the shape of a career (spine_extra.py)
    if extra.exists():
        d = d.merge(pd.read_parquet(extra), on=["player_id", "snapshot"], how="left")
    m3 = DATA / "lake" / "models" / "m3_states.parquet"          # Phase 5: the fused rating, when it has been built
    if m3.exists():
        d = d.merge(pd.read_parquet(m3), on=["player_id", "snapshot"], how="left")
    d = d[(d.age < 21) & d[target].notna()].copy()
    d[target] = d[target].astype(int)
    for c in LOGS:
        d[c] = np.log1p(d[c].clip(lower=0))
    d["mv_growth"] = d.mv_last - d.mv_1y
    d["ea_gap"] = d.ea_potential - d.ea_overall
    for p in ("GK", "DEF", "MID", "ATT"):
        d[f"pos_{p}"] = (d.pos == p).astype(int)
    return silence(d)


def features(d: pd.DataFrame, raters: bool = False) -> list[str]:
    """The engine's inputs: what happened. raters=True adds the benchmarks back (the ablation, never shipped)."""
    skip = {"snapshot", "player_id", "pos"} | {c for c in d.columns if c.startswith(("kt_", "y_"))} | {"level3"}
    return [c for c in d.columns if c not in skip and pd.api.types.is_numeric_dtype(d[c])
            and (raters or not is_rater(c)) and not c.startswith("m3_") and not is_leaky(c)]


def rater_cols(d: pd.DataFrame) -> list[str]:
    return [c for c in RATERS if c in d.columns]


def split(d: pd.DataFrame, tm) -> tuple[pd.DataFrame, pd.DataFrame]:
    (a, b), (c, e) = tm
    return d[d.snapshot.between(a, b)], d[d.snapshot.between(c, e)]


class Logit:
    """Median imputation with missing flags, standardisation, L2 logistic."""

    def __init__(self, cols: list[str], C: float = 1.0):
        self.cols, self.C = cols, C

    def _x(self, d: pd.DataFrame) -> np.ndarray:
        x = d[self.cols].astype(float)
        miss = x.isna().astype(float).add_suffix("_na")
        x = (x.fillna(self.med) - self.mu) / self.sd
        return np.hstack([x.to_numpy(), miss[[c + "_na" for c in self.flagged]].to_numpy()])

    def fit(self, d: pd.DataFrame, y) -> "Logit":
        x = d[self.cols].astype(float)
        self.med = x.median().fillna(0.0)          # a feature empty in these years (PES, MatchData before 2021): 0 + its flag
        self.mu = x.fillna(self.med).mean()
        self.sd = x.fillna(self.med).std().replace(0, 1)
        self.flagged = [c for c in self.cols if x[c].isna().any()]
        self.m = LogisticRegression(C=self.C, max_iter=2000).fit(self._x(d), y)
        return self

    def predict(self, d: pd.DataFrame) -> np.ndarray:
        return self.m.predict_proba(self._x(d))[:, 1]


def gbm(cols: list[str], leaves: int, rounds: int) -> lgb.LGBMClassifier:
    mono = [1 if c in MONOTONE_UP else 0 for c in cols]
    return lgb.LGBMClassifier(n_estimators=rounds, learning_rate=0.03, num_leaves=leaves, min_child_samples=40,
                              subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                              monotone_constraints=mono, random_state=7, verbose=-1)


def metrics(y, p) -> dict:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    bins = np.minimum((p * 10).astype(int), 9)
    ece = sum(abs(p[bins == b].mean() - np.asarray(y)[bins == b].mean()) * (bins == b).mean() for b in range(10) if (bins == b).any())
    return {"auc": round(float(roc_auc_score(y, p)), 4), "brier": round(float(brier_score_loss(y, p)), 4),
            "logloss": round(float(log_loss(y, p)), 4), "ece": round(float(ece), 4)}


def rungs(tr: pd.DataFrame, te: pd.DataFrame, target: str, cols: list[str], cfg: dict) -> dict[str, np.ndarray]:
    y = tr[target].to_numpy()
    out = {"0. base rate": np.full(len(te), y.mean())}
    # the benchmarks: what others think of the player, each turned into a forecast and scored like an engine
    out["1a. benchmark: market value"] = Logit(["mv_last"]).fit(tr, y).predict(te)
    out["1b. benchmark: EA ratings"] = Logit(["ea_overall", "ea_potential"]).fit(tr, y).predict(te)
    out["1c. benchmark: every rater together"] = Logit(cfg["rater_cols"], cfg["C"]).fit(tr, y).predict(te)
    # Promesse's engines: what happened, nothing else (inputs.py)
    out["2. penalised logistic"] = Logit(cols, cfg["C"]).fit(tr, y).predict(te)
    g = gbm(cols, cfg["leaves"], cfg["rounds"]).fit(tr[cols], y)
    out["3. gradient boosting"] = g.predict_proba(te[cols])[:, 1]
    cfg["_importance"] = dict(sorted(zip(cols, g.booster_.feature_importance("gain").round(1)), key=lambda kv: -kv[1])[:12])
    # the ablation, never shipped: the same engine with the raters added, to know what their opinions carry
    ac = cfg["ablation_cols"]
    g6 = gbm(ac, cfg["leaves"], cfg["rounds"]).fit(tr[ac], y)
    out["6. ablation: gradient boosting + raters"] = g6.predict_proba(te[ac])[:, 1]
    return out


def tune(d: pd.DataFrame, target: str, cols: list[str]) -> dict:
    tr, va = split(d, T1)
    y, yv = tr[target].to_numpy(), va[target].to_numpy()
    best_c = max((0.03, 0.1, 0.3, 1.0), key=lambda C: roc_auc_score(yv, Logit(cols, C).fit(tr, y).predict(va)))
    best = None
    for leaves in (7, 15, 31):
        g = gbm(cols, leaves, 2000).fit(tr[cols], y, eval_X=(va[cols],), eval_y=(yv,), eval_metric="auc",
                                        callbacks=[lgb.early_stopping(100, verbose=False)])
        auc = roc_auc_score(yv, g.predict_proba(va[cols], num_iteration=g.best_iteration_)[:, 1])
        if best is None or auc > best[0]:
            best = (auc, leaves, max(50, int(g.best_iteration_ or 200)))
    return {"C": best_c, "leaves": best[1], "rounds": best[2]}


def boot_gain(te: pd.DataFrame, target: str, p_hi, p_lo, n: int = 1000, seed: int = 7) -> tuple[float, float, float]:
    """AUC(hi) - AUC(lo) on resamples of players (all of a player's snapshots go together)."""
    rng = np.random.default_rng(seed)
    y = te[target].to_numpy()
    ids = te.player_id.to_numpy()
    uniq = np.unique(ids)
    pos = {u: np.flatnonzero(ids == u) for u in uniq}
    gains = []
    for _ in range(n):
        idx = np.concatenate([pos[u] for u in rng.choice(uniq, len(uniq))])
        if y[idx].min() == y[idx].max():
            continue
        gains.append(roc_auc_score(y[idx], p_hi[idx]) - roc_auc_score(y[idx], p_lo[idx]))
    return float(np.mean(gains)), float(np.percentile(gains, 2.5)), float(np.percentile(gains, 97.5))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="y_reg3")
    ap.add_argument("--open-t3", action="store_true")
    a = ap.parse_args()
    d = frame(a.target)
    cols = features(d)
    cfg = tune(d, a.target, cols)
    cfg["rater_cols"], cfg["ablation_cols"] = rater_cols(d), features(d, raters=True)
    res = {"target": a.target, "population": "under 21 at the snapshot", "features": cols, "benchmarks": cfg["rater_cols"],
           "inputs_rule": "engines read what happened only; raters are benchmarks (models/inputs.py, 2026)",
           "settings_chosen_on_T1": {k: v for k, v in cfg.items() if not k.startswith("_") and not k.endswith("_cols")}}
    engines, benches = ("2. penalised logistic", "3. gradient boosting"), (
        "1a. benchmark: market value", "1b. benchmark: EA ratings", "1c. benchmark: every rater together")
    for name, tm in (("T1 (validation)", T1), ("T2 (test)", T2)) + ((("T3 (locked)", T3),) if a.open_t3 else ()):
        tr, te = split(d, tm)
        preds = rungs(tr, te, a.target, cols, cfg)
        y = te[a.target].to_numpy()
        block = {"train": f"{tm[0][0]}-{tm[0][1]}", "test": f"{tm[1][0]}-{tm[1][1]}", "n_train": int(len(tr)),
                 "n_test": int(len(te)), "base_rate_test": round(float(y.mean()), 4),
                 "rungs": {k: metrics(y, v) for k, v in preds.items()}}
        g, lo, hi = boot_gain(te, a.target, preds["3. gradient boosting"], preds["1a. benchmark: market value"])
        block["gbm_minus_market_value_auc"] = {"mean": round(g, 4), "ci95": [round(lo, 4), round(hi, 4)]}
        g2, lo2, hi2 = boot_gain(te, a.target, preds["3. gradient boosting"], preds["2. penalised logistic"])
        block["gbm_minus_logistic_auc"] = {"mean": round(g2, 4), "ci95": [round(lo2, 4), round(hi2, 4)]}
        block["top_features_gbm"] = {k: float(v) for k, v in cfg["_importance"].items()}
        block["_preds"], block["_te"] = preds, te
        res[name] = block
    # Phase 4 gate: the engine chosen on T1 against the strongest benchmark on T2 (the hardest opponent there is)
    engine = max(engines, key=lambda k: res["T1 (validation)"]["rungs"][k]["auc"])
    t2b = res["T2 (test)"]
    bench = max(benches, key=lambda k: t2b["rungs"][k]["auc"])
    g4, lo4, hi4 = boot_gain(t2b["_te"], a.target, t2b["_preds"][engine], t2b["_preds"][bench])
    abl = boot_gain(t2b["_te"], a.target, t2b["_preds"]["6. ablation: gradient boosting + raters"],
                    t2b["_preds"]["3. gradient boosting"])
    res["gate_phase4"] = {"rule": "Promesse's engine (chosen on T1) beats the strongest benchmark on T2 (95 % interval above zero)",
                          "engine": engine, "benchmark": bench, "mean": round(g4, 4), "ci95": [round(lo4, 4), round(hi4, 4)],
                          "passed": lo4 > 0}
    res["ablation_raters"] = {"what": "gradient boosting + raters minus gradient boosting, T2 AUC: what the raters' opinions add",
                              "mean": round(abl[0], 4), "ci95": [round(abl[1], 4), round(abl[2], 4)]}
    for name in [k for k in res if k.startswith("T")]:
        res[name].pop("_preds"), res[name].pop("_te")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"ladder_{a.target}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    lines = [f"# The baseline ladder: {a.target}", "", f"Population: {res['population']}. Settings chosen on T1: "
             f"{res['settings_chosen_on_T1']}.", ""]
    for name in [k for k in res if k.startswith("T")]:
        b = res[name]
        lines += [f"## {name}: train {b['train']}, test {b['test']} (n = {b['n_test']}, base rate {b['base_rate_test']})", "",
                  "| Rung | AUC | Brier | Log loss | ECE |", "|---|---|---|---|---|"]
        lines += [f"| {k} | {v['auc']} | {v['brier']} | {v['logloss']} | {v['ece']} |" for k, v in b["rungs"].items()]
        gm, gl = b["gbm_minus_market_value_auc"], b["gbm_minus_logistic_auc"]
        lines += ["", f"Gradient boosting minus market value: AUC {gm['mean']:+.4f} (95 % {gm['ci95'][0]:+.4f} to {gm['ci95'][1]:+.4f}); "
                  f"minus logistic: {gl['mean']:+.4f} ({gl['ci95'][0]:+.4f} to {gl['ci95'][1]:+.4f}).", ""]
    g4, ab = res["gate_phase4"], res["ablation_raters"]
    lines += [f"**Phase 4 gate**: {g4['rule']}: {'passed' if g4['passed'] else 'not passed'} ({g4['engine']} vs "
              f"{g4['benchmark']}: AUC {g4['mean']:+.4f}, 95 % {g4['ci95'][0]:+.4f} to {g4['ci95'][1]:+.4f}).", "",
              f"Ablation (never shipped): adding the raters to the engine changes T2 AUC by {ab['mean']:+.4f} "
              f"(95 % {ab['ci95'][0]:+.4f} to {ab['ci95'][1]:+.4f}).", ""]
    (OUT / f"LADDER_{a.target}.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    if a.target == "y_reg3" and not a.open_t3:         # the reframed question: what the engine adds to the raters
        import ladder_adds
        ladder_adds.main()


if __name__ == "__main__":
    main()
