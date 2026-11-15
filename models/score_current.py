"""Promesse: score the latest snapshot with the models whose gates passed, for the Scout Desk.

Only what has earned it is shown:
  - the ladder's champion for y_reg3 (Phase 4): the chance of a regular place in the 31 leagues within three seasons;
    today the penalised logistic (gradient boosting did not beat it on T2), refit on every labelled year
  - the projection (Phase 6): quality minutes over the next three seasons, P10 / P50 / P90, refit on every labelled
    year with the conformal widening from the latest two
M3 (Phase 5) has not passed: its fused rating is not shown.

    python models/score_current.py      (Promesse venv) -> lake/models/current_outlook.parquet, current_outlook.json
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ladder        # noqa: E402  (the same feature preparation and models the gates judged)
import projection    # noqa: E402

DATA = Path(DATA_ROOT)
GOLD = DATA / "lake" / "gold"
OUT = DATA / "lake" / "models"


def prepare(sp: pd.DataFrame) -> pd.DataFrame:
    d = sp.copy()
    for c in ladder.LOGS:
        d[c] = np.log1p(d[c].clip(lower=0))
    d["mv_growth"] = d.mv_last - d.mv_1y
    d["ea_gap"] = d.ea_potential - d.ea_overall
    for p in ("GK", "DEF", "MID", "ATT"):
        d[f"pos_{p}"] = (d.pos == p).astype(int)
    return ladder.silence(d)


def main() -> None:
    cur = pd.read_parquet(GOLD / "spine_current.parquet")
    extra = GOLD / "spine_extra.parquet"                              # ProEngine's career-shape features, same snapshot
    if extra.exists():
        cur = cur.merge(pd.read_parquet(extra), on=["player_id", "snapshot"], how="left")
    cur = prepare(cur)
    cur = cur[cur.age < 21].copy()
    out = cur[["player_id", "snapshot", "age"]].copy()
    gates = {}

    # Phase 4's champion for y_reg3
    lad = json.loads((OUT / "ladder_y_reg3.json").read_text(encoding="utf-8"))
    gates["phase4"] = lad.get("gate_phase4", {}).get("passed")
    t2 = lad["T2 (test)"]["rungs"]
    champion = "3. gradient boosting" if t2["3. gradient boosting"]["auc"] - t2["2. penalised logistic"]["auc"] > 0 and \
        lad["T2 (test)"]["gbm_minus_logistic_auc"]["ci95"][0] > 0 else "2. penalised logistic"
    d = ladder.frame("y_reg3")
    cols = ladder.features(d)
    for c in cols:
        if c not in cur.columns:
            cur[c] = np.nan
    # B: a call that has not beaten the ratings still shows, labelled as behind market value; the
    # gate stays what it is (False) and the desk reads `calls_status` to word it. Clean inputs only (ladder.features).
    demo = not gates["phase4"]
    if gates["phase4"] or demo:
        C = lad["settings_chosen_on_T1"]["C"]
        if demo or champion == "2. penalised logistic":
            m = ladder.Logit(cols, C).fit(d, d.y_reg3.to_numpy())
            out["p_reg3"] = m.predict(cur)
            # what each call is made of: the model term by term (models/explain.py), for the desk's player pages
            import explain
            icpt, long = explain.contributions(m, cur.reset_index(drop=True))
            long["player_id"] = cur.player_id.reset_index(drop=True).to_numpy()[long.row]
            long.drop(columns="row").to_parquet(OUT / "current_contributions.parquet", index=False)
            (OUT / "current_engine.json").write_text(json.dumps({
                "intercept": icpt, "C": C, "inputs": list(m.cols), "flagged": list(m.flagged),
                "coef": dict(zip(list(m.cols) + [c + "_na" for c in m.flagged], map(float, m.m.coef_[0]))),
                "mean": {k: float(v) for k, v in m.mu.items()}, "sd": {k: float(v) for k, v in m.sd.items()},
                "median": {k: float(v) for k, v in m.med.items()}}, indent=1), encoding="utf-8")
        else:
            s = lad["settings_chosen_on_T1"]
            g = ladder.gbm(cols, s["leaves"], s["rounds"]).fit(d[cols], d.y_reg3)
            out["p_reg3"] = g.predict_proba(cur[cols])[:, 1]
    pj = json.loads((OUT / "projection_qmin3.json").read_text(encoding="utf-8"))
    gates["phase6"] = pj.get("gate_phase6", {}).get("passed")
    if gates["phase6"]:
        p = projection.frame()
        pcols = projection.cols_of(p)
        for c in pcols:
            if c not in cur.columns:
                cur[c] = np.nan
        last2 = p.snapshot.max() - 1
        fit, cal = p[p.snapshot < last2], p[p.snapshot >= last2]
        models = {a: projection.Averaged(a).fit(fit[pcols], fit.qmin3) for a in (projection.LO, projection.MID, projection.HI)}
        score = np.maximum(models[projection.LO].predict(cal[pcols]) - cal.qmin3,
                           cal.qmin3 - models[projection.HI].predict(cal[pcols]))
        w = float(np.sort(score)[min(len(score) - 1, int(np.ceil((len(score) + 1) * 0.8)) - 1)])
        out["qmin3_p10"] = np.expm1(np.maximum(models[projection.LO].predict(cur[pcols]) - w, 0))
        out["qmin3_p50"] = np.expm1(np.maximum(models[projection.MID].predict(cur[pcols]), 0))
        out["qmin3_p90"] = np.expm1(models[projection.HI].predict(cur[pcols]) + w)
    for c in ("p_reg3", "qmin3_p10", "qmin3_p50", "qmin3_p90"):
        if c not in out:
            out[c] = np.nan          # its gate didn't pass: the desk shows no number, and says why
    OUT.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT / "current_outlook.parquet", index=False)
    info = {"snapshot": int(cur.snapshot.iloc[0]) if len(cur) else None, "players": int(len(out)), "gates": gates,
            "reg3_model": champion if gates.get("phase4") else ("2. penalised logistic" if demo else None),
            "calls_status": "demonstration" if demo else "earned",
            "calls_label": "behind market value, from match evidence alone" if demo else None}
    (OUT / "current_outlook.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    print(json.dumps(info, indent=1))


if __name__ == "__main__":
    main()
