"""Promesse T3: roles. What a player does inside his team, in football's own words.

1. Family. Every MatchData start has a lineup slot (x across the pitch, y along it) and a formation. A classifier learns
   Transfermarkt's position for the same player in the same game (linked through gold/match_link.parquet), then names
   the family of every start, linked or not: GK, CB, FB, DM, CM, AM, W, ST. A player-season's family is the one he
   started most in (minutes-weighted).
2. Features, per player-season with 450+ minutes: per-90 rates, and shares of his team's actions while he was on the
   pitch (his long balls / the team's long balls x the fraction of the match he played). Standardised within the
   family and season, then shrunk by minutes (z * m / (m + 900)), so a short season can't look extreme.
3. Roles: each role is a written, weighted sum of those features (ROLES below), so an expert can read the definition.
   A player gets a score for every role in his family; his roles are where he scores high, never a single label.

Gate (T3): roles are stable. For player-seasons with 1,800+ minutes, scores from his odd and even matches agree
(Spearman >= 0.5 for every role), and his top role in one half is his top role in the other more often than 1.5 x
chance.

    python gold/roles.py           (Promesse venv) -> lake/gold/player_roles.parquet, roles_report.json
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
from pathlib import Path

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

DATA = Path(DATA_ROOT)
GOLD = DATA / "lake" / "gold"
PM = (DATA / "lake" / "matchdata" / "player_matches").as_posix() + "/**/*.parquet"
TM = (DATA / "transfermarkt-datasets.duckdb").as_posix()
PERSONS = (DATA / "lake" / "identity" / "persons.parquet").as_posix()
FAMILY = {"Goalkeeper": "GK", "Centre-Back": "CB", "Sweeper": "CB", "Left-Back": "FB", "Right-Back": "FB",
          "Defensive Midfield": "DM", "Central Midfield": "CM", "Attacking Midfield": "AM", "Left Winger": "W",
          "Right Winger": "W", "Left Midfield": "W", "Right Midfield": "W", "Centre-Forward": "ST", "Second Striker": "ST"}
MIN_SEASON, SHRINK_MIN, MIN_SPLIT = 450, 900, 1800

# the raw counts each player-match carries (MatchData column -> short name); "(of)" columns are attempts
COUNTS = {"Accurate passes": "pass_acc", "Accurate passes (of)": "passes", "Accurate long balls": "long_acc",
          "Accurate long balls (of)": "longs", "Accurate crosses (of)": "crosses", "Passes into final third": "final_third",
          "Chances created": "chances", "Big chances created": "big_chances", "Expected assists (xA)": "xa",
          "Expected goals (xG)": "xg", "Total shots": "shots", "Touches": "touches", "Touches in opposition box": "box",
          "Successful dribbles": "drib_succ", "Successful dribbles (of)": "dribbles", "Was fouled": "fouled",
          "Defensive actions": "def_actions", "Tackles": "tackles", "Interceptions": "interceptions",
          "Recoveries": "recoveries", "Clearances": "clearances", "Aerial duels won": "aerial_won",
          "Aerial duels won (of)": "aerials", "Duels won": "duels_won", "Saves": "saves", "Goals prevented": "prevented",
          "Acted as sweeper": "sweeper"}
SHARES = ["passes", "longs", "crosses", "chances", "shots", "xg", "box", "def_actions", "aerials", "touches"]

# the roles, written down: feature -> weight (r_ = per 90, s_ = share of the team's, q_ = a ratio)
ROLES = {
    "GK": {"Shot-stopper": {"r_prevented": 1, "r_saves": 0.5},
           "Sweeper-keeper": {"r_sweeper": 1, "s_passes": 0.7, "r_passes": 0.5, "q_long_share": -0.5}},
    "CB": {"Stopper": {"r_aerials": 1, "r_clearances": 1, "r_tackles": 0.5, "q_aerial_win": 0.5},
           "Ball-player": {"s_passes": 1, "r_final_third": 1, "q_long_acc": 0.5, "q_pass_acc": 0.5},
           "Cover": {"r_interceptions": 1, "r_recoveries": 1, "r_clearances": -0.3}},
    "FB": {"Crossing outlet": {"r_crosses": 1, "s_crosses": 0.7, "r_final_third": 0.5, "r_box": 0.5},
           "Inverted": {"s_passes": 1, "q_pass_acc": 0.5, "r_crosses": -0.7, "r_touches": 0.5},
           "Defensive": {"r_tackles": 1, "r_interceptions": 0.7, "r_duels_won": 0.5, "r_final_third": -0.3}},
    "DM": {"Anchor": {"r_tackles": 1, "r_interceptions": 1, "r_duels_won": 0.5, "r_recoveries": 0.5},
           "Deep playmaker": {"s_passes": 1, "r_longs": 0.7, "r_final_third": 0.7, "q_pass_acc": 0.5}},
    "CM": {"Box-to-box": {"r_box": 0.8, "r_def_actions": 0.8, "r_recoveries": 0.5, "r_shots": 0.4},
           "Mezzala": {"r_final_third": 0.6, "r_dribbles": 0.7, "r_box": 0.6, "r_chances": 0.5},
           "Organiser": {"s_passes": 1, "q_pass_acc": 0.8, "r_passes": 0.5}},
    "AM": {"Creator": {"r_chances": 1, "r_xa": 1, "r_big_chances": 0.5},
           "Second striker": {"r_shots": 1, "r_xg": 1, "r_box": 0.7}},
    "W": {"Wide winger": {"r_crosses": 1, "r_final_third": 0.5, "s_crosses": 0.5},
          "Inside forward": {"r_shots": 1, "r_xg": 0.8, "r_box": 0.6, "r_crosses": -0.4},
          "Dribbler": {"r_dribbles": 1, "r_fouled": 0.6, "r_drib_succ": 0.5}},
    "ST": {"Target": {"r_aerials": 1, "r_duels_won": 0.6, "r_touches": 0.4, "q_aerial_win": 0.5},
           "Poacher": {"q_xg_per_touch": 1, "s_box": 0.8, "r_shots": 0.5, "r_touches": -0.5},
           "Deep-lying forward": {"r_chances": 0.8, "r_touches": 0.7, "r_final_third": 0.5, "r_box": -0.3},
           "Pressing forward": {"r_def_actions": 1, "r_recoveries": 0.8, "r_tackles": 0.5}},
}


def rows(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    sel = ", ".join(f'coalesce("{k}", 0) as "{v}"' for k, v in COUNTS.items())
    d = con.execute(f"""
      select match_id, league_id::bigint league_id, season, try_cast(left(date, 10) as date) date, team_id::bigint team_id,
             team, player_id::varchar fid, name, role, lower(coalesce(goalkeeper, '')) = 'true' gk, formation,
             try_cast(x as double) x, try_cast(y as double) y, "Minutes played" as "minutes", {sel}
      from read_parquet('{PM}', union_by_name=true)
      where "Minutes played" > 0 and "Accurate passes (of)" is not null and team_id is not null""").df()
    team = d.groupby(["match_id", "team_id"])[SHARES].transform("sum")
    for c in SHARES:
        d[f"team_{c}"] = team[c]
    return d


def families(con: duckdb.DuckDBPyConnection, d: pd.DataFrame) -> tuple[pd.Series, dict]:
    """Learn Transfermarkt's lineup position from MatchData's slot; name every start's family."""
    lab = con.execute(f"""
      select l.match_id, l.team_id, ids.fid, gl.position
      from read_parquet('{(GOLD / 'match_link.parquet').as_posix()}') l
      join tm.game_lineups gl on gl.game_id::bigint = l.game_id and gl.club_id::bigint = l.club_id and gl.type = 'starting_lineup'
      join (select try_cast(tm_id as bigint) tm_id, matchdata_id::varchar fid from read_parquet('{PERSONS}')
            where tm_id is not null and matchdata_id is not null) ids on ids.tm_id = gl.player_id::bigint""").df()
    lab["family"] = lab.position.map(FAMILY)
    st = d[(d.role == "starter") & d.x.notna()].copy()
    f = st.formation.fillna("")
    st["back3"] = f.str.match(r"^[35]-").astype(int)
    st["n_att"] = pd.to_numeric(f.str.split("-").str[-1], errors="coerce")
    st["n_def"] = pd.to_numeric(f.str.split("-").str[0], errors="coerce")
    st["xc"] = (st.x - 0.5).abs()
    st["gkf"] = st.gk.astype(int)
    feats = ["x", "y", "xc", "back3", "n_att", "n_def", "gkf"]
    tr = st.merge(lab[["match_id", "team_id", "fid", "family"]].dropna(), on=["match_id", "team_id", "fid"])
    classes = sorted(tr.family.unique())
    cut = tr.date < pd.Timestamp("2024-07-01")
    clf = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31, random_state=7, verbose=-1)
    clf.fit(tr.loc[cut, feats], tr.loc[cut, "family"])
    acc = float((clf.predict(tr.loc[~cut, feats]) == tr.loc[~cut, "family"]).mean())
    clf.fit(tr[feats], tr.family)
    st["family"] = clf.predict(st[feats])
    return st.set_index(["match_id", "team_id", "fid"]).family, {"labelled_starts": int(len(tr)), "classes": classes,
                                                                    "accuracy_on_2024_on": round(acc, 3)}


def main() -> None:
    con = duckdb.connect()
    con.execute(f"attach '{TM}' as tm (read_only)")
    d = rows(con)
    fam, finfo = families(con, d)
    d = d.join(fam.rename("family"), on=["match_id", "team_id", "fid"])
    # a player-season's family: the one he started most in, minutes-weighted
    key = ["fid", "team_id", "league_id", "season"]
    fw = d.dropna(subset=["family"]).groupby(key + ["family"]).minutes.sum().reset_index()
    fam_ps = fw.sort_values("minutes").groupby(key).tail(1).set_index(key).family

    def build(part: pd.DataFrame) -> pd.DataFrame:
        g = part.groupby(key)
        s = g[list(COUNTS.values())].sum()
        s["minutes"] = g.minutes.sum()
        frac = part.minutes / 90.0
        for c in SHARES:
            part = part.assign(**{f"_t_{c}": part[f"team_{c}"] * frac})
        tsum = part.groupby(key)[[f"_t_{c}" for c in SHARES]].sum()
        out = pd.DataFrame(index=s.index)
        for v in COUNTS.values():
            out[f"r_{v}"] = s[v] / s.minutes * 90
        for c in SHARES:
            out[f"s_{c}"] = s[c] / tsum[f"_t_{c}"].replace(0, np.nan)
        out["q_pass_acc"] = s.pass_acc / s.passes.replace(0, np.nan)
        out["q_long_acc"] = s.long_acc / s.longs.replace(0, np.nan)
        out["q_long_share"] = s.longs / s.passes.replace(0, np.nan)
        out["q_aerial_win"] = s.aerial_won / s.aerials.replace(0, np.nan)
        out["q_xg_per_touch"] = s.xg / s.touches.replace(0, np.nan)
        out["minutes"] = s.minutes
        return out.join(fam_ps, how="inner")

    def score(f: pd.DataFrame) -> pd.DataFrame:
        f = f[f.minutes >= MIN_SEASON].copy()
        cols = [c for c in f.columns if c[:2] in ("r_", "s_", "q_")]
        grp = f.groupby(["family", f.index.get_level_values("season")])[cols]
        z = (f[cols] - grp.transform("mean")) / grp.transform("std").replace(0, np.nan)
        z = z.clip(-4, 4).fillna(0).mul(f.minutes / (f.minutes + SHRINK_MIN), axis=0)
        out = f[["family", "minutes"]].copy()
        for fam_name, roles in ROLES.items():
            m = out.family == fam_name
            for role, w in roles.items():
                out.loc[m, role] = sum(z.loc[m, c] * wt for c, wt in w.items()) / sum(abs(v) for v in w.values())
        return out

    full = score(build(d))
    # percentiles within family and season, then the top role
    seasons = full.index.get_level_values("season")
    for fam_name, roles in ROLES.items():
        m = full.family == fam_name
        for role in roles:
            full.loc[m, f"pct_{role}"] = full.loc[m, role].groupby(seasons[m]).rank(pct=True).round(3)
        full.loc[m, "top_role"] = full.loc[m, list(roles)].idxmax(axis=1)
    full = full.reset_index()
    full["tm_id"] = full.fid.map(con.execute(f"select matchdata_id::varchar fid, try_cast(tm_id as bigint) tm_id from read_parquet('{PERSONS}') "
                                              "where matchdata_id is not null and tm_id is not null").df().drop_duplicates("fid").set_index("fid").tm_id)
    names = d.groupby(key).agg(name=("name", "first"), team=("team", "first")).reset_index()
    full = full.merge(names, on=key, how="left")
    full.to_parquet(GOLD / "player_roles.parquet", index=False)

    # the gate: odd vs even matches, for player-seasons of 1,800+ minutes
    d = d.sort_values("date")
    d["half"] = d.groupby(key).cumcount() % 2
    big = full[full.minutes >= MIN_SPLIT].set_index(key).index
    sub = d.set_index(key).loc[d.set_index(key).index.isin(big)].reset_index()
    a, b = score(build(sub[sub.half == 0])), score(build(sub[sub.half == 1]))
    both = a.join(b, lsuffix="_a", rsuffix="_b", how="inner")
    stab, agree = {}, {}
    for fam_name, roles in ROLES.items():
        m = (both.family_a == fam_name) & (both.family_b == fam_name)
        if m.sum() < 30:
            continue
        for role in roles:
            stab[f"{fam_name}: {role}"] = round(float(spearmanr(both.loc[m, f"{role}_a"], both.loc[m, f"{role}_b"]).statistic), 3)
        ta = both.loc[m, [f"{r}_a" for r in roles]].to_numpy().argmax(1)
        tb = both.loc[m, [f"{r}_b" for r in roles]].to_numpy().argmax(1)
        agree[fam_name] = {"agree": round(float((ta == tb).mean()), 3), "chance": round(1 / len(roles), 3), "n": int(m.sum())}
    passed = all(v >= 0.5 for v in stab.values()) and all(v["agree"] >= 1.5 * v["chance"] for v in agree.values())
    report = {"family_classifier": finfo, "player_seasons": int(len(full)), "by_family": full.family.value_counts().to_dict(),
              "split_half_spearman": stab, "top_role_agreement": agree,
              "gate_t3": {"rule": "every role's odd/even Spearman >= 0.5 and top-role agreement >= 1.5 x chance (1,800+ minutes)",
                          "passed": bool(passed)}, "roles": ROLES}
    (GOLD / "roles_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("family_classifier", "player_seasons", "by_family", "gate_t3")}, indent=1))
    for k, v in stab.items():
        print(f"  {k:32s} {v:+.3f}")
    print("top-role agreement:", agree)


if __name__ == "__main__":
    main()
