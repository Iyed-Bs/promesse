"""Promesse T5: system fit. If he moves to a team that plays like this, what will he do there?

The natural experiment: every player with 900+ league minutes for one team in a season and 900+ for another the next
season (MatchData's detailed stats, 2021/22 on). For each skill (T4's rates, standardised within family and season), a
ridge model learns
    profile(next) = a * profile(now) + b . (game model(new) - game model(old)) + family
and two baselines answer the same question: "the same as before", and "what his family does at the new team"
(the new team's other players in his family that season).

Time order: trained on moves into 2022/23 and 2023/24, tested once on moves into 2024/25; moves into 2025/26 stay
locked. Gate (T5): on the test moves, the model's error (mean over skills) is lower than both baselines', the 95 %
interval of the gain (bootstrap over players) above zero.

    python gold/system_fit.py      (Promesse venv) -> lake/gold/system_fit.json, system_fit_moves.parquet
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import joblib
from sklearn.linear_model import Ridge

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roles  # noqa: E402
import signature  # noqa: E402

GOLD = Path((DATA_ROOT + "/lake/gold"))
MIN = 900
TRAIN_INTO, TEST_INTO = ("2022-2023", "2023-2024"), ("2024-2025",)
rng = np.random.default_rng(7)


def next_season(s: str) -> str | None:
    if len(s) == 9 and s[4] == "-":
        a = int(s[:4]) + 1
        return f"{a}-{a + 1}"
    return None


def main() -> None:
    rep = json.loads((GOLD / "team_style_report.json").read_text(encoding="utf-8"))
    dims = rep["dimensions_passed"]
    skills = [s for s, r in json.loads((GOLD / "skills_report.json").read_text(encoding="utf-8"))["by_skill"].items() if r.get("passed")]
    style = pd.read_parquet(GOLD / "team_style.parquet")[["league_id", "season", "team_id"] + [f"z_{c}" for c in dims]]
    fam = pd.read_parquet(GOLD / "player_roles.parquet")[signature.KEY + ["family", "name", "tm_id", "team"]]
    fam["league_id"] = fam.league_id.astype("int64")
    d = roles.rows(duckdb.connect())
    r = signature.season_rates(d).reset_index()
    r["league_id"] = r.league_id.astype("int64")
    # league rows only: a team's game model is measured on its league matches
    r = r.merge(fam, on=signature.KEY).merge(style, on=["league_id", "season", "team_id"], how="inner")
    r = r[r.minutes >= MIN].copy()
    for s in skills:                                    # each skill standardised within its family and season
        g = r.groupby(["family", "season"])[s]
        r[s] = (r[s] - g.transform("mean")) / g.transform("std")
    # one row per player-season: his main league team (most minutes)
    r = r.sort_values("minutes").groupby(["fid", "season"]).tail(1)
    r.to_parquet(GOLD / "player_profiles.parquet", index=False)     # the standardised profiles, for the club views
    r["next"] = r.season.map(next_season)
    a = r.rename(columns={c: f"{c}_a" for c in r.columns if c not in ("fid", "next")})
    b = r.rename(columns={c: f"{c}_b" for c in r.columns if c != "fid"})
    mv = a.merge(b, left_on=["fid", "next"], right_on=["fid", "season_b"])
    mv = mv[mv.team_id_a != mv.team_id_b].copy()
    # baseline 2: what his family does at the new team that season (the other players, leave-one-out)
    fam_team = r.groupby(["team_id", "season", "family"])[skills].agg(["sum", "count"])
    for s in skills:
        key = list(zip(mv.team_id_b, mv.season_b, mv.family_b))
        tot = fam_team[(s, "sum")].reindex(key).to_numpy()
        cnt = fam_team[(s, "count")].reindex(key).to_numpy()
        mv[f"teammean_{s}"] = np.where(cnt > 1, (tot - mv[f"{s}_b"].to_numpy()) / np.maximum(cnt - 1, 1), 0.0)
    for c in dims:
        mv[f"diff_{c}"] = mv[f"z_{c}_b"].fillna(0) - mv[f"z_{c}_a"].fillna(0)
    fams = sorted(mv.family_a.unique())
    train, test = mv[mv.season_b.isin(TRAIN_INTO)], mv[mv.season_b.isin(TEST_INTO)]

    def X(df: pd.DataFrame, s: str) -> np.ndarray:
        cols = [df[f"{s}_a"].fillna(0).to_numpy()[:, None], df[[f"diff_{c}" for c in dims]].to_numpy(),
                (df.family_a.to_numpy()[:, None] == np.array(fams)[None, :]).astype(float),
                df[f"{s}_a"].fillna(0).to_numpy()[:, None] * df[[f"diff_{c}" for c in dims]].to_numpy()]
        return np.hstack(cols)

    err = {"model": [], "same as before": [], "his family at the new team": [], "regression to the mean": []}
    coefs, models = {}, {}
    for s in skills:
        tr = train[train[f"{s}_b"].notna()]
        m = Ridge(alpha=10.0).fit(X(tr, s), tr[f"{s}_b"])
        models[s] = Ridge(alpha=10.0).fit(X(mv[mv[f"{s}_b"].notna() & (mv.season_b != "2025-2026")], s),
                                          mv.loc[mv[f"{s}_b"].notna() & (mv.season_b != "2025-2026"), f"{s}_b"])
        # the honest baseline: the same model without the systems (carry-over and family only)
        k = 1 + len(fams)
        base = Ridge(alpha=10.0).fit(np.hstack([X(tr, s)[:, :1], X(tr, s)[:, 1 + len(dims):1 + len(dims) + len(fams)]]), tr[f"{s}_b"])
        xt = X(test, s)
        err["regression to the mean"].append((base.predict(np.hstack([xt[:, :1], xt[:, 1 + len(dims):1 + len(dims) + len(fams)]]))
                                              - test[f"{s}_b"].to_numpy()) ** 2)
        del k
        coefs[s] = {"carry_over": round(float(m.coef_[0]), 3),
                    "style_effects": {c: round(float(v), 3) for c, v in zip(dims, m.coef_[1:1 + len(dims)])}}
        y = test[f"{s}_b"].to_numpy()                      # aligned to every test move; a missing skill stays NaN
        err["model"].append((m.predict(X(test, s)) - y) ** 2)
        err["same as before"].append((test[f"{s}_a"].fillna(0).to_numpy() - y) ** 2)
        err["his family at the new team"].append((test[f"teammean_{s}"].to_numpy() - y) ** 2)
    per_player = {k: np.nanmean(np.vstack(v), axis=0) for k, v in err.items()}    # mean over skills, per test move
    keep = ~np.isnan(per_player["model"])
    per_player = {k: v[keep] for k, v in per_player.items()}
    mse = {k: round(float(v.mean()), 4) for k, v in per_player.items()}
    gains = {}
    for base in ("same as before", "his family at the new team", "regression to the mean"):
        diff = per_player[base] - per_player["model"]
        boots = [diff[rng.integers(0, len(diff), len(diff))].mean() for _ in range(2000)]
        gains[base] = {"mean": round(float(diff.mean()), 4), "ci95": [round(float(np.percentile(boots, 2.5)), 4),
                                                                      round(float(np.percentile(boots, 97.5)), 4)]}
    passed = all(gains[b]["ci95"][0] > 0 for b in ("same as before", "his family at the new team"))
    systems_matter = gains["regression to the mean"]["ci95"][0] > 0      # do the game models add beyond shrinkage?
    out = {"moves": {"train": int(len(train)), "test": int(len(test)), "locked_into_2025_26": int((mv.season_b == "2025-2026").sum())},
           "skills": skills, "mse_test": mse, "gain_over": gains,
           "gate_t5": {"rule": "the model's error on unseen moves (into 2024/25) beats both baselines, 95 % interval of the gain above zero",
                       "passed": passed},
           "systems_add_beyond_shrinkage": {"rule": "the model beats the same model without the game models (regression to "
                                                     "the mean), 95 % interval above zero", "passed": systems_matter},
           "what_carries": coefs}
    (GOLD / "system_fit.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    # for use (not for judging): refitted on every move except the locked ones, with the design that built them
    joblib.dump({"models": models, "dims": dims, "fams": fams, "skills": skills}, GOLD / "system_fit_models.pkl")
    mv[["fid", "name_a", "team_id_a", "team_id_b", "season_a", "season_b", "family_a"]].to_parquet(GOLD / "system_fit_moves.parquet", index=False)
    print(json.dumps({k: out[k] for k in ("moves", "mse_test", "gain_over", "gate_t5")}, indent=1))
    print("carry-over (how much of each skill travels with the player):",
          {s: c["carry_over"] for s, c in coefs.items()})


if __name__ == "__main__":
    main()
