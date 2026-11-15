"""ProT6: development by system, on more seasons and with players who stay.

    python models/t6v2.py t1               -> lake/models/t6v2_t1.json
    python models/t6v2.py t2 <v2a|v2b|v2c> -> lake/models/t6v2_t2.json    (once)
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
from sklearn.linear_model import Ridge

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "gold"))
from development import base_X  # noqa: E402  (v1's baseline design matrix)

DATA = Path(DATA_ROOT)
G2 = DATA / "lake" / "gold_t6v2"
OUT = DATA / "lake" / "models"
SCOUT = (DATA / "scout" / "scout.duckdb").as_posix()
rng = np.random.default_rng(7)
K_COACH = 0.15
ALPHA_DELTA = 10.0


def load():
    con = duckdb.connect(SCOUT, read_only=True)
    car = con.execute("""select tm_id, season, club_id, club, league, coalesce(league_min, 0) league_min, coalesce("minutes", 0) "minutes",
                         coalesce(qmin, 0) qmin, share, "level" from career where season between 2016 and 2025""").df()
    people = con.execute("select tm_id, dob, position from people").df()
    nxt = car.groupby(["tm_id", "season"]).qmin.sum().rename("qmin_next").reset_index()
    nxt["season"] -= 1
    main = car[car.league_min > 0].sort_values("league_min").groupby(["tm_id", "season"]).tail(1)
    tot = car.groupby(["tm_id", "season"])[["qmin", "minutes"]].sum().add_suffix("_t").reset_index()
    d = main.merge(tot, on=["tm_id", "season"]).merge(people, on="tm_id")
    d["age"] = (pd.to_datetime(d.season.astype(str) + "-07-01") - pd.to_datetime(d.dob)).dt.days / 365.25
    d = d[(d.age < 21) & (d.age >= 15) & d.season.between(2017, 2024)].copy()
    d = d.merge(nxt, on=["tm_id", "season"], how="left")
    d["y"] = np.log1p(d.qmin_next.fillna(0))
    rep = json.loads((G2 / "team_style_report.json").read_text())
    dims = rep["dimensions_passed"]
    carried = json.loads((G2 / "coach_style_report.json").read_text())["dimensions_coaches_carry"]
    link = pd.read_parquet(G2 / "match_link.parquet", columns=["club_id", "team_id"]).dropna()
    link = link.groupby(["club_id", "team_id"]).size().rename("n").reset_index().sort_values("n").groupby("club_id").tail(1)
    style = pd.read_parquet(G2 / "team_style.parquet")[["season", "team_id"] + [f"z_{c}" for c in dims]]
    style = style.groupby(["season", "team_id"]).mean().reset_index()
    style["season"] = style.season.str[:4].astype(int)
    d = d.merge(link[["club_id", "team_id"]].astype({"club_id": "int64"}), on="club_id", how="left")
    d = d.merge(style, on=["season", "team_id"], how="left")             # NaN dims: the club's model is not measured that season
    sp = pd.read_parquet(G2 / "coach_spells.parquet").dropna(subset=["club_id"])
    sp["first"], sp["last"] = pd.to_datetime(sp["first"]), pd.to_datetime(sp["last"])
    rows = []
    for y in range(2016, 2025):
        a, b = pd.Timestamp(f"{y}-07-01"), pd.Timestamp(f"{y + 1}-06-30")
        s = sp[(sp["first"] <= b) & (sp["last"] >= a)].copy()
        span = (s["last"] - s["first"]).dt.days.clip(lower=1)
        s["w"] = s.n * ((s["last"].clip(upper=b) - s["first"].clip(lower=a)).dt.days.clip(lower=1) / span)
        s = s.sort_values("w").groupby("club_id").tail(1)
        s = s.assign(season=y).rename(columns={c: f"fp_{c}" for c in carried})
        rows.append(s[["club_id", "season", "manager"] + [f"fp_{c}" for c in carried]])
    coach = pd.concat(rows).astype({"club_id": "int64"})
    d = d.merge(coach, on=["club_id", "season"], how="left")
    return d, dims, carried


def boot_gain(err_lo: np.ndarray, err_hi: np.ndarray, level: float, n: int = 2000) -> dict:
    """Gain = mean(err_lo - err_hi) (lower error is better for err_hi); interval at `level` (e.g. 0.9875 for Bonferroni of 4)."""
    diff = err_lo - err_hi
    idx = rng.integers(0, len(diff), (n, len(diff)))
    means = diff[idx].mean(axis=1)
    a = (1 - level) / 2 * 100
    return {"mean": round(float(diff.mean()), 4), "ci": [round(float(np.percentile(means, a)), 4), round(float(np.percentile(means, 100 - a)), 4)],
            "level": level, "relative": round(float(diff.mean() / err_lo.mean()), 4), "n": int(len(diff))}


def v2a(d, dims, tr_seasons, te_season, level):
    tr, te = d[d.season.isin(tr_seasons) & d[f"z_{dims[0]}"].notna()], d[(d.season == te_season) & d[f"z_{dims[0]}"].notna()]
    leagues, pos = sorted(tr.league.dropna().unique()), sorted(tr.position.dropna().unique())
    z = [f"z_{c}" for c in dims]
    Xb_tr, Xb_te = base_X(tr, leagues, pos), base_X(te, leagues, pos)
    Xs_tr, Xs_te = np.hstack([Xb_tr, tr[z].fillna(0).to_numpy()]), np.hstack([Xb_te, te[z].fillna(0).to_numpy()])
    coaches = sorted(tr.manager.dropna().unique())
    C = lambda df: (df.manager.to_numpy()[:, None] == np.array(coaches)[None, :]).astype(float)  # noqa: E731
    mb, ms = Ridge(alpha=1.0).fit(Xb_tr, tr.y), Ridge(alpha=1.0).fit(Xs_tr, tr.y)
    mc = Ridge(alpha=1.0).fit(np.hstack([Xs_tr, C(tr) * K_COACH]), tr.y)
    eb, es = (mb.predict(Xb_te) - te.y).to_numpy() ** 2, (ms.predict(Xs_te) - te.y).to_numpy() ** 2
    ec = (mc.predict(np.hstack([Xs_te, C(te) * K_COACH])) - te.y).to_numpy() ** 2
    return {"n_train": int(len(tr)), "n_test": int(len(te)), "mse": {"baseline": round(float(eb.mean()), 4), "+ game model": round(float(es.mean()), 4),
            "+ coach": round(float(ec.mean()), 4)},
            "gain_game_model": boot_gain(eb, es, level), "gain_coach": boot_gain(es, ec, level)}


def stayers(d, tr_seasons, te_season, dims, carried, version, level):
    """Pairs (t-1, t) at the same club; outcome = the change in the residual from a baseline fitted on the training rows."""
    tr_rows = d[d.season.isin(tr_seasons)]
    leagues, pos = sorted(tr_rows.league.dropna().unique()), sorted(tr_rows.position.dropna().unique())
    mb = Ridge(alpha=1.0).fit(base_X(tr_rows, leagues, pos), tr_rows.y)
    d = d.copy()
    d["resid"] = d.y - mb.predict(base_X(d, leagues, pos))
    z, fp = [f"z_{c}" for c in dims], [f"fp_{c}" for c in carried]
    a = d.rename(columns={c: c + "_p" for c in ["resid", "manager"] + z + fp})[["tm_id", "season", "club_id", "resid_p", "manager_p"] + [c + "_p" for c in z + fp]]
    a["season"] += 1
    p = d.merge(a, on=["tm_id", "season", "club_id"])                    # same club, one season earlier
    p["dr"] = p.resid - p.resid_p
    if version == "v2b":
        p = p.dropna(subset=[c for c in z] + [c + "_p" for c in z])
        X = np.column_stack([p[c] - p[c + "_p"] for c in z])
    else:
        p = p[(p.manager.notna()) & (p.manager_p.notna()) & (p.manager != p.manager_p)]
        p = p.dropna(subset=fp + [c + "_p" for c in fp])
        X = np.column_stack([p[c] - p[c + "_p"] for c in fp])
    tr = (p.season.isin(tr_seasons)).to_numpy()
    te = (p.season == te_season).to_numpy()
    if tr.sum() < 30 or te.sum() < 30:
        return {"n_train": int(tr.sum()), "n_test": int(te.sum()), "note": "too few pairs"}
    m = Ridge(alpha=ALPHA_DELTA).fit(X[tr], p.dr.to_numpy()[tr])
    e0 = p.dr.to_numpy()[te] ** 2                                   # as registered: predicting zero change
    mean_tr = float(p.dr.to_numpy()[tr].mean())
    em = (p.dr.to_numpy()[te] - mean_tr) ** 2                       # the fair comparator: the training years' mean change
    e1 = (p.dr.to_numpy()[te] - m.predict(X[te])) ** 2
    return {"n_train": int(tr.sum()), "n_test": int(te.sum()), "train_mean_change": round(mean_tr, 3),
            "mse": {"zero change": round(float(e0.mean()), 4), "train-mean change": round(float(em.mean()), 4),
                    "with change in system": round(float(e1.mean()), 4)},
            "gain_vs_zero_as_registered": boot_gain(e0, e1, level), "gain_vs_train_mean": boot_gain(em, e1, level),
            "coef": {c: round(float(v), 3) for c, v in zip(z if version == "v2b" else fp, m.coef_)}}


def main() -> None:
    stage = sys.argv[1]
    d, dims, carried = load()
    if stage == "t1":
        lvl = 0.9875
        res = {"v2a": v2a(d, dims, (2018, 2019), 2020, lvl), "v2b": stayers(d, (2018, 2019), 2020, dims, carried, "v2b", lvl),
               "v2c": stayers(d, (2018, 2019), 2020, dims, carried, "v2c", lvl)}
        (OUT / "t6v2_t1.json").write_text(json.dumps(res, indent=1))
    else:
        v, lvl = sys.argv[2], 0.95
        tr = (2018, 2019, 2020, 2021, 2022)
        res = v2a(d, dims, tr, 2023, lvl) if v == "v2a" else stayers(d, tr, 2023, dims, carried, v, lvl)
        res["version"] = v
        (OUT / "t6v2_t2.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
