"""Promesse: score the latest snapshot with ProEngine (adopt it in the build and the desk).

ProEngine = the ProEngine 0.1 inputs + MatchData per-90 stats read against the player's league-season. T1 chose it
on the final data (gradient boosting, settings in lake/models/engine_v2_t1.json); T2 (2021-22, once): AUC 0.7794 against
v1 0.7437 and market value 0.7753, level with the market, the Phase 4 gate still not passed.

Written to side files so the v1 files stay as history; the desk reads these (scout/precompute.py, scout/api.py why()).
Contributions are exact TreeSHAP in log-odds (lightgbm pred_contrib), the same long-table shape as models/explain.py.

    python models/score_v2c.py      (Promesse venv)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import engine_v2     # noqa: E402  (the same inputs and silencing the T1/T2 runs used)
import explain       # noqa: E402
import ladder        # noqa: E402
import score_current  # noqa: E402  (prepare(): the same feature preparation as the v1 desk scoring)

OUT = ladder.OUT
GOLD = ladder.GOLD


def main() -> None:
    cfg = json.loads((OUT / "engine_v2_t1.json").read_text(encoding="utf-8"))["versions"]["v2c"]["cfg"]
    d = engine_v2.build()                                   # labelled snapshots with the fm2 inputs
    d = d[d.y_reg3.notna()]
    cols = engine_v2.cols_of(d, "v2c")

    cur = pd.read_parquet(GOLD / "spine_current.parquet")
    extra = GOLD / "spine_extra.parquet"
    if extra.exists():
        cur = cur.merge(pd.read_parquet(extra), on=["player_id", "snapshot"], how="left")
    cur = score_current.prepare(cur)
    cur = cur[cur.age < 21].copy()
    fm = pd.read_parquet(OUT / "fm_feats.parquet")
    cur = cur.merge(fm, on=["player_id", "snapshot"], how="left").replace([np.inf, -np.inf], np.nan)
    cur["fm2_min_365"] = np.log1p(cur.fm2_min_365.clip(lower=0))
    for c in cols:
        if c not in cur.columns:
            cur[c] = np.nan
    d, cur = engine_v2.silence_fm(d, cur, cols)             # absence silenced: median of the fitting years, no flag
    cur = cur.reset_index(drop=True)

    g = ladder.gbm(cols, cfg["leaves"], cfg["rounds"]).fit(d[cols], d.y_reg3.to_numpy())
    out = cur[["player_id", "snapshot", "age"]].copy()
    out["p_reg3"] = g.predict_proba(cur[cols])[:, 1]

    # exact TreeSHAP in log-odds: the last column is the base value, the rest one term per input
    sh = g.booster_.predict(cur[cols], pred_contrib=True)
    base = float(sh[0, -1])
    raw = cur[cols].astype(float)
    long = pd.concat([pd.DataFrame({"player_id": cur.player_id.to_numpy(), "input": c, "contribution": sh[:, j],
                                    "value": raw[c].to_numpy(), "missing": raw[c].isna().to_numpy()})
                      for j, c in enumerate(cols)], ignore_index=True)
    long["group"] = long.input.map(lambda c: explain.INPUTS.get(c, ("Other", c))[0])
    long["label"] = long.input.map(lambda c: explain.INPUTS.get(c, ("Other", c))[1])
    long.to_parquet(OUT / "current_contributions_v2c.parquet", index=False)

    # The club-variable swap (scout/api.py why()): a tree has no coefficient to swap, so the swap is re-scored here. For
    # each input a club knows better, the player's log-odds at a grid of values across the slider's range, everything
    # else held. The page reads between grid points. (x is in the slider's unit; the tree reads youth minutes as log1p.)
    cv = json.loads((HERE / "club_variables.json").read_text(encoding="utf-8"))
    rows = []
    for e in cv["engine_inputs"]:
        k = e["input"]
        xs = np.linspace(e["min"], e["max"], 15)
        for x in xs:
            alt = cur[cols].copy()
            alt[k] = np.log1p(x) if k == "fm_youth_min_365" else x
            lg = g.booster_.predict(alt, raw_score=True)
            rows.append(pd.DataFrame({"player_id": cur.player_id.to_numpy(), "input": k, "x": float(x), "logit": lg}))
    pd.concat(rows, ignore_index=True).to_parquet(OUT / "current_swap_v2c.parquet", index=False)
    out.to_parquet(OUT / "current_outlook_v2c.parquet", index=False)

    v1 = pd.read_parquet(OUT / "current_outlook.parquet")[["player_id", "p_reg3"]].rename(columns={"p_reg3": "p_v1"})
    m = out.merge(v1, on="player_id")
    info = {"players": int(len(out)), "base_logit": base, "n_inputs": len(cols), "cfg": cfg,
            "corr_with_v1": float(m.p_reg3.corr(m.p_v1)), "mean_p_v2c": float(out.p_reg3.mean()), "mean_p_v1": float(m.p_v1.mean()),
            "engine": "v2c", "intercept": base,
            # the desk words the calls from this: level with market value on 2021-22, gate not passed
            "calls_status": "level", "calls_label": "level with market value from public records alone, not ahead"}
    (OUT / "current_outlook_v2c.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    print(json.dumps(info, indent=1))


if __name__ == "__main__":
    main()
