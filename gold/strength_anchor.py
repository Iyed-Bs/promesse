"""Promesse, Phase 2b experiment: league-anchored Elo+ (the Danish Superliga's median team rated above the
Bundesliga's, because a league's average only moves through the few games its clubs play outside it).

Same model as gold/strength_tm.py (its chosen settings), plus one level per league: a team's strength in a game is its
own rating plus its league's level. Inside a league the levels cancel, so domestic games are untouched; in a game
between two leagues (European cups, mostly) the result also moves both leagues' levels, by KL, so one club's European
results inform its whole league. KL is chosen on 2018-2020 on cross-league games, tested once on 2021 on.
Gate: Brier on cross-league test games lower than Elo+'s, 95 % bootstrap interval of the gain above zero, and all test
games no worse. Writes only its own report: nothing downstream changes until the gate passes and the rebuild is chosen.

    python gold/strength_anchor.py      (Promesse venv) -> lake/gold/strength_anchor_report.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import strength_tm as S  # noqa: E402

rng = np.random.default_rng(7)


def run_anchored(df: pd.DataFrame, K: float, base_home: float, shrink: float, fresh: float, KL: float):
    edge = S.home_edge(df, S.VAL[0], base_home)
    rating: dict[int, float] = {}
    played: dict[int, int] = {}
    league_of: dict[int, str] = {}
    level: dict[str, float] = {}                      # each league's level, added to its teams' own ratings
    exp, rh_all, ra_all = np.empty(len(df)), np.empty(len(df)), np.empty(len(df))
    cross = np.zeros(len(df), dtype=bool)
    season_now = None
    for i, r in enumerate(df.itertuples()):
        if r.season != season_now:
            if season_now is not None and shrink > 0:
                means: dict[str, list[float]] = {}
                for t, lg in league_of.items():
                    means.setdefault(lg, []).append(rating.get(t, S.START))
                lvl = {lg: float(np.mean(v)) for lg, v in means.items()}
                for t in rating:
                    target = lvl.get(league_of.get(t, ""), S.START)
                    rating[t] = target + (rating[t] - target) * (1 - shrink)
            season_now = r.season
        lh, la = league_of.get(r.home_id), league_of.get(r.away_id)
        is_cross = lh is not None and la is not None and lh != la
        rh = rating.get(r.home_id, S.START) + level.get(lh, 0.0)
        ra = rating.get(r.away_id, S.START) + level.get(la, 0.0)
        h = edge.get(r.competition_id, base_home)
        e = 1 / (1 + 10 ** ((ra - rh - h) / 400))
        exp[i], rh_all[i], ra_all[i], cross[i] = e, rh, ra, is_cross
        margin = (abs(r.hg - r.ag) + 1) ** 0.5
        kh = K * (1 + fresh / (1 + played.get(r.home_id, 0) / 10))
        ka = K * (1 + fresh / (1 + played.get(r.away_id, 0) / 10))
        rating[r.home_id] = rating.get(r.home_id, S.START) + kh * margin * (r.res - e)
        rating[r.away_id] = rating.get(r.away_id, S.START) - ka * margin * (r.res - e)
        if is_cross and KL > 0:
            level[lh] = level.get(lh, 0.0) + KL * margin * (r.res - e)
            level[la] = level.get(la, 0.0) - KL * margin * (r.res - e)
        played[r.home_id] = played.get(r.home_id, 0) + 1
        played[r.away_id] = played.get(r.away_id, 0) + 1
        if r.ctype == "domestic_league":
            league_of[r.home_id] = r.competition_id
            league_of[r.away_id] = r.competition_id
    return exp, rh_all, ra_all, cross, level


def main() -> None:
    df = S.games()
    set_ = json.loads((S.OUT / "tm_strength_report.json").read_text(encoding="utf-8"))["settings"]
    y = df.res.to_numpy()
    val = ((df.date >= S.VAL[0]) & (df.date < S.VAL[1])).to_numpy()
    test = (df.date >= S.TEST_FROM).to_numpy()
    base = run_anchored(df, set_["K"], set_["base_home"], set_["shrink"], set_["fresh"], KL=0.0)   # = Elo+ as it stands
    cross = base[3]
    tried = {}
    best = None
    for KL in (2.0, 5.0, 10.0, 20.0, 40.0):
        out = run_anchored(df, set_["K"], set_["base_home"], set_["shrink"], set_["fresh"], KL=KL)
        b = S.brier(out[0][val & cross], y[val & cross])
        tried[KL] = round(b, 5)
        if best is None or b < best[0]:
            best = (b, KL, out)
    _, KL, out = best
    t_cross = test & cross
    d = (base[0][t_cross] - y[t_cross]) ** 2 - (out[0][t_cross] - y[t_cross]) ** 2
    boots = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)]
    gain = {"mean": float(d.mean()), "ci95": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]}
    all_base, all_new = S.brier(base[0][test], y[test]), S.brier(out[0][test], y[test])
    passed = gain["ci95"][0] > 0 and all_new <= all_base
    # the drift that started it: each league's median team level against the big five's, 2025/26, before and after
    def medians(o) -> dict:
        g = df.assign(rh=o[1], ra=o[2])
        g = g[(g.ctype == "domestic_league") & (g.season == 2025)]
        sides = pd.concat([g[["competition_id", "home_id", "rh"]].set_axis(["lg", "team", "r"], axis=1),
                           g[["competition_id", "away_id", "ra"]].set_axis(["lg", "team", "r"], axis=1)])
        team = sides.groupby(["lg", "team"]).r.mean().reset_index()
        ref = team[team.lg.isin(S.BIG5)].r.mean()
        return (team.groupby("lg").r.median() - ref).round(0).to_dict()
    mb, mn = medians(base), medians(out)
    show = ["GB1", "ES1", "L1", "IT1", "FR1", "DK1", "PO1", "NL1", "BE1", "TR1", "SC1", "GR1", "A1", "C1", "RU1", "UKR1"]
    report = {"settings": set_, "KL_tried_val_cross_brier": tried, "KL": KL,
              "cross_league_games": {"val": int((val & cross).sum()), "test": int(t_cross.sum())},
              "brier_test_cross": {"elo_plus": S.brier(base[0][t_cross], y[t_cross]), "anchored": S.brier(out[0][t_cross], y[t_cross])},
              "gain_cross": gain, "brier_test_all": {"elo_plus": all_base, "anchored": all_new}, "gate_passed": passed,
              "median_team_vs_big5_2025": {lg: {"elo_plus": mb.get(lg), "anchored": mn.get(lg)} for lg in show if lg in mb},
              "league_levels": {k: round(v, 1) for k, v in sorted(out[4].items(), key=lambda kv: -kv[1])[:40]}}
    (S.OUT / "strength_anchor_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("KL_tried_val_cross_brier", "KL", "cross_league_games", "brier_test_cross",
                                             "gain_cross", "brier_test_all", "gate_passed", "median_team_vs_big5_2025")}, indent=1))


if __name__ == "__main__":
    main()
