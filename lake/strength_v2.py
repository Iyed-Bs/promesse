"""Promesse Phase 2: strength v2, judged against the current Elo on the same matches and the same split.

The gate: a held-out Brier better than the maintenance loop's Elo, and youth and reserve sides
placed sensibly. Same data (lake/strength/elo_matches, every result the lake holds), same target (home win 1, draw
0.5, loss 0), same split: settings chosen on 2023/24, judged once on 2024/25 onwards. Every prediction uses only
matches played before it.

The ladder, simplest first:
  0. elo        the loop's Elo as it stands (its own pre-match expectation, read from the table)
  1. elo+       the same Elo with three changes: home advantage learned per competition from the seasons before
                2023/24 (youth tournaments and neutral venues get almost none), faster updates for teams with few
                matches, and each summer a pull of every rating back toward its league's starting level
  2. goals      an online goals model: each team an attack and a defence, home goals ~ Poisson(exp(mu + home_l +
                att_home - def_away)), updated after every match by one gradient step; the win, draw and loss
                chances come from the two Poisson laws
  3. blend      the average of 1 and 2

    python strength_v2.py      (Patcher venv) -> lake/strength/v2_ladder.json, team_ratings_v2.parquet, a printout
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

LAKE = Path((DATA_ROOT + "/lake"))
VAL = ("2023-07-01", "2024-07-01")
TEST_FROM = "2024-07-01"
PRIOR_FALLBACK = 1200.0


def load() -> pd.DataFrame:
    df = pd.read_parquet(LAKE / "strength" / "elo_matches.parquet")
    df = df.sort_values(["date", "match_id"]).reset_index(drop=True)
    df["season"] = pd.to_datetime(df["date"]).map(lambda d: d.year if d.month >= 7 else d.year - 1)
    return df


def brier(p: pd.Series, y: pd.Series) -> float:
    return float(((p - y) ** 2).mean())


def starting_levels(df: pd.DataFrame) -> dict:
    """Each team starts where the loop's Elo started it: the prior of its usual league (read back from the first
    pre-match rating the loop gave it)."""
    first_h = df.drop_duplicates("home_id")[["home_id", "elo_home_before"]].set_axis(["team", "r"], axis=1)
    first_a = df.drop_duplicates("away_id")[["away_id", "elo_away_before"]].set_axis(["team", "r"], axis=1)
    both = pd.concat([first_h, first_a]).drop_duplicates("team")
    return dict(zip(both.team, both.r))


def home_by_league(df: pd.DataFrame, before: str, base: float) -> dict:
    """Home advantage per competition in Elo points, from the seasons before `before`, shrunk toward `base`."""
    past = df[df.date < before]
    out = {}
    for lid, g in past.groupby("league_id"):
        m = float(g.res.mean())
        m = min(max(m, 0.35), 0.75)
        pts = 400 * math.log10(m / (1 - m))
        w = len(g) / (len(g) + 300)
        out[lid] = w * pts + (1 - w) * base
    return out


def elo_plus(df: pd.DataFrame, K: float, base_home: float, shrink: float, fresh: float, start: dict) -> pd.Series:
    home_l = home_by_league(df, VAL[0], base_home)
    rating: dict[str, float] = {}
    games: dict[str, int] = {}
    season_now = None
    exp = np.empty(len(df))
    for i, r in enumerate(df.itertuples()):
        if r.season != season_now:                       # the summer pull toward each team's starting level
            if season_now is not None:
                for t in rating:
                    s0 = start.get(t, PRIOR_FALLBACK)
                    rating[t] = s0 + (rating[t] - s0) * (1 - shrink)
            season_now = r.season
        rh = rating.get(r.home_id, start.get(r.home_id, PRIOR_FALLBACK))
        ra = rating.get(r.away_id, start.get(r.away_id, PRIOR_FALLBACK))
        h = home_l.get(r.league_id, base_home)
        e = 1 / (1 + 10 ** ((ra - rh - h) / 400))
        exp[i] = e
        margin = (abs(r.hg - r.ag) + 1) ** 0.5
        kh = K * (1 + fresh / (1 + games.get(r.home_id, 0) / 10))
        ka = K * (1 + fresh / (1 + games.get(r.away_id, 0) / 10))
        rating[r.home_id] = rh + kh * margin * (r.res - e)
        rating[r.away_id] = ra - ka * margin * (r.res - e)
        games[r.home_id] = games.get(r.home_id, 0) + 1
        games[r.away_id] = games.get(r.away_id, 0) + 1
    return pd.Series(exp, index=df.index)


def poisson_outcome(lh: float, la: float, cap: int = 10) -> float:
    """P(home win) + 0.5 P(draw) under two independent Poisson laws."""
    ph = [math.exp(-lh) * lh ** k / math.factorial(k) for k in range(cap + 1)]
    pa = [math.exp(-la) * la ** k / math.factorial(k) for k in range(cap + 1)]
    win = sum(ph[i] * sum(pa[:i]) for i in range(cap + 1))
    draw = sum(ph[i] * pa[i] for i in range(cap + 1))
    return win + 0.5 * draw


def goals_model(df: pd.DataFrame, lr: float, start: dict, scale: float, keep: bool = False):
    """Online attack/defence ratings; teams start from their league's level (the Elo prior, turned into goals)."""
    mu = math.log(max(float(df[df.date < VAL[0]][["hg", "ag"]].values.mean()), 0.5))
    home = {}
    past = df[df.date < VAL[0]]
    for lid, g in past.groupby("league_id"):           # home goal edge per competition, shrunk toward the overall
        hg, ag = g.hg.mean() + 0.1, g.ag.mean() + 0.1
        w = len(g) / (len(g) + 300)
        home[lid] = w * math.log(hg / ag) / 2 + (1 - w) * 0.12
    att: dict[str, float] = {}
    dfn: dict[str, float] = {}
    exp = np.empty(len(df))
    for i, r in enumerate(df.itertuples()):
        s_h = (start.get(r.home_id, PRIOR_FALLBACK) - 1400) / scale
        s_a = (start.get(r.away_id, PRIOR_FALLBACK) - 1400) / scale
        ah, dh = att.get(r.home_id, s_h / 2), dfn.get(r.home_id, s_h / 2)
        aa, da = att.get(r.away_id, s_a / 2), dfn.get(r.away_id, s_a / 2)
        hl = home.get(r.league_id, 0.12)
        lh = math.exp(mu + hl + ah - da)
        la = math.exp(mu - hl + aa - dh)
        exp[i] = poisson_outcome(min(lh, 8), min(la, 8))
        gh, ga = min(r.hg, 10) - lh, min(r.ag, 10) - la    # gradient of the Poisson log-likelihood
        att[r.home_id] = ah + lr * gh
        dfn[r.away_id] = da - lr * gh
        att[r.away_id] = aa + lr * ga
        dfn[r.home_id] = dh - lr * ga
    if keep:
        return pd.Series(exp, index=df.index), att, dfn
    return pd.Series(exp, index=df.index)


def main() -> None:
    df = load()
    val = (df.date >= VAL[0]) & (df.date < VAL[1])
    test = df.date >= TEST_FROM
    start = starting_levels(df)
    ladder = {"elo (the loop's)": (brier(df.p_home[val], df.res[val]), brier(df.p_home[test], df.res[test]))}

    best = None
    for K in (15.0, 20.0):
        for base in (40.0, 60.0):
            for shrink in (0.0, 0.15, 0.3):
                for fresh in (0.0, 1.0):
                    e = elo_plus(df, K, base, shrink, fresh, start)
                    b = brier(e[val], df.res[val])
                    if best is None or b < best[0]:
                        best = (b, dict(K=K, base_home=base, shrink=shrink, fresh=fresh), e)
    e1 = best[2]
    ladder["elo+"] = (best[0], brier(e1[test], df.res[test]))

    bestg = None
    for lr in (0.02, 0.04, 0.06):
        for scale in (400.0, 800.0):
            g = goals_model(df, lr, start, scale)
            b = brier(g[val], df.res[val])
            if bestg is None or b < bestg[0]:
                bestg = (b, dict(lr=lr, scale=scale), g)
    g2 = bestg[2]
    ladder["goals"] = (bestg[0], brier(g2[test], df.res[test]))
    blend = (e1 + g2) / 2
    ladder["blend"] = (brier(blend[val], df.res[val]), brier(blend[test], df.res[test]))

    out = {"split": {"validation": VAL, "test_from": TEST_FROM, "matches": len(df), "test_matches": int(test.sum())},
           "ladder": {k: {"validation": round(v[0], 4), "test": round(v[1], 4)} for k, v in ladder.items()},
           "settings": {"elo+": best[1], "goals": bestg[1]}}
    (LAKE / "strength" / "v2_ladder.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    for k, v in out["ladder"].items():
        print(f"{k:18s} validation {v['validation']:.4f}  test {v['test']:.4f}")
    print("settings:", out["settings"])

    # The ratings at the end of the data, from the goals model (attack + defence), for the placement check.
    _, att, dfn = goals_model(df, bestg[1]["lr"], start, bestg[1]["scale"], keep=True)
    names = pd.concat([df[["home_id", "home"]].set_axis(["team_id", "team"], axis=1),
                       df[["away_id", "away"]].set_axis(["team_id", "team"], axis=1)]).drop_duplicates("team_id", keep="last")
    teams = names.assign(strength=names.team_id.map(lambda t: att.get(t, 0) + dfn.get(t, 0)))
    teams.sort_values("strength", ascending=False).to_parquet(LAKE / "strength" / "team_ratings_v2.parquet")
    probe = teams[teams.team.str.contains(r"^(Barcelona|Barça Atl|Real Madrid|Ajax|Jong Ajax|Manchester City|Benfica)",
                                          regex=True, na=False)]
    print(probe.sort_values("strength", ascending=False).head(20).to_string(index=False))


if __name__ == "__main__":
    main()
