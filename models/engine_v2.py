"""Engine v2: MatchData per-90 stats from the backfill years. T1 compares the versions; T2 runs once,
for the version T1 chose.  Gate A (audit_fm.py) failed as written, so the registered consequence applies: the absence of
the fm2 inputs is silenced (median of the fitting years, no missing flag).

    python models/engine_v2.py t1                 -> lake/models/engine_v2_t1.json
    python models/engine_v2.py t2 <version>       -> lake/models/engine_v2_t2.json   (once)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ladder  # noqa: E402

OUT = ladder.OUT
FM_RAW = ["fm2_chances90", "fm2_dribbles90", "fm2_boxtouch90", "fm2_final3_90", "fm2_defact90", "fm2_duel_rate",
          "fm2_pass_acc", "fm2_xgxa90"]
FM_OTHER = ["fm2_start_share", "fm2_stat_cov", "fm2_min_365"]


def build() -> pd.DataFrame:
    d = ladder.frame("y_reg3")
    f = pd.read_parquet(OUT / "fm_feats.parquet")
    d = d.merge(f, on=["player_id", "snapshot"], how="left")
    d = d.replace([np.inf, -np.inf], np.nan)
    d["fm2_min_365"] = np.log1p(d.fm2_min_365.clip(lower=0))
    return d


def cols_of(d: pd.DataFrame, version: str) -> list[str]:
    base = [c for c in ladder.features(d) if not c.startswith("fm2_")]
    if version == "v1":
        return base
    base = [c for c in base if c != "fm_min_365"]                       # replaced by fm2_min_365 (backfill + main)
    raw = FM_RAW + FM_OTHER
    if version == "v2c":
        raw = [c + "_adj" if c in FM_RAW else c for c in raw]
    return base + raw


def silence_fm(tr: pd.DataFrame, te: pd.DataFrame, cols: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Absence carries nothing: fill the fm2 per-90 inputs with the fitting years' median (no flag)."""
    tr, te = tr.copy(), te.copy()
    for c in cols:
        if c.startswith("fm2_"):
            m = tr[c].median()
            tr[c], te[c] = tr[c].fillna(m), te[c].fillna(m)
    return tr, te


def run(d: pd.DataFrame, version: str, tm) -> dict:
    tr, te = ladder.split(d, tm)
    if version == "v2b":
        tr = tr[tr.snapshot >= 2017]
    cols = cols_of(d, version)
    tr, te = silence_fm(tr, te, cols)
    cfg = _tune(tr, te, cols, tm)
    y, yt = tr.y_reg3.to_numpy(), te.y_reg3.to_numpy()
    p_log = ladder.Logit(cols, cfg["C"]).fit(tr, y).predict(te)
    g = ladder.gbm(cols, cfg["leaves"], cfg["rounds"]).fit(tr[cols], y)
    p_gbm = g.predict_proba(te[cols])[:, 1]
    return {"cfg": cfg, "auc_logistic": float(roc_auc_score(yt, p_log)), "auc_gbm": float(roc_auc_score(yt, p_gbm)),
            "n_train": int(len(tr)), "n_test": int(len(te)), "_p_gbm": p_gbm, "_p_log": p_log, "_te": te, "n_cols": len(cols),
            "top": {k: float(v) for k, v in sorted(zip(cols, g.booster_.feature_importance("gain")), key=lambda kv: -kv[1])[:10]}}


def _tune(tr, te, cols, tm):
    """The settings are chosen on T1's validation years; for T2 they are the ones T1 chose for this version."""
    if tm == ladder.T1:
        import lightgbm as lgb
        yv = te.y_reg3.to_numpy()
        y = tr.y_reg3.to_numpy()
        best_c = max((0.03, 0.1, 0.3, 1.0), key=lambda C: roc_auc_score(yv, ladder.Logit(cols, C).fit(tr, y).predict(te)))
        best = None
        for leaves in (7, 15, 31):
            g = ladder.gbm(cols, leaves, 2000).fit(tr[cols], y, eval_set=[(te[cols], yv)], eval_metric="auc",
                                                    callbacks=[lgb.early_stopping(100, verbose=False)])
            auc = roc_auc_score(yv, g.predict_proba(te[cols], num_iteration=g.best_iteration_)[:, 1])
            if best is None or auc > best[0]:
                best = (auc, leaves, max(50, int(g.best_iteration_ or 200)))
        return {"C": best_c, "leaves": best[1], "rounds": best[2]}
    t1 = json.loads((OUT / "engine_v2_t1.json").read_text())
    return t1["versions"][_VERSION]["cfg"]


_VERSION = "v1"


def main() -> None:
    global _VERSION
    stage = sys.argv[1]
    d = build()
    if stage == "t1":
        res = {"versions": {}}
        base = None
        for v in ("v1", "v2a", "v2b", "v2c"):
            _VERSION = v
            r = run(d, v, ladder.T1)
            best = "gbm" if r["auc_gbm"] >= r["auc_logistic"] else "logistic"
            r["engine"], r["auc"] = best, r[f"auc_{best}"]
            if base is None:
                base = {k: r[k] for k in ("engine", "n_test", "_p_gbm", "_p_log")}
            lo_p = base["_p_gbm"] if base["engine"] == "gbm" else base["_p_log"]
            hi_p = r["_p_gbm"] if best == "gbm" else r["_p_log"]
            if r["n_test"] == base["n_test"]:
                g, lo, hi = ladder.boot_gain(r["_te"], "y_reg3", hi_p, lo_p)
                r["gain_over_v1"] = {"mean": round(g, 4), "ci95": [round(lo, 4), round(hi, 4)]}
            for k in ("_p_gbm", "_p_log", "_te"):
                r.pop(k)
            res["versions"][v] = r
            print(v, {k: (round(x, 4) if isinstance(x, float) else x) for k, x in r.items() if k not in ("top", "cfg")}, r["cfg"], flush=True)
        (OUT / "engine_v2_t1.json").write_text(json.dumps(res, indent=1))
    else:
        v = sys.argv[2]
        _VERSION = v
        r1 = run(d, "v1", ladder.T2) if False else None
        _VERSION = "v1"
        base = run(d, "v1", ladder.T2)
        _VERSION = v
        r = run(d, v, ladder.T2)
        for rr in (base, r):
            rr["engine"] = "gbm" if rr["auc_gbm"] >= rr["auc_logistic"] else "logistic"
        # the engine kind is the one T1 chose for each version (not the T2 winner)
        t1 = json.loads((OUT / "engine_v2_t1.json").read_text())["versions"]
        pick = lambda rr, vv: rr["_p_gbm"] if t1[vv]["engine"] == "gbm" else rr["_p_log"]  # noqa: E731
        g, lo, hi = ladder.boot_gain(r["_te"], "y_reg3", pick(r, v), pick(base, "v1"))
        lad = json.loads((OUT / "ladder_y_reg3.json").read_text())["T2 (test)"]
        mv_p = ladder.Logit(["mv_last"]).fit(*[ladder.split(d, ladder.T2)[0], ladder.split(d, ladder.T2)[0].y_reg3.to_numpy()]).predict(r["_te"])
        g2, lo2, hi2 = ladder.boot_gain(r["_te"], "y_reg3", pick(r, v), mv_p)
        out = {"version": v, "auc_v1": float(roc_auc_score(r["_te"].y_reg3, pick(base, "v1"))),
               "auc_version": float(roc_auc_score(r["_te"].y_reg3, pick(r, v))),
               "gain_over_v1": {"mean": g, "ci95": [lo, hi]}, "gap_to_market_value": {"mean": g2, "ci95": [lo2, hi2]},
               "market_value_auc_stored": lad["rungs"]["1a. benchmark: market value"]["auc"]}
        (OUT / "engine_v2_t2.json").write_text(json.dumps(out, indent=1))
        print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
