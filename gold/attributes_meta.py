"""Promesse: the attributes' discrimination (Franks, D'Amour, Cervone and Bornn 2016, "Meta-Analytics"; RESEARCH.md).

Stability (the split-half gate in gold/attributes.py) asks whether an attribute repeats. Discrimination asks how much
of the spread between players is the players, and how much is which matches they happened to play:
    D = 1 - (mean over players of the sampling variance of his reading) / (variance of the reading across players)
The sampling variance comes from bootstrapping each player's matches (his season resampled with replacement, the
attribute recomputed against the same full-season system prediction). Player-seasons of 1,800+ league minutes, as the
gate; within each family, then averaged weighted by players.
Rule, written before the run: an attribute stays shown only if D >= 0.5, more than half of the spread
being the players. The result is written into attributes_report.json beside the split-half number.

    python gold/attributes_meta.py      (Promesse venv) -> adds "discrimination" to lake/gold/attributes_report.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

sys.path.insert(0, str(Path(__file__).resolve().parent))
import attributes as A  # noqa: E402
import signature  # noqa: E402

B, SAMPLE, D_MIN = 60, 2500, 0.5
rng = np.random.default_rng(7)


def main() -> None:
    con = duckdb.connect()
    d = A.load(con)
    rep = json.loads((A.GOLD / "team_style_report.json").read_text(encoding="utf-8"))
    dims = rep["dimensions_passed"]
    style = pd.read_parquet(A.GOLD / "team_style.parquet")[["league_id", "season", "team_id"] + [f"z_{c}" for c in dims]]
    fam = pd.read_parquet(A.GOLD / "player_roles.parquet")[A.KEY + ["family", "name", "tm_id", "team"]]
    fam["league_id"] = fam.league_id.astype("int64")
    full = A.summed(d).merge(fam, on=A.KEY).merge(style, on=["league_id", "season", "team_id"], how="left")
    full = full[(full.minutes >= A.MIN_SEASON) & (full.family != "GK")].reset_index(drop=True)
    leagues = sorted(full.league_id.unique())
    big = full[full.minutes >= A.MIN_SPLIT]
    big = big.sample(min(SAMPLE, len(big)), random_state=7)
    d["league_id"] = d.league_id.astype("int64")
    counts = list(set(list(signature.roles.COUNTS.values()) + list(A.EXTRA.values()))) + ["minutes"]
    matches = {k: g[counts] for k, g in d.groupby(A.KEY) if k in set(map(tuple, big[A.KEY].to_numpy()))}

    report = {}
    for key, (label, _, inds) in A.ATTRS.items():
        covs = A.COVARIATES.get(key, [])

        def X_of(df: pd.DataFrame) -> np.ndarray:
            base = signature.design(df, dims, leagues)
            return base if not covs else np.hstack([base, np.column_stack([fn(df).fillna(0).to_numpy() for fn in covs])])
        # the full-season system prediction and spread per family and indicator, as gold/attributes.py fits them
        fitted = {}
        for f, part in full.groupby("family"):
            for j, fn in enumerate(inds):
                x = fn(part)
                ok = x.notna() & np.isfinite(x)
                if ok.sum() < 80:
                    continue
                m = Ridge(alpha=5.0).fit(X_of(part[ok]), x[ok])
                fitted[(f, j)] = (m, float(np.nanstd(x[ok] - m.predict(X_of(part[ok])))) or 1.0)
        per_fam = {}
        for f, part in big.groupby("family"):
            if not all((f, j) in fitted for j in range(len(inds))):
                continue
            preds = [fitted[(f, j)][0].predict(X_of(part)) for j in range(len(inds))]
            sds = [fitted[(f, j)][1] for j in range(len(inds))]
            reading, svar = [], []
            for i, (_, row) in enumerate(part.iterrows()):
                g = matches.get(tuple(row[A.KEY]))
                if g is None or len(g) < 8:
                    continue
                arr = g.to_numpy(dtype=float)
                def value(sums: np.ndarray) -> float:
                    s = pd.DataFrame([sums], columns=counts)
                    zs = [(float(fn(s).iloc[0]) - preds[j][i]) / sds[j] for j, fn in enumerate(inds)]
                    zs = [z for z in zs if np.isfinite(z)]
                    return float(np.mean(zs)) if zs else np.nan
                full_val = value(arr.sum(axis=0))
                boots = [value(arr[rng.integers(0, len(arr), len(arr))].sum(axis=0)) for _ in range(B)]
                boots = [b for b in boots if np.isfinite(b)]
                if np.isfinite(full_val) and len(boots) > B // 2:
                    reading.append(full_val)
                    svar.append(np.var(boots, ddof=1))
            if len(reading) >= 40:
                per_fam[f] = (len(reading), 1 - float(np.mean(svar)) / float(np.var(reading, ddof=1)))
        n = sum(v[0] for v in per_fam.values())
        D = sum(v[0] * v[1] for v in per_fam.values()) / n if n else float("nan")
        report[key] = {"label": label, "discrimination": round(D, 3), "players": int(n),
                       "by_family": {f: round(v[1], 3) for f, v in per_fam.items()}, "kept": bool(D >= D_MIN)}
        print(f"  {label:14s} D = {D:.3f} over {n} player-seasons  {report[key]['by_family']}")

    p = A.GOLD / "attributes_report.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    for key, r in report.items():
        doc["by_attribute"][key]["discrimination"] = r["discrimination"]
        if doc["by_attribute"][key]["passed"] and not r["kept"]:
            doc["by_attribute"][key]["passed"] = False
            doc["by_attribute"][key]["hidden_by"] = f"discrimination {r['discrimination']} < {D_MIN}"
    doc["discrimination_rule"] = (f"Franks et al. 2016: share of the spread between players that is the players (bootstrap of "
                                  f"each player's matches, {B} draws, player-seasons of 1,800+ minutes); shown only if >= {D_MIN}")
    doc["shown"] = [r["label"] for r in doc["by_attribute"].values() if r["passed"]]
    doc["hidden"] = [r["label"] for r in doc["by_attribute"].values() if not r["passed"]]
    p.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    print("shown:", doc["shown"], "| hidden:", doc["hidden"])


if __name__ == "__main__":
    main()
