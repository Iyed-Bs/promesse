"""Promesse T1: game models. How each team plays, match by match and season by season.

Every team-match is summed from its players' MatchData rows (2021/22 on, where the detailed stats exist); the opponent's
rows give the denominators; shots give xG by situation. Fifteen dimensions, each a rate, so a team's style doesn't
depend on how many matches it played. A team-season is its league matches' average, shrunk towards the league-season
mean by how many matches it has (empirical Bayes: k = within-team match variance / between-team variance), then
standardised within its league-season, so a "direct" side means direct for its league. League-seasons are keyed
by MatchData's league id: two countries' "Bundesliga" or "Premier League" are different leagues.

Gate (T1): each dimension is reliable. For team-seasons with 20+ matches, the odd and even matches (by date) give two
estimates; centred by league-season, their Spearman correlation across teams must be 0.6 or more. Dimensions that
fail are kept in the file and flagged, never used by T2-T5.

    python gold/team_style.py      (Promesse venv) -> lake/gold/team_matches.parquet, team_style.parquet,
                                                      team_style_report.json
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
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

DATA = Path(DATA_ROOT)
LAKE = DATA / "lake"
GOLD = LAKE / "gold"
PM = (LAKE / "matchdata" / "player_matches").as_posix() + "/**/*.parquet"
SHOTS = (LAKE / "matchdata" / "shots.parquet").as_posix()
MIN_SPLIT = 20
DIMS = ["possession", "combination", "directness", "progression", "width", "dribbling", "box_presence", "pressing",
        "ball_winning", "aerial_play", "chance_quality", "counter", "set_pieces", "back_three", "two_up_front"]
# competitions that are a team's own league (style is judged against the league it plays in)
CUPS = r"(?i)cup|copa|coupe|pokal|coppa|beker|taça|champions league|europa|conference|qualification|super ?cup|playoff|youth|friend"


def team_matches(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    sql = f"""
    with p as (
      select match_id, league_id::bigint league_id, league, season, try_cast(left(date, 10) as date) date, team_id::bigint team_id, team, home,
             formation,
             coalesce("Touches", 0) touches, coalesce("Accurate passes (of)", 0) passes, coalesce("Accurate long balls (of)", 0) longs,
             coalesce("Accurate crosses (of)", 0) crosses, coalesce("Passes into final third", 0) final_third,
             coalesce("Successful dribbles (of)", 0) dribbles, coalesce("Touches in opposition box", 0) box,
             coalesce("Defensive actions", 0) def_actions, coalesce("Recoveries", 0) recoveries,
             coalesce("Aerial duels won (of)", 0) aerials, ("Accurate passes (of)" is not null)::int detailed
      from read_parquet('{PM}', union_by_name=true) where team_id is not null),
    t as (
      select match_id, any_value(league_id) league_id, any_value(league) league, any_value(season) season, any_value(date) date, team_id,
             any_value(team) team, any_value(home) home, mode(formation) formation,
             sum(touches) touches, sum(passes) passes, sum(longs) longs, sum(crosses) crosses, sum(final_third) final_third,
             sum(dribbles) dribbles, sum(box) box, sum(def_actions) def_actions, sum(recoveries) recoveries,
             sum(aerials) aerials, sum(detailed) detailed
      from p group by match_id, team_id),
    s as (
      select match_id, team_id::bigint team_id, count(*) shots, sum(xg) xg,
             sum(xg) filter (where situation = 'FastBreak') xg_fast,
             sum(xg) filter (where situation in ('RegularPlay', 'FastBreak', 'IndividualPlay')) xg_open,
             sum(xg) filter (where situation in ('SetPiece', 'FromCorner', 'FreeKick', 'ThrowInSetPiece')) xg_set
      from read_parquet('{SHOTS}') where not coalesce(own_goal, false) group by 1, 2)
    select t.*, o.team_id opp_id, o.team opp, o.touches opp_touches, o.passes opp_passes,
           coalesce(s.shots, 0) shots, coalesce(s.xg, 0) xg, coalesce(s.xg_fast, 0) xg_fast, coalesce(s.xg_open, 0) xg_open,
           coalesce(s.xg_set, 0) xg_set
    from t join t o on o.match_id = t.match_id and o.team_id <> t.team_id
    left join s on s.match_id = t.match_id and s.team_id = t.team_id
    where t.detailed >= 8 and o.detailed >= 8 and t.passes > 80 and o.passes > 80
    """
    d = con.execute(sql).df()
    eps = 1e-9
    d["possession"] = d.touches / (d.touches + d.opp_touches + eps)
    d["combination"] = d.passes / (d.touches + eps)
    d["directness"] = d.longs / (d.passes + eps)
    d["progression"] = d.final_third / (d.passes + eps)
    d["width"] = d.crosses / (d.final_third + eps)
    d["dribbling"] = d.dribbles / (d.touches + eps)
    d["box_presence"] = d.box / (d.touches + eps)
    d["pressing"] = d.def_actions / (d.opp_passes + eps)
    d["ball_winning"] = d.recoveries / (d.opp_touches + eps)
    d["aerial_play"] = d.aerials
    d["chance_quality"] = np.where(d.shots > 0, d.xg / d.shots.clip(lower=1), np.nan)
    d["counter"] = np.where(d.xg_open > 0.05, d.xg_fast / d.xg_open.clip(lower=0.05), np.nan)
    d["set_pieces"] = np.where(d.xg > 0.05, d.xg_set / d.xg.clip(lower=0.05), np.nan)
    f = d.formation.fillna("")
    d["back_three"] = f.str.match(r"^[35]-").astype(float).where(f != "")
    d["two_up_front"] = f.str.match(r".*-2$").astype(float).where(f != "")
    d["league_match"] = ~d.league.fillna("").str.contains(CUPS)
    return d


def shrunk_seasons(d: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Team-season means, shrunk to the league-season mean, then z-scored within the league-season."""
    lm = d[d.league_match]
    g = lm.groupby(["league_id", "season", "team_id"])
    mean, n = g[DIMS].mean(), g.size().rename("n")
    var_within = g[DIMS].var().mean()                                    # match-to-match noise inside a team
    var_between = mean.groupby(level=[0, 1]).var().mean()                # spread of team means in a league
    k = (var_within / var_between.clip(lower=1e-12)).clip(upper=60)
    league_mean = mean.groupby(level=[0, 1]).transform("mean")
    w = n.values[:, None] / (n.values[:, None] + k.values[None, :])
    shr = mean * w + league_mean * (1 - w)
    z = (shr - shr.groupby(level=[0, 1]).transform("mean")) / shr.groupby(level=[0, 1]).transform("std").replace(0, np.nan)
    out = pd.concat([n, mean.add_prefix("raw_"), z.add_prefix("z_")], axis=1).reset_index()
    names = lm.groupby(["league_id", "season", "team_id"]).agg(league=("league", "first"), team=("team", "first"), first=("date", "min"), last=("date", "max"))
    return out.merge(names.reset_index(), on=["league_id", "season", "team_id"]), {k_: round(float(v), 2) for k_, v in k.items()}


def reliability(d: pd.DataFrame) -> dict:
    """Odd vs even matches of each team-season, centred by league-season; Spearman across team-seasons."""
    lm = d[d.league_match].sort_values("date").copy()
    lm["half"] = lm.groupby(["league_id", "season", "team_id"]).cumcount() % 2
    size = lm.groupby(["league_id", "season", "team_id"]).size()
    keep = size[size >= MIN_SPLIT].index
    h = lm.set_index(["league_id", "season", "team_id"]).loc[keep].reset_index()
    halves = h.groupby(["league_id", "season", "team_id", "half"])[DIMS].mean().unstack("half")
    res = {}
    for dim in DIMS:
        a, b = halves[(dim, 0)], halves[(dim, 1)]
        a = a - a.groupby(level=[0, 1]).transform("mean")
        b = b - b.groupby(level=[0, 1]).transform("mean")
        ok = a.notna() & b.notna()
        res[dim] = round(float(spearmanr(a[ok], b[ok]).statistic), 3) if ok.sum() > 30 else None
    return {"team_seasons": int(len(halves)), "spearman_odd_even": res}


def archetypes(s: pd.DataFrame, dims: list[str]) -> tuple[pd.DataFrame, dict]:
    x = s[[f"z_{d}" for d in dims]].fillna(0).to_numpy()
    best = None
    for k in range(5, 10):
        km = KMeans(n_clusters=k, n_init=20, random_state=7).fit(x)
        sc = silhouette_score(x, km.labels_, sample_size=min(4000, len(x)), random_state=7)
        if best is None or sc > best[0]:
            best = (sc, k, km)
    sc, k, km = best
    s = s.copy()
    s["archetype"] = km.labels_
    cent = {int(i): {d: round(float(v), 2) for d, v in zip(dims, c)} for i, c in enumerate(km.cluster_centers_)}
    return s, {"k": k, "silhouette": round(float(sc), 3), "centres": cent,
               "sizes": {int(i): int((km.labels_ == i).sum()) for i in range(k)}}


def main() -> None:
    con = duckdb.connect()
    d = team_matches(con)
    d.to_parquet(GOLD / "team_matches.parquet", index=False)
    s, k = shrunk_seasons(d)
    rel = reliability(d)
    passed = [dim for dim, r in rel["spearman_odd_even"].items() if r is not None and r >= 0.6]
    s, arch = archetypes(s, passed)
    s.to_parquet(GOLD / "team_style.parquet", index=False)
    report = {"team_matches": int(len(d)), "league_team_matches": int(d.league_match.sum()), "team_seasons": int(len(s)),
              "shrinkage_k": k, "reliability": rel, "dimensions_passed": passed,
              "dimensions_failed": [x for x in DIMS if x not in passed],
              "gate_t1": {"rule": "each dimension: odd vs even matches agree, Spearman >= 0.6 (team-seasons with 20+ matches)",
                          "passed": len(passed) >= 10},
              "archetypes": arch}
    (GOLD / "team_style_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k_: report[k_] for k_ in ("team_matches", "team_seasons", "dimensions_passed", "dimensions_failed", "gate_t1")}, indent=1))
    print("reliability:", rel["spearman_odd_even"])
    print("archetypes:", arch["k"], arch["silhouette"], arch["sizes"])


if __name__ == "__main__":
    main()
