"""Promesse T2: coach fingerprints. Does a coach carry his way of playing from club to club?

1. Link: every MatchData team-match to its Transfermarkt game and club, through the players who played it (identity v3:
   MatchData id -> Transfermarkt id; their Transfermarkt appearance on the same date, +/- 1 day). A team-match is linked
   when 3+ of its players agree. Transfermarkt then names the manager (club_games).
2. Styles: each team-match's T1 dimensions, standardised within its league-season (in units of the spread between
   teams, as T1's team-season z-scores). A spell (a coach at a club) is the shrunk mean of its league matches.
3. The test: for a coach who moved from club A to club B, with 10+ league matches each and 10+ matches of B under
   other coaches in the 400 days before he arrived,
       style(B under him) = a * style(A under him) + b * style(B before him) + e,  one regression per dimension.
   a > 0 with a 95 % bootstrap interval (over moves) above zero: the coach carries that dimension.

Gate (T2): the coach effect a is above zero (interval) on at least half of T1's reliable dimensions.

    python gold/coach_style.py     (Promesse venv) -> lake/gold/match_link.parquet, coach_spells.parquet,
                                                      coach_moves.parquet, coach_style_report.json
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
GOLD = DATA / "lake" / "gold"
PM = (DATA / "lake" / "matchdata" / "player_matches").as_posix() + "/**/*.parquet"
TM = (DATA / "transfermarkt-datasets.duckdb").as_posix()
PERSONS = (DATA / "lake" / "identity" / "persons.parquet").as_posix()
MIN_SPELL, MIN_BEFORE, SHRINK_K, BOOT = 10, 10, 8.0, 2000


def link(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute(f"""
      with fm as (select distinct match_id, team_id::bigint team_id, try_cast(left(date, 10) as date) date,
                         player_id::varchar fid from read_parquet('{PM}', union_by_name=true)
                  where team_id is not null and try_cast("Minutes played" as double) > 0),
           ids as (select try_cast(tm_id as bigint) tm_id, matchdata_id::varchar fid from read_parquet('{PERSONS}')
                   where tm_id is not null and matchdata_id is not null),
           hit as (select fm.match_id, fm.team_id, a.game_id, a.player_club_id::bigint club_id
                   from fm join ids using (fid)
                   join tm.appearances a on a.player_id::bigint = ids.tm_id and abs(date_diff('day', a.date::date, fm.date)) <= 1)
      select match_id, team_id, mode(game_id) game_id, mode(club_id) club_id, count(*) n_players
      from hit group by 1, 2 having count(*) >= 3""").df()


def main() -> None:
    con = duckdb.connect()
    con.execute(f"attach '{TM}' as tm (read_only)")
    lk = link(con)
    lk.to_parquet(GOLD / "match_link.parquet", index=False)
    mgr = con.execute("select game_id::bigint game_id, club_id::bigint club_id, own_manager_name manager from tm.club_games "
                      "where own_manager_name is not null").df()
    rep = json.loads((GOLD / "team_style_report.json").read_text(encoding="utf-8"))
    dims = rep["dimensions_passed"]
    tm = pd.read_parquet(GOLD / "team_matches.parquet")
    tm = tm[tm.league_match]
    # standardise each match within its league-season, in units of the spread between that league's teams
    ts = tm.groupby(["league_id", "season", "team_id"])[dims].mean()
    mu, sd = ts.groupby(level=[0, 1]).mean(), ts.groupby(level=[0, 1]).std().replace(0, np.nan)
    key = pd.MultiIndex.from_frame(tm[["league_id", "season"]])
    z = (tm[dims].to_numpy() - mu.reindex(key).to_numpy()) / sd.reindex(key).to_numpy()
    zm = pd.concat([tm[["match_id", "team_id", "team", "league_id", "league", "season", "date"]].reset_index(drop=True),
                    pd.DataFrame(z, columns=dims)], axis=1)
    zm = zm.merge(lk[["match_id", "team_id", "game_id", "club_id"]], on=["match_id", "team_id"], how="left")
    zm = zm.merge(mgr, on=["game_id", "club_id"], how="left")
    linked = float(zm.game_id.notna().mean())
    with_mgr = zm[zm.manager.notna()]

    def shrunk(g: pd.DataFrame) -> pd.Series:
        n = len(g)
        return pd.concat([pd.Series({"n": n, "first": g.date.min(), "last": g.date.max(), "team": g.team.iloc[0]}),
                          g[dims].mean() * n / (n + SHRINK_K)])
    spells = with_mgr.groupby(["manager", "club_id"]).apply(shrunk, include_groups=False).reset_index()
    spells.to_parquet(GOLD / "coach_spells.parquet", index=False)

    # the moves: consecutive clubs of the same coach, each spell long enough, and the new club's style before him
    good = spells[spells.n >= MIN_SPELL].sort_values(["manager", "first"])
    rows = []
    for mname, g in good.groupby("manager"):
        g = g.reset_index(drop=True)
        for i in range(len(g) - 1):
            a, b = g.iloc[i], g.iloc[i + 1]
            if b["first"] <= a["first"]:
                continue
            before = zm[(zm.club_id == b.club_id) & (zm.manager != mname) & (zm.date < b["first"])
                        & (zm.date >= b["first"] - pd.Timedelta(days=400))]
            if len(before) < MIN_BEFORE:
                continue
            nb = len(before)
            rows.append({"manager": mname, "from": a.team, "to": b.team, "arrived": b["first"], "n_a": a.n, "n_b": b.n,
                         "n_before": nb, **{f"a_{d}": a[d] for d in dims}, **{f"b_{d}": b[d] for d in dims},
                         **{f"pre_{d}": before[d].mean() * nb / (nb + SHRINK_K) for d in dims}})
    mv = pd.DataFrame(rows)
    mv.to_parquet(GOLD / "coach_moves.parquet", index=False)

    rng = np.random.default_rng(7)
    res = {}
    for d in dims:
        m = mv[[f"a_{d}", f"pre_{d}", f"b_{d}"]].dropna()
        X = np.column_stack([np.ones(len(m)), m[f"a_{d}"], m[f"pre_{d}"]])
        y = m[f"b_{d}"].to_numpy()
        coef = np.linalg.lstsq(X, y, rcond=None)[0]
        boots = []
        for _ in range(BOOT):
            idx = rng.integers(0, len(m), len(m))
            boots.append(np.linalg.lstsq(X[idx], y[idx], rcond=None)[0][1])
        lo, hi = np.percentile(boots, [2.5, 97.5])
        res[d] = {"coach_a": round(float(coef[1]), 3), "ci95": [round(float(lo), 3), round(float(hi), 3)],
                  "club_b": round(float(coef[2]), 3), "moves": int(len(m)), "passed": bool(lo > 0)}
    carried = [d for d, r in res.items() if r["passed"]]
    report = {"team_matches_linked_to_transfermarkt": round(linked, 3), "matches_with_manager": int(len(with_mgr)),
              "spells": int(len(spells)), "coach_moves_tested": int(len(mv)), "by_dimension": res,
              "dimensions_coaches_carry": carried,
              "gate_t2": {"rule": "coach effect a > 0 (95 % bootstrap interval over moves) on at least half of T1's reliable dimensions",
                          "passed": len(carried) >= len(dims) / 2}}
    (GOLD / "coach_style_report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("team_matches_linked_to_transfermarkt", "matches_with_manager", "spells",
                                              "coach_moves_tested", "dimensions_coaches_carry", "gate_t2")}, indent=1, default=str))
    for d, r in res.items():
        print(f"  {d:15s} coach {r['coach_a']:+.3f} [{r['ci95'][0]:+.3f}, {r['ci95'][1]:+.3f}]  club before {r['club_b']:+.3f}  n={r['moves']}")


if __name__ == "__main__":
    main()
