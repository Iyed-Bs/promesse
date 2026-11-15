"""Promesse T3c, design 5: interplay, what two players do together, across lines.

pairs cross the lines (a full-back and his winger, rotating midfielders, a false 9 and the shadow
striker), and what they do together shows in their passes: do they play together, how often a third man unlocks them,
how they play around each other. Famous duos set the bar; the data should find them.

1. Pairs. Two outfield teammates, any lines, on the pitch together 30+ minutes in a match (StatsBomb lineups: position
   stints with their clock times). A pair is (team, A, B) over every season held; it enters with 10+ such matches.
   Its type: both players' most common position groups (CB, FB, DM, CM, W, AM, ST) and their flanks (same flank,
   opposite flanks, central). Its pool: the competition. A is the deeper position (ties: the lower id).
2. Per pair (completed open-play passes; places in the attacking team's frame, StatsBomb's 120 x 80 yards):
     links       passes between them both ways, per 90 together
     chemistry   log of links against the links expected from volume alone (A's passes x B's share of the team's
                 receptions from others, and the reverse), each +0.5
     one_twos    A to B and straight back (or B to A to B) in the same possession within 6 s, per 90
     third_man   A to C, then C to B within 4 s (or B to C to A), B receiving 10+ yards ahead of where A passed, per 90
     b_wider     possessions where both receive in the opponent's half: the share in which B receives wider than A
     b_higher    ... and higher than A
   Reported with no gate: together (matches together / matches either played 30+), flow (share of links A to B).
3. Each measure is centred on its type's mean in its pool: a full-back and his winger always link a lot; the question is
   whether this pair does more.

Gates:
  G1 per measure: each pair's matches split odd and even by date; Spearman-Brown of the type-centred values >= 0.5 with
     30+ pairs.
  G2 chemistry, one_twos, third_man belong to the pair: within each half, each player's own effect (his mean over his
     other pairs, this one left out) is taken out; the residual's split-half >= 0.5.
  G3 known duos, named before the run: each duo's type-centred chemistry in the top third of its type in its
     competition; passes if 2/3+ of the testable duos are (chance: 1/3). Testable: 10+ matches together, a type pool
     of 10+ pairs; G3 needs 6+ testable duos.
Decisions: a measure passing G1 may show pair signatures on the desk with counts; "chemistry" as the pair's own only if
G2 passes; if G3 fails, the measure does not separate the duos football remembers, and that is said.

    python gold/partners_interplay.py   (Promesse venv) -> lake/gold/partner_interplay.parquet,
                                                           partner_interplay_matches.parquet, partners_interplay_report.json
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
from itertools import combinations
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

DATA = Path(DATA_ROOT)
SB = DATA / "lake" / "statsbomb"
GOLD = DATA / "lake" / "gold"
EV = (SB / "events").as_posix() + "/**/*.parquet"
MIN_TOGETHER, MIN_MATCHES, MIN_PAIRS, MIN_POOL, MIN_DUOS, MIN_SHARED = 30, 10, 30, 10, 6, 5
ONE_TWO_S, THIRD_S, THIRD_GAIN = 6, 4, 10
END = 99 * 10000                                     # clock key of the final whistle (a stint with no end)
# club leagues only: national teams and cup runs rarely give a pair ten matches (competitions in the pools)
LEAGUES = ["La Liga", "Premier League", "Serie A", "Ligue 1", "1. Bundesliga", "FA Women's Super League", "Liga F", "NWSL",
           "Frauen Bundesliga", "Serie A Women", "Indian Super league", "Major League Soccer"]
GROUP = {"Goalkeeper": "GK", "Right Back": "FB", "Left Back": "FB", "Right Wing Back": "FB", "Left Wing Back": "FB",
         "Right Center Back": "CB", "Left Center Back": "CB", "Center Back": "CB",
         "Right Defensive Midfield": "DM", "Left Defensive Midfield": "DM", "Center Defensive Midfield": "DM",
         "Right Center Midfield": "CM", "Left Center Midfield": "CM", "Center Midfield": "CM",
         "Right Midfield": "W", "Left Midfield": "W", "Right Wing": "W", "Left Wing": "W",
         "Right Attacking Midfield": "AM", "Left Attacking Midfield": "AM", "Center Attacking Midfield": "AM",
         "Right Center Forward": "ST", "Left Center Forward": "ST", "Center Forward": "ST", "Secondary Striker": "ST"}
DEPTH = {"CB": 0, "FB": 1, "DM": 2, "CM": 3, "W": 4, "AM": 5, "ST": 6}
MEASURES = ["links", "chemistry", "one_twos", "third_man", "b_wider", "b_higher"]
PAIR_OWN = ["chemistry", "one_twos", "third_man"]
# G3, the duos named before the run (ids resolved by name from the lineups, values unseen)
DUOS = [("Barcelona", 20131, 5216, "Xavi–Iniesta"), ("Barcelona", 5503, 4324, "Messi–Dani Alves"),
        ("Barcelona", 5503, 5211, "Messi–Jordi Alba"), ("Barcelona", 5216, 5211, "Iniesta–Jordi Alba"),
        ("Barcelona", 5203, 20131, "Busquets–Xavi"), ("Barcelona", 5503, 5246, "Messi–Suárez"),
        ("Barcelona", 5503, 4320, "Messi–Neymar"), ("Arsenal", 15516, 15042, "Henry–Bergkamp"),
        ("Arsenal", 19312, 12529, "Pirès–Ashley Cole"), ("Arsenal", 15516, 19312, "Henry–Pirès"),
        ("Leicester City", 10960, 3814, "Vardy–Mahrez"), ("Tottenham Hotspur", 10955, 3094, "Kane–Dele Alli"),
        ("Arsenal", 3496, 3385, "Özil–Alexis Sánchez"), ("Napoli", 5497, 7037, "Higuaín–Insigne"),
        ("Napoli", 7037, 8876, "Insigne–Ghoulam"), ("Napoli", 7025, 7037, "Hamšík–Insigne"),
        ("Bayer Leverkusen", 10336, 32712, "Grimaldo–Frimpong"), ("Bayer Leverkusen", 3500, 40724, "Xhaka–Wirtz"),
        ("Bayer Leverkusen", 40724, 10336, "Wirtz–Grimaldo"), ("Paris Saint-Germain", 3009, 4320, "Mbappé–Neymar"),
        ("Paris Saint-Germain", 5503, 3009, "Messi–Mbappé")]


def _clock(mmss: str | None, period, end_min: float) -> tuple[int, float]:
    """a stint's 'mm:ss' and period -> (an ordering key, match-clock minutes); no time = the final whistle"""
    if mmss is None:
        return END, end_min
    m, s = mmss.split(":")
    return int(period or 1) * 10000 + int(m) * 60 + int(s), int(m) + int(s) / 60


def load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """league matches, their completed open-play passes, and each player's window on the pitch"""
    con = duckdb.connect()
    m = con.sql(f"""SELECT match_id, match_date AS date, "competition.competition_name" AS pool, "season.season_name" AS season
                    FROM '{(SB / "matches.parquet").as_posix()}' WHERE pool IN ({", ".join("'" + x.replace("'", "''") + "'" for x in LEAGUES)})""").df()
    con.register("kept", m[["match_id"]])
    ev = f"read_parquet('{EV}', hive_partitioning = true, union_by_name = true)"
    end = con.sql(f"SELECT match_id, max(minute + second / 60.0) AS end_min FROM {ev} WHERE match_id IN (SELECT match_id FROM kept) GROUP BY 1").df()
    p = con.sql(f"""
        SELECT match_id, period, "index" AS idx, period * 10000 + minute * 60 + second AS k, minute * 60 + second AS t, possession,
               "team.id" AS team_id, "player.id" AS a, "pass.recipient.id" AS b, x, "pass.end_x" AS ex, "pass.end_y" AS ey
        FROM {ev}
        WHERE match_id IN (SELECT match_id FROM kept) AND "type.name" = 'Pass' AND "pass.outcome.name" IS NULL
          AND "pass.recipient.id" IS NOT NULL AND ("pass.type.name" IS NULL OR "pass.type.name" IN ('Recovery', 'Interception'))
        ORDER BY match_id, team_id, period, idx""").df()
    lu = con.sql(f"""SELECT match_id, team_id, team, player_id, coalesce(nickname, player) AS name, positions
                     FROM '{(SB / "lineups.parquet").as_posix()}' WHERE positions IS NOT NULL AND positions <> '[]'""").df()
    lu = lu[lu.match_id.isin(m.match_id)].merge(end, on="match_id")
    rows = []
    for r in lu.itertuples(index=False):
        st = json.loads(r.positions)
        spans = [(*_clock(s["from"], s["from_period"], r.end_min), *_clock(s["to"], s["to_period"], r.end_min), s["position"]) for s in st]
        mins = [max(0.0, b_min - a_min) for _, a_min, _, b_min, _ in spans]
        pos = spans[int(np.argmax(mins))][4]                   # his position: the stint he held longest
        rows.append({"match_id": r.match_id, "team_id": r.team_id, "team": r.team, "player_id": r.player_id, "name": r.name,
                     "kf": min(s[0] for s in spans), "kt": max(s[2] for s in spans), "mf": min(s[1] for s in spans),
                     "mt": max(s[3] for s in spans), "minutes": float(sum(mins)), "group": GROUP.get(pos, "?"),
                     "side": "L" if pos.startswith("Left") else "R" if pos.startswith("Right") else "C"})
    return m, p, pd.DataFrame(rows)


def per_match(P: pd.DataFrame, S: pd.DataFrame) -> list[dict]:
    """one match, one team -> a row per pair on the pitch together 30+ minutes (lo = the lower id, hi = the higher)"""
    S = S[(S.group != "GK") & (S.group != "?")].set_index("player_id")
    a, b, k = P["a"].to_numpy(), P["b"].to_numpy(), P["k"].to_numpy()
    # the chains: consecutive passes in one possession where the receiver passes next
    nxt = P.shift(-1)
    chain = (nxt["possession"] == P["possession"]) & (nxt["period"] == P["period"]) & (nxt["a"] == P["b"])
    gap = nxt["t"] - P["t"]
    one = P[chain & (nxt["b"] == P["a"]) & (gap <= ONE_TWO_S)]
    thr = P[chain & (nxt["b"] != P["a"]) & (gap <= THIRD_S) & (nxt["ex"] >= P["x"] + THIRD_GAIN)].assign(y=nxt["b"])
    one_c = pd.Series([tuple(sorted(x)) for x in zip(one["a"], one["b"])], dtype=object).value_counts().to_dict()
    thr_c = pd.Series([tuple(sorted(x)) for x in zip(thr["a"], thr["y"].astype(int))], dtype=object).value_counts().to_dict()
    # who receives where, per possession, in the opponent's half (mean depth, mean width from the long axis)
    R = P[P["ex"] >= 60].assign(w=lambda d: (d["ey"] - 40).abs()).groupby(["possession", "b"])[["ex", "w"]].mean().reset_index()
    rel = R.merge(R, on="possession", suffixes=("_l", "_h"))
    rel = rel[rel["b_l"] < rel["b_h"]]
    rel_c = rel.assign(wider=rel["w_h"] > rel["w_l"], higher=rel["ex_h"] > rel["ex_l"]).groupby(["b_l", "b_h"])[["wider", "higher"]].agg(["sum", "count"])
    rows, cache = [], {}
    for lo, hi in combinations(sorted(S.index), 2):
        sl, sh = S.loc[lo], S.loc[hi]
        together = min(sl.mt, sh.mt) - max(sl.mf, sh.mf)
        if together < MIN_TOGETHER:
            continue
        win = (max(sl.kf, sh.kf), min(sl.kt, sh.kt))
        if win not in cache:                                  # one count table per window (a handful per match)
            m = (k >= win[0]) & (k <= win[1])
            pairs = pd.Series(list(zip(a[m], b[m])), dtype=object).value_counts().to_dict()
            cache[win] = (pairs, pd.Series(a[m]).value_counts().to_dict(), pd.Series(b[m]).value_counts().to_dict(), int(m.sum()))
        pairs, out_, in_, tot = cache[win]
        l_lh, l_hl = pairs.get((lo, hi), 0), pairs.get((hi, lo), 0)

        def expect(x, y, l_xy):  # x's passes x y's share of the receptions from others, among receivers other than x
            rest = tot - out_.get(x, 0) - in_.get(x, 0)
            return out_.get(x, 0) * (in_.get(y, 0) - l_xy) / rest if rest > 0 else 0.0
        rw = rel_c.loc[(lo, hi)] if (lo, hi) in rel_c.index else None
        rows.append({"lo": lo, "hi": hi, "minutes": together, "l_lh": l_lh, "l_hl": l_hl,
                     "e_lh": expect(lo, hi, l_lh), "e_hl": expect(hi, lo, l_hl),
                     "n_one_twos": one_c.get((lo, hi), 0), "n_third_man": thr_c.get((lo, hi), 0),
                     "shared": int(rw[("wider", "count")]) if rw is not None else 0,
                     "hi_wider": int(rw[("wider", "sum")]) if rw is not None else 0,
                     "hi_higher": int(rw[("higher", "sum")]) if rw is not None else 0,
                     "g_lo": sl.group, "g_hi": sh.group, "s_lo": sl.side, "s_hi": sh.side})
    return rows


def measures(g: pd.DataFrame, a_is_lo: pd.Series) -> pd.DataFrame:
    """summed counts -> the six measures, oriented so that A is the deeper player"""
    L, E = g["l_lh"] + g["l_hl"], g["e_lh"] + g["e_hl"]
    out = pd.DataFrame(index=g.index)
    out["links"] = 90 * L / g["minutes"]
    out["chemistry"] = np.log((L + 0.5) / (E + 0.5))
    out["one_twos"] = 90 * g["n_one_twos"] / g["minutes"]
    out["third_man"] = 90 * g["n_third_man"] / g["minutes"]
    ok = g["shared"] >= MIN_SHARED
    hw, hh = g["hi_wider"] / g["shared"].where(ok), g["hi_higher"] / g["shared"].where(ok)
    out["b_wider"] = np.where(a_is_lo, hw, 1 - hw)
    out["b_higher"] = np.where(a_is_lo, hh, 1 - hh)
    out["flow"] = np.where(a_is_lo, g["l_lh"], g["l_hl"]) / L.where(L > 0)
    return out


def split_half(x: pd.Series, y: pd.Series) -> dict:
    s = pd.concat([x, y], axis=1).dropna()
    rec = {"pairs": int(len(s)), "testable": bool(len(s) >= MIN_PAIRS)}
    if rec["testable"]:
        r = float(s.corr().iloc[0, 1])
        sb = (lambda v: 2 * v / (1 + v))
        z, se = np.arctanh(np.clip(r, -0.999, 0.999)), 1 / np.sqrt(len(s) - 3)
        lo, hi = np.tanh(z - 1.96 * se), np.tanh(z + 1.96 * se)
        rec.update(r=round(r, 3), spearman_brown=round(sb(r), 3) if r > -1 else None,
                   sb_interval=[round(sb(lo), 3) if lo > -1 else None, round(sb(hi), 3)])
    rec["pass"] = bool(rec["testable"] and rec["r"] > 0 and (rec["spearman_brown"] or 0) >= 0.5)
    return rec


def residual(v: pd.Series, pairs: pd.DataFrame) -> pd.Series:
    """the pair's value minus both players' own effects (each one's mean over his other pairs, this one left out)"""
    long = pd.concat([pairs[["team_id", "A"]].rename(columns={"A": "p"}).assign(v=v.values, i=pairs.index),
                      pairs[["team_id", "B"]].rename(columns={"B": "p"}).assign(v=v.values, i=pairs.index)]).dropna(subset=["v"])
    g = long.groupby(["team_id", "p"])["v"]
    s, n = g.transform("sum"), g.transform("count")
    long["eff"] = ((s - long["v"]) / (n - 1)).where(n > 1, 0.0)
    return v - long.groupby("i")["eff"].sum().reindex(pairs.index).fillna(0.0)


def chrono(pm: pd.DataFrame, full: pd.DataFrame) -> dict:
    """Check (exploratory, written after the gates ran): G1 and G2 again with the pair's earlier matches against its later
    ones, and G2 on the pairs whose two halves fall in different seasons (form and the moment no longer shared)."""
    key = ["team_id", "lo", "hi"]
    S = ["minutes", "l_lh", "l_hl", "e_lh", "e_hl", "n_one_twos", "n_third_man", "shared", "hi_wider", "hi_higher"]
    pm = pm.sort_values(key + ["date", "match_id"]).copy()
    pm["late"] = (pm.groupby(key).cumcount() >= pm.groupby(key)["match_id"].transform("size") / 2).astype(int)
    a_is_lo = (full["A"] == full["lo"]).values
    h = pm.groupby(key + ["late"])[S].sum().reset_index()
    halves = {i: measures(full[key].merge(h[h.late == i], on=key, how="left"), a_is_lo) for i in (0, 1)}
    tmean = full.groupby(["pool", "type"])[MEASURES].transform("mean")
    for v in MEASURES:
        for i in (0, 1):
            halves[i][v + "_c"] = halves[i][v] - tmean[v].values
    res = {v: [residual(halves[i][v + "_c"], full) for i in (0, 1)] for v in PAIR_OWN}
    seasons = pm.groupby(key + ["late"])["season"].agg(lambda s: s.mode().iloc[0]).unstack("late").reset_index()
    apart = full[key].merge(seasons, on=key, how="left")
    diff = (apart[0] != apart[1]).values
    return {"G1": {v: split_half(halves[0][v + "_c"], halves[1][v + "_c"]) for v in MEASURES},
            "G2": {v: split_half(*res[v]) for v in PAIR_OWN},
            "G2_different_seasons": {v: split_half(res[v][0][diff], res[v][1][diff]) for v in PAIR_OWN},
            "pairs_different_seasons": int(diff.sum())}


def main() -> None:
    m, p, st = load()
    print(f"league matches {len(m):,} | passes {len(p):,} | player-matches {len(st):,}")
    rows = []
    stg = {key: g for key, g in st.groupby(["match_id", "team_id"])}
    for (mid, tid), P in p.groupby(["match_id", "team_id"], sort=False):
        if (mid, tid) in stg:
            rows += [{"match_id": mid, "team_id": tid, **r} for r in per_match(P.reset_index(drop=True), stg[(mid, tid)])]
    pm = pd.DataFrame(rows).merge(m, on="match_id")
    print(f"pair-matches {len(pm):,}")
    key = ["team_id", "lo", "hi"]
    pm = pm.sort_values(key + ["date", "match_id"])
    pm["half"] = pm.groupby(key).cumcount() % 2
    n = pm.groupby(key).size().rename("matches")
    S = ["minutes", "l_lh", "l_hl", "e_lh", "e_hl", "n_one_twos", "n_third_man", "shared", "hi_wider", "hi_higher"]
    full = pm.groupby(key)[S].sum().join(n)
    full = full[full.matches >= MIN_MATCHES]
    # the pair's type: each one's most common group and side over their matches together; A is the deeper
    kept = pm.merge(full.reset_index()[key], on=key)
    for c in ("g_lo", "g_hi", "s_lo", "s_hi", "pool"):
        full[c] = kept.groupby(key)[c].agg(lambda s: s.mode().iloc[0]).reindex(full.index)
    full = full.reset_index()
    a_is_lo = full["g_lo"].map(DEPTH) < full["g_hi"].map(DEPTH)
    a_is_lo |= (full["g_lo"] == full["g_hi"])                          # same group: the lower id is A
    full["A"], full["B"] = np.where(a_is_lo, full["lo"], full["hi"]), np.where(a_is_lo, full["hi"], full["lo"])
    gA, gB = np.where(a_is_lo, full["g_lo"], full["g_hi"]), np.where(a_is_lo, full["g_hi"], full["g_lo"])
    sides = list(zip(full["s_lo"], full["s_hi"]))
    rel = ["same flank" if x == y and x != "C" else "opposite flanks" if {x, y} == {"L", "R"} else "central" for x, y in sides]
    full["type"] = [f"{x}-{y}, {r}" for x, y, r in zip(gA, gB, rel)]
    full = pd.concat([full, measures(full, a_is_lo)], axis=1)
    # together: matches together over matches either played 30+ minutes, for this team
    played = st[st.minutes >= MIN_TOGETHER].groupby(["team_id", "player_id"]).size()
    nA = [played.get((t, x), 0) for t, x in zip(full.team_id, full.A)]
    nB = [played.get((t, x), 0) for t, x in zip(full.team_id, full.B)]
    full["together"] = full["matches"] / (np.array(nA) + np.array(nB) - full["matches"]).clip(lower=1)
    # halves, oriented the same way, then everything centred on its type's mean in its pool
    h = pm.groupby(key + ["half"])[S].sum().reset_index()
    halves = {}
    for i in (0, 1):
        hi_ = full[key + ["pool", "type"]].merge(h[h.half == i], on=key, how="left")
        halves[i] = measures(hi_, a_is_lo.values)
    tmean = full.groupby(["pool", "type"])[MEASURES].transform("mean")
    for v in MEASURES:
        full[v + "_c"] = full[v] - tmean[v]
        for i in (0, 1):
            halves[i][v + "_c"] = halves[i][v] - tmean[v].values
    g1 = {v: split_half(halves[0][v + "_c"], halves[1][v + "_c"]) for v in MEASURES}
    g2 = {v: split_half(residual(halves[0][v + "_c"], full), residual(halves[1][v + "_c"], full)) for v in PAIR_OWN}
    # G3: the named duos against their type in their pool
    names = st.drop_duplicates("player_id").set_index("player_id")["name"]
    teams = st.drop_duplicates("team_id").set_index("team").to_dict()["team_id"]
    pool_n = full.groupby(["pool", "type"]).size()
    duos = []
    for team, x, y, label in DUOS:
        t = teams.get(team)
        hit = full[(full.team_id == t) & (((full.A == x) & (full.B == y)) | ((full.A == y) & (full.B == x)))]
        rec = {"duo": label, "team": team, "found": bool(len(hit))}
        if len(hit):
            r = hit.iloc[0]
            peers = full[(full.pool == r.pool) & (full.type == r.type)]
            rec.update(pool=r.pool, type=r.type, matches=int(r.matches), together=round(float(r.together), 2),
                       pool_pairs=int(pool_n[(r.pool, r.type)]), testable=bool(pool_n[(r.pool, r.type)] >= MIN_POOL),
                       **{v: (None if pd.isna(r[v]) else round(float(r[v]), 3)) for v in MEASURES + ["flow"]},
                       **{v + "_pct": (None if pd.isna(r[v]) else round(float((peers[v] <= r[v]).mean()), 2)) for v in MEASURES})
            rec["top_third"] = bool(rec["testable"] and rec["chemistry_pct"] > 2 / 3)
        duos.append(rec)
    testable = [d for d in duos if d.get("testable")]
    hits = sum(d["top_third"] for d in testable)
    g3 = {"named": len(DUOS), "found": sum(d["found"] for d in duos), "testable": len(testable), "top_third": hits,
          "share": round(hits / len(testable), 3) if testable else None, "enough": len(testable) >= MIN_DUOS}
    g3["pass"] = bool(g3["enough"] and hits / len(testable) >= 2 / 3)
    full["name_A"], full["name_B"] = full.A.map(names), full.B.map(names)
    report = {"built": pd.Timestamp.now().isoformat(timespec="seconds"), "data": "StatsBomb open data, club leagues (credit StatsBomb)",
              "matches": int(len(m)), "pair_matches": int(len(pm)), "pairs": int(len(full)),
              "pairs_by_pool": full["pool"].value_counts().to_dict(), "G1_signature": g1,
              "G1_passing": [v for v, x in g1.items() if x["pass"]], "G2_pair_own": g2,
              "G2_passing": [v for v, x in g2.items() if x["pass"]], "G3_known_duos": g3, "duos": duos}
    full.to_parquet(GOLD / "partner_interplay.parquet", index=False)
    pm.to_parquet(GOLD / "partner_interplay_matches.parquet", index=False)
    (GOLD / "partners_interplay_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    (GOLD / "partners_interplay_chrono.json").write_text(json.dumps(chrono(pm, full), indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "duos"}, indent=1, ensure_ascii=False, default=str))
    for d in duos:
        print(json.dumps(d, ensure_ascii=False))


if __name__ == "__main__":
    main()
