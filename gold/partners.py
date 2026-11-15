"""Promesse T3c: partners. How a player's game changes with who plays beside him.

"Pedri by partner is a single example ... you can find millions of these combinations and how they
change how players function". This is the first engine for it, on lineups and match stats only (no tracking).

1. Beside him. Every MatchData start has a lineup slot (x across the pitch, y along it). Starters with 60+ minutes are cut
   into lines (same y, the formation's rows: a back line, a pivot, a line of three behind the striker...), and in a line
   his partners are his neighbours on either side (sorted by x). A double pivot's two players are each other's partner;
   a back three's middle centre-back has two.
2. His function, per match: per-90 rates of what he does (touches, accurate passes, passes into the final third,
   chances created, xA, xG, shots, touches in the box, dribbles, defensive actions, recoveries, accurate long balls,
   crosses). Each rate is adjusted for the match (home or away; the opponent's strength, its season xG difference per
   match), with one slope per line and rate pooled over every start, then centred on his own team-season-line mean, so
   a comparison is always him against himself in the same team, season and line.
3. Pair effects. For a player F and a partner P (6+ starts beside him and 6+ starts in the same team-season-line
   without him): the difference of F's adjusted means, with P beside him minus without, in units of F's own match-to-
   match spread (a standardised mean difference d), its standard error, and the empirical-Bayes shrunk d (shrunk to
   zero by how noisy it is against how much pair effects really vary, per rate).
4. Patterns. The same contrast by the partner's role (gold/player_roles.parquet: Anchor, Deep playmaker, Box-to-box,
   Mezzala, Organiser, Stopper, Ball-player...): for F, his starts beside a partner of role A against his starts beside a
   partner of role B (5+ each); pooled over every F of one family and role. "A mezzala beside a deep playmaker rather
   than an anchor: touches in the box +0.2 SD" is the kind of sentence this produces, with its interval and its count.

Gates (written before the first run,; results recorded whatever they say):
  G1 pair effects are a property of the pair, not noise: for pairs with 10+ starts on each side, split each side's
     starts into odd and even (by date); the d from the odd halves and from the even halves agree across pairs. A rate's
     pair effects may reach the desk if its split-half reliability (Spearman-Brown) >= 0.5.
  G2 patterns replicate: focal players split in two at random (seeded); a pattern (family, role, partner A vs B, rate)
     with 15+ players in each half keeps its sign in both halves, and the pattern means of the two halves correlate
     (Pearson >= 0.5 across patterns). Patterns may reach the desk only if G2 passes; each with its n and interval.
  G3 balance: with and without starts should face the same football. The mean absolute difference in home share and
     in opponent strength between the two sides is reported; the adjustment in step 2 is there for what remains.
What it cannot see (said on the page): in-match rotations, who covered whom, off-ball runs; tracking would add them.

    python gold/partners.py      (Promesse venv) -> lake/gold/partner_effects.parquet, partner_patterns.parquet,
                                                    partners_report.json
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
MIN_MINUTES, MIN_SIDE, MIN_SPLIT, MIN_ROLE_SIDE, MIN_HALF = 60, 6, 10, 5, 15
SEED = 20261031

# the rates of his function (MatchData column -> short name), all per 90 (which rates count as "his function")
RATES = {"Touches": "touches", "Accurate passes": "passes", "Passes into final third": "final_third",
         "Chances created": "chances", "Expected assists (xA)": "xa", "Expected goals (xG)": "xg", "Total shots": "shots",
         "Touches in opposition box": "box", "Successful dribbles": "dribbles", "Defensive actions": "def_actions",
         "Recoveries": "recoveries", "Accurate long balls": "long_balls", "Accurate crosses (of)": "crosses"}
LINE_NAME = [(0.35, "back line"), (0.60, "midfield"), (0.80, "attacking midfield"), (1.01, "forwards")]


def line_of(y: float) -> str:
    return next(name for top, name in LINE_NAME if y < top)


def load() -> pd.DataFrame:
    """Starters with 60+ minutes and a lineup slot, their per-90 rates, the match's home flag and opponent strength."""
    con = duckdb.connect()
    cols = ", ".join(f'"{k}" AS {v}' for k, v in RATES.items())
    df = con.sql(f"""
        SELECT match_id, season, date, team_id, team, player_id, name, home, TRY_CAST(x AS DOUBLE) AS x,
               TRY_CAST(y AS DOUBLE) AS y, "Minutes played" AS minutes, {cols}
        FROM read_parquet('{PM}', hive_partitioning = true, union_by_name = true)
        WHERE role = 'starter' AND "Minutes played" >= {MIN_MINUTES} AND TRY_CAST(y AS DOUBLE) > 0.2
    """).df()
    # opponent strength: the opponent's season xG difference per match (team_matches carries both sides' xG)
    tm = con.sql(f"""
        WITH m AS (SELECT a.match_id, a.season, a.team_id, a.opp_id, a.xg AS xg_for, b.xg AS xg_against
                   FROM '{(GOLD / "team_matches.parquet").as_posix()}' a
                   JOIN '{(GOLD / "team_matches.parquet").as_posix()}' b ON a.match_id = b.match_id AND b.team_id = a.opp_id),
             s AS (SELECT team_id, season, avg(xg_for - xg_against) AS xgd FROM m GROUP BY ALL)
        SELECT m.match_id, m.team_id, s.xgd AS opp_strength FROM m JOIN s ON s.team_id = m.opp_id AND s.season = m.season
    """).df()
    tm["match_id"] = tm["match_id"].astype(str)
    df["match_id"] = df["match_id"].astype(str)
    df = df.merge(tm, on=["match_id", "team_id"], how="left")
    df["opp_strength"] = df["opp_strength"].fillna(0.0)
    df["home"] = df["home"].astype(float).fillna(0.5)
    for v in RATES.values():
        df[v] = df[v].astype(float).fillna(0.0) * 90.0 / df["minutes"].clip(lower=MIN_MINUTES)
    df["line"] = [line_of(y) for y in df["y"]]
    df["yl"] = df["y"].round(2)
    return df


def neighbours(df: pd.DataFrame) -> pd.DataFrame:
    """(match, team, player) -> partner: his neighbours on either side in his line."""
    d = df.sort_values(["match_id", "team_id", "yl", "x"])[["match_id", "team_id", "yl", "player_id"]].copy()
    g = d.groupby(["match_id", "team_id", "yl"])
    out = []
    for shift in (1, -1):
        nb = g["player_id"].shift(shift)
        e = d.assign(partner_id=nb).dropna(subset=["partner_id"])
        out.append(e[["match_id", "team_id", "player_id", "partner_id"]])
    pairs = pd.concat(out, ignore_index=True)
    pairs["partner_id"] = pairs["partner_id"].astype(df["player_id"].dtype)
    return pairs


def adjust(df: pd.DataFrame) -> pd.DataFrame:
    """Each rate: minus home and opponent effects (one slope per line and rate, pooled), then centred on his own
    team-season-line mean; scaled by his own match-to-match spread there."""
    key = ["player_id", "team_id", "season", "line"]
    for v in RATES.values():
        for line, sub in df.groupby("line"):
            c = sub[v] - sub.groupby(key)[v].transform("mean")
            X = np.column_stack([sub["home"] - sub.groupby(key)["home"].transform("mean"),
                                 sub["opp_strength"] - sub.groupby(key)["opp_strength"].transform("mean")])
            beta, *_ = np.linalg.lstsq(X, c.to_numpy(), rcond=None)
            df.loc[sub.index, v + "_adj"] = sub[v] - X @ beta
        grp = df.groupby(key)[v + "_adj"]
        df[v + "_c"] = df[v + "_adj"] - grp.transform("mean")
        df[v + "_sd"] = grp.transform("std")
    return df


def smd(a: np.ndarray, b: np.ndarray, sd: float) -> tuple[float, float]:
    """standardised mean difference of a against b in units of sd, and its standard error"""
    if sd is None or not np.isfinite(sd) or sd <= 1e-9:
        return np.nan, np.nan
    d = (a.mean() - b.mean()) / sd
    se = np.sqrt(1 / len(a) + 1 / len(b) + d * d / (2 * (len(a) + len(b))))
    return d, se


def pair_effects(df: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    rates = list(RATES.values())
    beside = pairs.merge(df[["match_id", "team_id", "player_id", "season", "line", "date"]], on=["match_id", "team_id", "player_id"])
    cnt = beside.groupby(["player_id", "team_id", "season", "line", "partner_id"]).size().rename("n_with").reset_index()
    cnt = cnt[cnt.n_with >= MIN_SIDE]
    starts = df.groupby(["player_id", "team_id", "season", "line"]).size().rename("n_all").reset_index()
    cnt = cnt.merge(starts, on=["player_id", "team_id", "season", "line"])
    cnt = cnt[cnt.n_all - cnt.n_with >= MIN_SIDE]
    rows = []
    sub = df.set_index(["player_id", "team_id", "season", "line"]).sort_index()
    bset = beside.set_index(["player_id", "team_id", "season", "line", "partner_id"])["match_id"].sort_index()
    for r in cnt.itertuples(index=False):
        k = (r.player_id, r.team_id, r.season, r.line)
        own = sub.loc[[k]].sort_values("date")
        with_ids = set(bset.loc[[(*k, r.partner_id)]].to_numpy())
        w = own["match_id"].isin(with_ids).to_numpy()
        rec = {"player_id": r.player_id, "team_id": r.team_id, "season": r.season, "line": r.line, "partner_id": r.partner_id,
               "n_with": int(w.sum()), "n_without": int((~w).sum()),
               "d_home": float(own["home"][w].mean() - own["home"][~w].mean()),
               "d_opp": float(own["opp_strength"][w].mean() - own["opp_strength"][~w].mean())}
        odd = (np.arange(len(own)) % 2) == 0
        for v in rates:
            c, sd = own[v + "_c"].to_numpy(), own[v + "_sd"].iloc[0]
            rec[v], rec[v + "_se"] = smd(c[w], c[~w], sd)
            if rec["n_with"] >= MIN_SPLIT and rec["n_without"] >= MIN_SPLIT:
                rec[v + "_odd"] = smd(c[w & odd], c[~w & odd], sd)[0]
                rec[v + "_even"] = smd(c[w & ~odd], c[~w & ~odd], sd)[0]
        rows.append(rec)
    out = pd.DataFrame(rows)
    # empirical Bayes, per rate: tau^2 = how much pair effects really vary (variance of d minus its noise)
    for v in rates:
        d, se = out[v], out[v + "_se"]
        tau2 = max(0.0, float(np.nanvar(d) - np.nanmean(se ** 2)))
        out[v + "_shrunk"] = d * tau2 / (tau2 + se ** 2)
        out.attrs[v + "_tau"] = float(np.sqrt(tau2))
    return out


def role_patterns(df: pd.DataFrame, pairs: pd.DataFrame, roles: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """F's starts beside a partner of role A against beside role B, pooled over every F of one family and role."""
    rates = list(RATES.values())
    r = roles[["fid", "team_id", "season", "family", "top_role"]].dropna().copy()
    r["fid"] = r["fid"].astype(str)
    pr = pairs.copy()
    pr["pid"] = pr["partner_id"].astype(str)
    meta = df[["match_id", "team_id", "player_id", "season", "line", "date"]].copy()
    pr = pr.merge(meta, on=["match_id", "team_id", "player_id"])
    pr = pr.merge(r.rename(columns={"fid": "pid", "top_role": "partner_role", "family": "partner_family"}), on=["pid", "team_id", "season"])
    # one partner role per start: if his two neighbours differ, the start is left out (it compares nothing cleanly)
    one = pr.groupby(["match_id", "team_id", "player_id"])["partner_role"].agg(lambda s: s.iloc[0] if s.nunique() == 1 else None).dropna()
    one = one.rename("partner_role").reset_index()
    x = df.merge(one, on=["match_id", "team_id", "player_id"])
    x["fid"] = x["player_id"].astype(str)
    x = x.merge(r.rename(columns={"top_role": "role"}), on=["fid", "team_id", "season"])
    rows = []
    for (pid, tid, season, line), own in x.groupby(["player_id", "team_id", "season", "line"]):
        roles_here = own["partner_role"].value_counts()
        ok = roles_here[roles_here >= MIN_ROLE_SIDE].index.tolist()
        for i in range(len(ok)):
            for j in range(i + 1, len(ok)):
                a, b = sorted((ok[i], ok[j]))
                ia, ib = (own["partner_role"] == a).to_numpy(), (own["partner_role"] == b).to_numpy()
                rec = {"player_id": pid, "family": own["family"].iloc[0], "role": own["role"].iloc[0], "line": line,
                       "role_a": a, "role_b": b, "n_a": int(ia.sum()), "n_b": int(ib.sum())}
                for v in rates:
                    rec[v] = smd(own[v + "_c"].to_numpy()[ib], own[v + "_c"].to_numpy()[ia], own[v + "_sd"].iloc[0])[0]
                rows.append(rec)
    per = pd.DataFrame(rows)
    if per.empty:
        return per, {"patterns": 0}
    # pooled per (family, role, A vs B, rate): mean over focal players, its standard error, a random split for G2
    rng = np.random.default_rng(SEED)
    players = per["player_id"].unique()
    half = dict(zip(players, rng.integers(0, 2, len(players))))
    per["half"] = per["player_id"].map(half)
    long = per.melt(id_vars=["player_id", "family", "role", "line", "role_a", "role_b", "n_a", "n_b", "half"], value_vars=rates,
                    var_name="rate", value_name="d").dropna(subset=["d"])
    key = ["family", "role", "role_a", "role_b", "rate"]
    pooled = long.groupby(key)["d"].agg(n="count", mean="mean", sd="std").reset_index()
    pooled["se"] = pooled["sd"] / np.sqrt(pooled["n"])
    pooled["lo"], pooled["hi"] = pooled["mean"] - 1.96 * pooled["se"], pooled["mean"] + 1.96 * pooled["se"]
    halves = long.groupby(key + ["half"])["d"].agg(["count", "mean"]).unstack("half")
    halves.columns = [f"{a}_{b}" for a, b in halves.columns]
    halves = halves.reset_index()
    both = halves[(halves.get("count_0", 0) >= MIN_HALF) & (halves.get("count_1", 0) >= MIN_HALF)]
    g2 = {"patterns_testable": int(len(both))}
    if len(both) >= 10:
        g2["corr_halves"] = float(np.corrcoef(both["mean_0"], both["mean_1"])[0, 1])
        g2["same_sign"] = float((np.sign(both["mean_0"]) == np.sign(both["mean_1"])).mean())
    g2["pass"] = bool(g2.get("corr_halves", 0) >= 0.5)
    pooled = pooled.merge(halves, on=key, how="left")
    return pooled, g2


def main() -> None:
    df = load()
    print(f"starts {len(df):,} | players {df.player_id.nunique():,} | matches {df.match_id.nunique():,}")
    pairs = neighbours(df)
    df = adjust(df)
    eff = pair_effects(df, pairs)
    rates = list(RATES.values())
    names = df.drop_duplicates("player_id").set_index("player_id")["name"]
    teams = df.drop_duplicates("team_id").set_index("team_id")["team"]
    eff["name"], eff["partner"], eff["team"] = eff.player_id.map(names), eff.partner_id.map(names), eff.team_id.map(teams)
    # G1: split-half reliability per rate, pairs with MIN_SPLIT+ starts on each side
    g1 = {}
    for v in rates:
        if v + "_odd" not in eff:
            continue
        s = eff[[v + "_odd", v + "_even"]].dropna()
        if len(s) >= 30:
            r = float(s.corr().iloc[0, 1])
            g1[v] = {"pairs": int(len(s)), "r": round(r, 3), "spearman_brown": round(2 * r / (1 + r), 3) if r > -1 else None,
                     "pass": bool(r > 0 and 2 * r / (1 + r) >= 0.5), "tau": round(eff.attrs.get(v + "_tau", np.nan), 3)}
    roles = pd.read_parquet(GOLD / "player_roles.parquet")
    pooled, g2 = role_patterns(df, pairs, roles)
    g3 = {"pairs": int(len(eff)), "mean_abs_home_diff": round(float(eff["d_home"].abs().mean()), 3),
          "mean_abs_opp_strength_diff": round(float(eff["d_opp"].abs().mean()), 3),
          "opp_strength_sd_between_matches": round(float(df["opp_strength"].std()), 3)}
    # the example: Pedri, by partner
    ped = eff[(eff["name"] == "Pedri") & (eff["team"] == "Barcelona")]
    example = [{"season": r.season, "line": r.line, "partner": r.partner, "n_with": r.n_with, "n_without": r.n_without,
                **{v: round(float(getattr(r, v + "_shrunk")), 2) for v in rates if np.isfinite(getattr(r, v + "_shrunk"))}}
               for r in ped.sort_values(["season", "n_with"], ascending=[True, False]).itertuples()]
    report = {"built": pd.Timestamp.now().isoformat(timespec="seconds"), "starts": int(len(df)),
              "players": int(df.player_id.nunique()), "matches": int(df.match_id.nunique()),
              "neighbour_links": int(len(pairs)), "pairs": int(len(eff)),
              "pairs_split_testable": int(eff[[c for c in eff.columns if c.endswith("_odd")]].notna().any(axis=1).sum()),
              "G1_pair_reliability": g1, "G1_rates_passing": [v for v, x in g1.items() if x["pass"]],
              "G2_patterns": g2, "G3_balance": g3, "pedri": example}
    keep = ["player_id", "name", "team_id", "team", "season", "line", "partner_id", "partner", "n_with", "n_without", "d_home", "d_opp"]
    keep += [c for v in rates for c in (v, v + "_se", v + "_shrunk")]
    eff[keep].to_parquet(GOLD / "partner_effects.parquet", index=False)
    pooled.to_parquet(GOLD / "partner_patterns.parquet", index=False)
    (GOLD / "partners_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "pedri"}, indent=1, ensure_ascii=False))
    print("Pedri:", json.dumps(example[:6], ensure_ascii=False))


if __name__ == "__main__":
    main()
