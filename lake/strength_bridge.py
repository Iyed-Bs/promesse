"""Promesse Phase 2, second half: bridge the competitions' scales through players, not results.

A player who plays in two competitions in the same month (the U21 league and the first team, the Youth League and
his club's league, a U21 international and his club) is the same player on both pitches. The gap between his MatchData
ratings there says how much easier one competition is than the other. Across thousands of such months, one offset
per competition explains them all:

    rating(player, month, competition) = form(player, month) + ease(competition) + noise
    so  rating_A - rating_B = ease(A) - ease(B)      for the same player in the same month

The offsets are fitted by weighted least squares on the comparison graph (weight: the harmonic mean of the minutes on
each side), with the Premier League at 0 and a small ridge. Competitions that never share a player with the rest stay
unplaced: results alone can't join them, and neither can this.

The test, out of time: offsets fitted on months before July 2024, judged once on the pairs from July 2024 on, against
a ladder of simpler answers (no offset; one offset for "youth vs senior"), with a paired bootstrap over players.

    python strength_bridge.py      (Promesse venv) -> lake/strength/bridge_offsets.parquet, bridge_report.json
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

LAKE = Path((DATA_ROOT + "/lake"))
SPLIT = "2024-07"
MIN_MINUTES = 30          # each side of a pair
REFERENCE = 47            # Premier League: ease 0
THIN = 30                 # fewer shared players than this: the offset is shown, flagged thin, never used
RIDGE = 1.0
YOUTH = re.compile(r"U1\d|U2\d|Youth|Premier League 2|Primavera|Juvenil|Reserve", re.I)


def monthly() -> pd.DataFrame:
    """One row per player, month and competition: minutes-weighted mean rating, minutes."""
    pm = f"read_parquet('{(LAKE / 'matchdata' / 'player_matches').as_posix()}/**/*.parquet', union_by_name=true)"
    return duckdb.sql(f"""
        select player_id, substr(date, 1, 7) as month, league_id, any_value(league) as league,
               sum("matchdata rating" * "Minutes played") / sum("Minutes played") as rating,
               sum("Minutes played") as minutes
        from {pm}
        where "matchdata rating" is not null and "Minutes played" > 0 and player_id is not null
        group by 1, 2, 3
        having sum("Minutes played") >= {MIN_MINUTES}
    """).df()


def pairs(m: pd.DataFrame) -> pd.DataFrame:
    """Every pair of competitions a player rated in within one month: d = rating_A - rating_B, weight."""
    j = m.merge(m, on=["player_id", "month"], suffixes=("_a", "_b"))
    j = j[j["league_id_a"] < j["league_id_b"]].copy()
    j["d"] = j["rating_a"] - j["rating_b"]
    j["w"] = 2 * j["minutes_a"] * j["minutes_b"] / (j["minutes_a"] + j["minutes_b"]) / 90.0
    return j.reset_index(drop=True)


def fit(p: pd.DataFrame, leagues: list[int]) -> dict[int, float]:
    """ease per competition: weighted least squares on d = ease_a - ease_b, the reference at 0, a small ridge."""
    free = [l for l in leagues if l != REFERENCE]
    col = {l: i for i, l in enumerate(free)}
    X = np.zeros((len(p), len(free)))
    for k, (a, b) in enumerate(zip(p["league_id_a"], p["league_id_b"])):
        if a in col:
            X[k, col[a]] += 1.0
        if b in col:
            X[k, col[b]] -= 1.0
    w = p["w"].to_numpy()
    A = X.T @ (X * w[:, None]) + RIDGE * np.eye(len(free))
    theta = np.linalg.solve(A, X.T @ (w * p["d"].to_numpy()))
    out = {l: float(theta[col[l]]) for l in free}
    out[REFERENCE] = 0.0
    return out


def connected(p: pd.DataFrame) -> set[int]:
    """The competitions joined to the reference by shared players."""
    adj: dict[int, set[int]] = {}
    for a, b in zip(p["league_id_a"], p["league_id_b"]):
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    seen, stack = {REFERENCE}, [REFERENCE]
    while stack:
        for v in adj.get(stack.pop(), ()):
            if v not in seen:
                seen.add(v)
                stack.append(v)
    return seen


def main() -> None:
    m = monthly()
    names = m.groupby("league_id")["league"].first().to_dict()
    p = pairs(m)
    train, test = p[p["month"] < SPLIT], p[p["month"] >= SPLIT]
    placed = sorted(connected(train))
    train = train[train["league_id_a"].isin(placed) & train["league_id_b"].isin(placed)]
    ease = fit(train, placed)

    # the ladder, judged once on the pairs from July 2024 on (both competitions placed in training)
    t = test[test["league_id_a"].isin(placed) & test["league_id_b"].isin(placed)].copy()
    youth = {l for l in placed if YOUTH.search(names.get(l) or "")}
    yt = train.assign(ya=train["league_id_a"].isin(youth).astype(int), yb=train["league_id_b"].isin(youth).astype(int))
    yt = yt[yt["ya"] != yt["yb"]]
    one = float(np.average(np.where(yt["ya"] == 1, yt["d"], -yt["d"]), weights=yt["w"])) if len(yt) else 0.0
    t["pred_zero"] = 0.0
    t["pred_youth"] = (t["league_id_a"].isin(youth).astype(int) - t["league_id_b"].isin(youth).astype(int)) * one
    t["pred_bridge"] = t["league_id_a"].map(ease) - t["league_id_b"].map(ease)
    err = {k: float(np.average(np.abs(t["d"] - t[f"pred_{k}"]), weights=t["w"])) for k in ("zero", "youth", "bridge")}

    # paired bootstrap over players: the bridge's gain against the next rung down
    rng = np.random.default_rng(7)
    players = t["player_id"].unique()
    by = {k: g for k, g in t.groupby("player_id")}
    gains = []
    for _ in range(1000):
        s = pd.concat([by[x] for x in rng.choice(players, len(players))])
        e_b = np.average(np.abs(s["d"] - s["pred_bridge"]), weights=s["w"])
        e_y = np.average(np.abs(s["d"] - s["pred_youth"]), weights=s["w"])
        gains.append(e_b - e_y)
    lo, hi = np.percentile(gains, [2.5, 97.5])

    # the table itself: once the test is done, the offsets are fitted again on every month (the youth leagues'
    # ratings only start in 2024/25, after the split), with standard errors from players resampled
    test_placed = placed
    placed = sorted(connected(p))
    allp = p[p["league_id_a"].isin(placed) & p["league_id_b"].isin(placed)]
    ease = fit(allp, placed)
    youth = {l for l in placed if YOUTH.search(names.get(l) or "")}
    tp = allp["player_id"].unique()
    tby = {k: g for k, g in allp.groupby("player_id")}
    boots = []
    for _ in range(100):
        s = pd.concat([tby[x] for x in rng.choice(tp, len(tp))])
        e = fit(s, placed)
        boots.append([e.get(l, np.nan) for l in placed])
    se = np.nanstd(np.array(boots), axis=0)
    n_pairs = pd.concat([allp["league_id_a"], allp["league_id_b"]]).value_counts()
    n_players = pd.concat([allp[["player_id", "league_id_a"]].rename(columns={"league_id_a": "l"}),
                           allp[["player_id", "league_id_b"]].rename(columns={"league_id_b": "l"})]
                          ).groupby("l")["player_id"].nunique()
    table = pd.DataFrame({
        "league_id": placed,
        "league": [names.get(l, str(l)) for l in placed],
        "ease": [ease[l] for l in placed],
        "se": se,
        "pairs": [int(n_pairs.get(l, 0)) for l in placed],
        "players": [int(n_players.get(l, 0)) for l in placed],
        "youth": [l in youth for l in placed],
    }).sort_values("ease")
    table["thin"] = table["players"] < THIN
    out = LAKE / "strength"
    table.to_parquet(out / "bridge_offsets.parquet", index=False)
    unplaced = sorted(set(names) - set(placed))
    report = {
        "rows_rated": int(len(m)), "pairs_train": int(len(train)), "pairs_test": int(len(t)),
        "players_test": int(len(players)), "split": SPLIT,
        "weighted_mae_test": err, "youth_offset_one_number": one,
        "bridge_minus_youth_mae": float(np.mean(gains)), "ci95": [float(lo), float(hi)],
        "placed_in_test": len(test_placed), "placed_final": len(placed), "thin": int(table["thin"].sum()),
        "unplaced": [names.get(l, str(l)) for l in unplaced],
    }
    (out / "bridge_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    pd.set_option("display.width", 160)
    print(table.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
