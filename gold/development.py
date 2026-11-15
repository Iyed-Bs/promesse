"""ProT6 0.1: development by system. Which coaches and game models grow young players fastest?

Unit: a player under 21 at the start of July of season t, with league minutes in t at a club whose game model we measure (T1).
Outcome: how much quality football he plays the next season, log(1 + quality minutes in t+1), 0 if none.
  baseline   what he is already: quality minutes and minutes in t, his share of his club's league minutes, age, age
             squared, position, his club's level, his league
  + system   his club's game model in t (T1's eleven dimensions, league-relative)
  + coach    his coach in t (T2's spells), as shrunk effects: ridge on one indicator per coach, so a coach with two
             prospects claims almost nothing
Time order, as T5: trained on seasons t = 2021/22 and 2022/23 (outcomes in 2022/23 and 2023/24), tested once on
t = 2023/24 (outcomes in 2024/25); t = 2024/25 (outcomes in 2025/26) stays locked.
Gate (ProT6 0.1): on the test season, a layer's error is lower than the layer below it, 95 % bootstrap interval of the gain
(over players) above zero. Coaches, separately: does a coach's effect learned on the training seasons line up with
his young players' residuals in the test season (coaches with 5+ young players in both)?

    python gold/development.py      (Promesse venv) -> lake/gold/development.json, development_coaches.parquet
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge

GOLD = Path((DATA_ROOT + "/lake/gold"))
SCOUT = (DATA_ROOT + "/scout/scout.duckdb")
TRAIN, TEST, LOCKED = (2021, 2022), (2023,), (2024,)
rng = np.random.default_rng(7)


def season_str(y: int) -> str:
    return f"{y}-{y + 1}"


def load() -> tuple[pd.DataFrame, list[str]]:
    con = duckdb.connect(SCOUT, read_only=True)
    car = con.execute("""select tm_id, season, club_id, club, league, coalesce(league_min, 0) as league_min, coalesce("minutes", 0) as "minutes",
                                coalesce(qmin, 0) as qmin, share, "level" from career where season between 2020 and 2025""").df()
    people = con.execute("select tm_id, dob, position from people").df()
    nxt = car.groupby(["tm_id", "season"]).qmin.sum().rename("qmin_next").reset_index()
    nxt["season"] -= 1                                   # his next season's quality minutes, keyed on this season
    main = car[car.league_min > 0].sort_values("league_min").groupby(["tm_id", "season"]).tail(1)
    tot = car.groupby(["tm_id", "season"])[["qmin", "minutes"]].sum().add_suffix("_t").reset_index()
    d = main.merge(tot, on=["tm_id", "season"]).merge(people, on="tm_id")
    d["age"] = (pd.to_datetime(d.season.astype(str) + "-07-01") - pd.to_datetime(d.dob)).dt.days / 365.25
    d = d[(d.age < 21) & (d.age >= 15) & d.season.between(2021, 2024)].copy()
    d = d.merge(nxt, on=["tm_id", "season"], how="left")
    d["y"] = np.log1p(d.qmin_next.fillna(0))
    # his club's game model that season: Transfermarkt club -> MatchData team (match link), then T1's league-relative dims
    rep = json.loads((GOLD / "team_style_report.json").read_text(encoding="utf-8"))
    dims = rep["dimensions_passed"]
    link = pd.read_parquet(GOLD / "match_link.parquet", columns=["club_id", "team_id"]).dropna()
    link = link.groupby(["club_id", "team_id"]).size().rename("n").reset_index().sort_values("n").groupby("club_id").tail(1)
    style = pd.read_parquet(GOLD / "team_style.parquet")[["season", "team_id"] + [f"z_{c}" for c in dims]]
    style = style.groupby(["season", "team_id"]).mean().reset_index()   # a team in two competitions: its mean
    d = d.merge(link[["club_id", "team_id"]].astype({"club_id": "int64"}), on="club_id", how="left")
    d["season_s"] = d.season.map(season_str)
    d = d.merge(style.rename(columns={"season": "season_s"}), on=["season_s", "team_id"], how="inner")
    # his coach that season: the manager with the most matches at his club inside the season (T2's spells)
    sp = pd.read_parquet(GOLD / "coach_spells.parquet", columns=["manager", "club_id", "n", "first", "last"]).dropna(subset=["club_id"])
    sp["first"], sp["last"] = pd.to_datetime(sp["first"]), pd.to_datetime(sp["last"])
    rows = []
    for y in range(2021, 2025):
        a, b = pd.Timestamp(f"{y}-07-01"), pd.Timestamp(f"{y + 1}-06-30")
        s = sp[(sp["first"] <= b) & (sp["last"] >= a)].copy()
        span = (s["last"] - s["first"]).dt.days.clip(lower=1)
        s["w"] = s.n * ((s["last"].clip(upper=b) - s["first"].clip(lower=a)).dt.days.clip(lower=1) / span)
        s = s.sort_values("w").groupby("club_id").tail(1)
        rows.append(s.assign(season=y)[["club_id", "season", "manager"]])
    coach = pd.concat(rows).astype({"club_id": "int64"})
    d = d.merge(coach, on=["club_id", "season"], how="left")
    return d, dims


def base_X(d: pd.DataFrame, leagues: list, pos: list) -> np.ndarray:
    lvl = d["level"].astype(float)
    cols = [np.log1p(d.qmin_t), np.log1p(d.minutes_t), d.share.fillna(0), d.age, d.age ** 2,
            lvl.fillna(-300) / 100, lvl.isna().astype(float)]
    cols += [(d.position == p).astype(float) for p in pos] + [(d.league == lg).astype(float) for lg in leagues]
    return np.column_stack([np.asarray(c, dtype=float) for c in cols])


def main() -> None:
    d, dims = load()
    leagues = sorted(d.league.dropna().unique())
    pos = sorted(d.position.dropna().unique())
    z = [f"z_{c}" for c in dims]
    tr, te = d[d.season.isin(TRAIN)], d[d.season.isin(TEST)]
    Xb_tr, Xb_te = base_X(tr, leagues, pos), base_X(te, leagues, pos)
    Xs_tr, Xs_te = np.hstack([Xb_tr, tr[z].fillna(0).to_numpy()]), np.hstack([Xb_te, te[z].fillna(0).to_numpy()])
    coaches = sorted(tr.manager.dropna().unique())
    def C(df: pd.DataFrame) -> np.ndarray:
        return (df.manager.to_numpy()[:, None] == np.array(coaches)[None, :]).astype(float)

    m_base = Ridge(alpha=1.0).fit(Xb_tr, tr.y)
    m_sys = Ridge(alpha=1.0).fit(Xs_tr, tr.y)
    # coaches shrunk hard: their indicators get a much stronger penalty than the rest (scaled down = more shrinkage)
    k = 0.15
    m_coach = Ridge(alpha=1.0).fit(np.hstack([Xs_tr, C(tr) * k]), tr.y)
    err = {"baseline": (m_base.predict(Xb_te) - te.y) ** 2,
           "+ game model": (m_sys.predict(Xs_te) - te.y) ** 2,
           "+ coach": (m_coach.predict(np.hstack([Xs_te, C(te) * k])) - te.y) ** 2}
    err = {a: np.asarray(v) for a, v in err.items()}
    gains = {}
    for hi, lo in (("+ game model", "baseline"), ("+ coach", "+ game model")):
        diff = err[lo] - err[hi]
        boots = [diff[rng.integers(0, len(diff), len(diff))].mean() for _ in range(2000)]
        gains[f"{hi} over {lo}"] = {"mean": round(float(diff.mean()), 4),
                                    "ci95": [round(float(np.percentile(boots, 2.5)), 4), round(float(np.percentile(boots, 97.5)), 4)]}
    # which game models grow young players: the system coefficients, bootstrapped over training players
    coefs = []
    for _ in range(300):
        i = rng.integers(0, len(tr), len(tr))
        coefs.append(Ridge(alpha=1.0).fit(Xs_tr[i], tr.y.to_numpy()[i]).coef_[-len(z):])
    coefs = np.array(coefs)
    by_dim = {c: {"effect": round(float(np.median(coefs[:, j])), 3),
                  "ci95": [round(float(np.percentile(coefs[:, j], 2.5)), 3), round(float(np.percentile(coefs[:, j], 97.5)), 3)]}
              for j, c in enumerate(dims)}
    # coaches: does an effect learned on the training seasons line up with the test season's residuals?
    eff = pd.Series(m_coach.coef_[Xs_tr.shape[1]:] * k, index=coaches, name="effect")
    n_tr = tr.manager.value_counts().rename("young_train")
    res_te = (te.y - m_sys.predict(Xs_te)).groupby(te.manager.values).agg(["mean", "size"]).rename(columns={"mean": "resid_test", "size": "young_test"})
    cc = pd.concat([eff, n_tr, res_te], axis=1)
    both = cc[(cc.young_train >= 5) & (cc.young_test >= 5)].dropna()
    rho = float(spearmanr(both.effect, both.resid_test).statistic) if len(both) >= 10 else float("nan")
    cc.rename_axis("manager").reset_index().to_parquet(GOLD / "development_coaches.parquet", index=False)
    passed_sys = gains["+ game model over baseline"]["ci95"][0] > 0
    passed_coach = gains["+ coach over + game model"]["ci95"][0] > 0
    out = {"players": {"train": int(len(tr)), "test": int(len(te)), "locked": int(d.season.isin(LOCKED).sum())},
           "mse_test": {a: round(float(v.mean()), 4) for a, v in err.items()}, "gain": gains,
           "gate_t6": {"game model": passed_sys, "coach": passed_coach,
                       "rule": "a layer's error on the test season is lower than the layer below it, 95 % interval above zero"},
           "coach_stability": {"coaches": int(len(both)), "spearman_effect_vs_test_residual": round(rho, 3)},
           "game_model_effects": by_dim}
    (GOLD / "development.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("players", "mse_test", "gain", "gate_t6", "coach_stability")}, indent=1))
    print("game-model effects on next season's log quality minutes (clear ones):",
          {c: v for c, v in by_dim.items() if v["ci95"][0] > 0 or v["ci95"][1] < 0})
    top = cc[cc.young_train >= 8].sort_values("effect", ascending=False)
    print("coaches, most growth credited (8+ young players in training):", top.head(8).effect.round(3).to_dict())


if __name__ == "__main__":
    main()
