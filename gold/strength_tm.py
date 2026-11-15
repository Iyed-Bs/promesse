"""Promesse, Phase 2b: team strength on Transfermarkt's games, 2006-2026, so careers from 2012 have a level at every date.

The MatchData strength (lake/strength_v2.py) starts in earnest in 2021; careers need 2012 on. Transfermarkt's club games
(31 first divisions, domestic cups, UEFA competitions) start in July 2012 and give one connected graph: the European
cups tie the leagues to one scale. Every team starts at the same rating, so 2012/13 and 2013/14 are burn-in seasons:
the spine's first snapshot is the start of the 2014/15 season. (ClubElo's league levels would give a point-in-time start instead; its API
didn't answer in 2026 and the cached files are empty, so it's queued as a source.)

The model is strength v2's Elo+ (home advantage learned per competition, faster updates for teams with few games, a
summer pull toward the competition's level), here recording every team's rating before every game, which is what
quality minutes need. It is judged against plain Elo on the same games: settings chosen on 2018-2020, tested once on
2021 onward.

League levels (gold/strength_anchor.py): a team's strength in a game is its own rating plus its league's
level. Inside a league the levels cancel; in a game between two leagues the result also moves both leagues' levels by
KL, so one club's European results inform its whole league. Without them a league's average only moved through the
few games its clubs play abroad, and isolated leagues drifted (the Danish Superliga's median team rated above the
Bundesliga's). KL is chosen on 2018-2020's cross-league games; on 2021 on, the cross-league Brier fell from 0.176 to
0.165 (95 % interval of the gain 0.007 to 0.015) and all games' from 0.1655 to 0.1652.

    python gold/strength_tm.py      (Promesse venv) -> lake/gold/tm_game_strength.parquet, tm_strength_report.json
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
import math
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

DATA = Path(DATA_ROOT)
TM = DATA / "transfermarkt-datasets.duckdb"
OUT = DATA / "lake" / "gold"
VAL = ("2018-07-01", "2021-07-01")
TEST_FROM = "2021-07-01"
START = 1500.0
# the big five's first divisions: their average rating at each season start is the reference level (quality factor 1)
BIG5 = ("GB1", "ES1", "IT1", "L1", "FR1")


def games() -> pd.DataFrame:
    c = duckdb.connect(str(TM), read_only=True)
    df = c.sql("""
        select g.game_id::bigint as game_id, g.date::date as date, g.season, g.competition_id, c.type as ctype,
               g.home_club_id::bigint as home_id, g.away_club_id::bigint as away_id,
               g.home_club_goals as hg, g.away_club_goals as ag
        from games g join competitions c using (competition_id)
        where c.type <> 'national_team_competition' and g.home_club_goals is not null and g.away_club_goals is not null
          and g.home_club_id is not null and g.away_club_id is not null
        order by g.date, g.game_id
    """).df()
    c.close()
    df["res"] = np.where(df.hg > df.ag, 1.0, np.where(df.hg < df.ag, 0.0, 0.5))
    df["date"] = pd.to_datetime(df["date"])
    df["season"] = df["date"].map(lambda d: d.year if d.month >= 7 else d.year - 1)
    return df.reset_index(drop=True)


def home_edge(df: pd.DataFrame, before: str, base: float) -> dict:
    """Home advantage per competition in Elo points, from games before `before`, shrunk toward `base`."""
    out = {}
    for cid, g in df[df.date < before].groupby("competition_id"):
        m = min(max(float(g.res.mean()), 0.35), 0.75)
        w = len(g) / (len(g) + 300)
        out[cid] = w * 400 * math.log10(m / (1 - m)) + (1 - w) * base
    return out


def run(df: pd.DataFrame, K: float, base_home: float, shrink: float, fresh: float, plain: bool = False, KL: float = 0.0):
    """Expected home score per game, and each side's strength before the game (own rating + league level).
    `plain`: K fixed, one home edge, no pull, no league levels."""
    edge = {} if plain else home_edge(df, VAL[0], base_home)
    rating: dict[int, float] = {}
    played: dict[int, int] = {}
    league_of: dict[int, str] = {}           # each team's last domestic league: where the summer pull goes
    level: dict[str, float] = {}             # each league's level, moved only by games between leagues
    exp = np.empty(len(df))
    rh_all = np.empty(len(df))
    ra_all = np.empty(len(df))
    season_now = None
    for i, r in enumerate(df.itertuples()):
        if not plain and r.season != season_now:
            if season_now is not None and shrink > 0:
                means: dict[str, list[float]] = {}
                for t, lg in league_of.items():
                    means.setdefault(lg, []).append(rating.get(t, START))
                lvl = {lg: float(np.mean(v)) for lg, v in means.items()}
                for t in rating:
                    target = lvl.get(league_of.get(t, ""), START)
                    rating[t] = target + (rating[t] - target) * (1 - shrink)
            season_now = r.season
        lh, la = league_of.get(r.home_id), league_of.get(r.away_id)
        cross = not plain and KL > 0 and lh is not None and la is not None and lh != la
        rh = rating.get(r.home_id, START) + (0.0 if plain else level.get(lh, 0.0))
        ra = rating.get(r.away_id, START) + (0.0 if plain else level.get(la, 0.0))
        h = base_home if plain else edge.get(r.competition_id, base_home)
        e = 1 / (1 + 10 ** ((ra - rh - h) / 400))
        exp[i], rh_all[i], ra_all[i] = e, rh, ra
        margin = 1.0 if plain else (abs(r.hg - r.ag) + 1) ** 0.5
        kh = K if plain else K * (1 + fresh / (1 + played.get(r.home_id, 0) / 10))
        ka = K if plain else K * (1 + fresh / (1 + played.get(r.away_id, 0) / 10))
        rating[r.home_id] = rating.get(r.home_id, START) + kh * margin * (r.res - e)
        rating[r.away_id] = rating.get(r.away_id, START) - ka * margin * (r.res - e)
        if cross:
            level[lh] = level.get(lh, 0.0) + KL * margin * (r.res - e)
            level[la] = level.get(la, 0.0) - KL * margin * (r.res - e)
        played[r.home_id] = played.get(r.home_id, 0) + 1
        played[r.away_id] = played.get(r.away_id, 0) + 1
        if r.ctype == "domestic_league":
            league_of[r.home_id] = r.competition_id
            league_of[r.away_id] = r.competition_id
    return exp, rh_all, ra_all


def brier(p, y) -> float:
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def main() -> None:
    df = games()
    val = ((df.date >= VAL[0]) & (df.date < VAL[1])).to_numpy()
    test = (df.date >= TEST_FROM).to_numpy()
    y = df.res.to_numpy()
    plain = run(df, 20.0, 60.0, 0.0, 0.0, plain=True)
    best = None
    for K in (15.0, 20.0, 30.0):
        for base in (40.0, 60.0):
            for shrink in (0.0, 0.15, 0.3):
                for fresh in (0.0, 1.0):
                    out = run(df, K, base, shrink, fresh)
                    b = brier(out[0][val], y[val])
                    if best is None or b < best[0]:
                        best = (b, dict(K=K, base_home=base, shrink=shrink, fresh=fresh), out)
    # the league levels: KL chosen on the validation years' games between two leagues
    last_lg = {}
    cross_mask = np.zeros(len(df), dtype=bool)
    for i, r in enumerate(df[["home_id", "away_id", "ctype", "competition_id"]].itertuples(index=False)):
        a, b = last_lg.get(r.home_id), last_lg.get(r.away_id)
        cross_mask[i] = a is not None and b is not None and a != b
        if r.ctype == "domestic_league":
            last_lg[r.home_id] = last_lg[r.away_id] = r.competition_id
    kl_best = (brier(best[2][0][val & cross_mask], y[val & cross_mask]), 0.0, best[2])
    for KL in (2.0, 5.0, 10.0, 20.0):
        out = run(df, **best[1], KL=KL)
        b = brier(out[0][val & cross_mask], y[val & cross_mask])
        if b < kl_best[0]:
            kl_best = (b, KL, out)
    exp, rh, ra = kl_best[2]
    best[1]["KL"] = kl_best[1]
    report = {
        "games": int(len(df)), "first": str(df.date.min().date()), "last": str(df.date.max().date()),
        "settings": best[1],
        "brier_val": {"plain_elo": brier(plain[0][val], y[val]), "elo_plus": best[0]},
        "brier_test": {"plain_elo": brier(plain[0][test], y[test]), "elo_plus": brier(exp[test], y[test])},
        "brier_test_cross_league": {"plain_elo": brier(plain[0][test & cross_mask], y[test & cross_mask]),
                                    "elo_plus": brier(exp[test & cross_mask], y[test & cross_mask]),
                                    "games": int((test & cross_mask).sum())},
        "test_games": int(test.sum()),
    }
    report["gate_passed"] = report["brier_test"]["elo_plus"] < report["brier_test"]["plain_elo"]
    df["r_home"], df["r_away"] = rh, ra
    # the reference level: the big five's first-division teams' mean rating at their first league game of each season
    big = df[df.competition_id.isin(BIG5)]
    first = pd.concat([big[["season", "home_id", "r_home", "date"]].set_axis(["season", "team", "r", "date"], axis=1),
                       big[["season", "away_id", "r_away", "date"]].set_axis(["season", "team", "r", "date"], axis=1)])
    first = first.sort_values("date").drop_duplicates(["season", "team"])
    ref = first.groupby("season")["r"].mean().rename("ref").reset_index()
    report["reference_by_season"] = {int(s): round(float(r), 1) for s, r in zip(ref.season, ref.ref)}
    OUT.mkdir(parents=True, exist_ok=True)
    df[["game_id", "date", "season", "competition_id", "ctype", "home_id", "away_id", "r_home", "r_away"]].to_parquet(
        OUT / "tm_game_strength.parquet", index=False)
    ref.to_parquet(OUT / "tm_reference_level.parquet", index=False)
    (OUT / "tm_strength_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "reference_by_season"}, indent=1))


if __name__ == "__main__":
    main()
