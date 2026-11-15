"""Promesse, Phase 2c: quality minutes and careers, from Transfermarkt's appearances (2012-2026).

Quality minutes (ARCHITECTURE D1, frozen v1): every minute is weighted by the level of the match it was played in:

    level  = (team's rating + opponent's rating) / 2, both before the game (gold/strength_tm.py)
    factor = 2 · E(level vs the big five's average that season), clipped to [0.05, 2]
    qmin   = minutes × factor

so a minute in a match at the big five's average level counts 1, a match 200 Elo points below counts about 0.48, and a
Champions League night between two strong sides counts up to 2.

Careers: per player, club and season, the league minutes and the share of his team's league minutes (games × 90), and
the team's level that season (its mean pre-game rating in the league, minus the season's reference).

    python gold/careers.py      (Promesse venv) -> lake/gold/appearance_quality.parquet, player_club_seasons.parquet,
                                                   player_seasons.parquet, careers_report.json
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

DATA = Path(DATA_ROOT)
TM = DATA / "transfermarkt-datasets.duckdb"
GOLD = DATA / "lake" / "gold"
QUALITY_VERSION = "qmin v1: minutes × 2·E(match level vs big-five average), clipped to [0.05, 2]"


def main() -> None:
    c = duckdb.connect(str(TM), read_only=True)
    apps = c.sql("""
        select player_id::bigint as player_id, player_club_id::bigint as club_id, game_id::bigint as game_id,
               date::date as date, competition_id,
               coalesce(minutes_played, 0) as minutes
        from appearances where minutes_played > 0
    """).df()
    c.close()
    s = pd.read_parquet(GOLD / "tm_game_strength.parquet")
    ref = pd.read_parquet(GOLD / "tm_reference_level.parquet")
    a = apps.merge(s[["game_id", "season", "ctype", "home_id", "away_id", "r_home", "r_away"]], on="game_id", how="inner")
    home = a.club_id == a.home_id
    a["r_team"] = np.where(home, a.r_home, a.r_away)
    a["r_opp"] = np.where(home, a.r_away, a.r_home)
    a = a.merge(ref, on="season", how="left")
    level = (a.r_team + a.r_opp) / 2
    a["level_rel"] = level - a.ref
    a["factor"] = np.clip(2 / (1 + 10 ** ((a.ref - level) / 400)), 0.05, 2.0)
    a["qmin"] = a.minutes * a.factor
    a["date"] = pd.to_datetime(a["date"])
    keep = ["player_id", "club_id", "game_id", "date", "season", "competition_id", "ctype", "minutes", "qmin", "factor",
            "level_rel"]
    GOLD.mkdir(parents=True, exist_ok=True)
    a[keep].to_parquet(GOLD / "appearance_quality.parquet", index=False)

    # each club's league games and level per season
    lg = s[s.ctype == "domestic_league"]
    sides = pd.concat([lg[["season", "competition_id", "home_id", "r_home"]].set_axis(["season", "league", "club_id", "r"], axis=1),
                       lg[["season", "competition_id", "away_id", "r_away"]].set_axis(["season", "league", "club_id", "r"], axis=1)])
    team = (sides.groupby(["season", "club_id"])
                 .agg(league=("league", lambda x: x.mode().iat[0]), team_games=("r", "size"), team_r=("r", "mean"))
                 .reset_index().merge(ref, on="season", how="left"))
    team["team_level_rel"] = team.team_r - team.ref

    la = a[a.ctype == "domestic_league"]
    pcs = (la.groupby(["player_id", "season", "club_id"])
             .agg(league_min=("minutes", "sum"), league_qmin=("qmin", "sum"), league_apps=("minutes", "size"))
             .reset_index().merge(team[["season", "club_id", "league", "team_games", "team_level_rel"]],
                                  on=["season", "club_id"], how="left"))
    pcs["share"] = (pcs.league_min / (pcs.team_games * 90)).clip(upper=1.0)
    pcs.to_parquet(GOLD / "player_club_seasons.parquet", index=False)

    tot = a.groupby(["player_id", "season"]).agg(minutes=("minutes", "sum"), qmin=("qmin", "sum"),
                                                 clubs=("club_id", "nunique")).reset_index()
    by_ct = a.pivot_table(index=["player_id", "season"], columns="ctype", values="minutes", aggfunc="sum", fill_value=0)
    by_ct.columns = [f"min_{c}" for c in by_ct.columns]
    best = pcs.sort_values("share", ascending=False).drop_duplicates(["player_id", "season"])
    best = best[["player_id", "season", "share", "team_level_rel", "league"]].rename(
        columns={"share": "best_share", "team_level_rel": "best_share_level", "league": "best_share_league"})
    ps = tot.merge(by_ct.reset_index(), on=["player_id", "season"], how="left").merge(best, on=["player_id", "season"], how="left")
    ps.to_parquet(GOLD / "player_seasons.parquet", index=False)

    report = {"version": QUALITY_VERSION, "appearances": int(len(a)), "players": int(a.player_id.nunique()),
              "player_seasons": int(len(ps)), "player_club_seasons": int(len(pcs)),
              "seasons": [int(ps.season.min()), int(ps.season.max())],
              "factor_quantiles": {q: round(float(a.factor.quantile(q)), 3) for q in (0.1, 0.5, 0.9)},
              "unmatched_appearances": int(len(apps) - len(a))}
    (GOLD / "careers_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
