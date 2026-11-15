"""Promesse: attributes from evidence, the abstract ones included ("skills, abilities, character, style
of play, attributes, even the abstract ones like vision, field of view, concentration").

An attribute is a written composite of match indicators, read the way T4 reads a skill: within his family, net of his
team's game model and his league (ridge), each indicator scaled to its spread, averaged, shrunk by minutes, and shown
only if a player's odd matches predict his even ones (Spearman >= 0.5, player-seasons of 1,800+ minutes). What each
one can and can't see is written beside it, and goes on the desk with it.

  vision         xA, chances and passes into the final third, each per pass he plays: what his passing finds for its
                 volume. What he saw before he passed needs video.
  composure      dispossessed per touch: he keeps the ball when it's on him.
  concentration  lapses per 90: errors leading to a goal, penalties conceded, own goals.
  discipline     fouls committed per 90 (cards are not in these match data).
  consistency    how little his match-by-match output swings (matches of 60+ minutes; output = his family's T4 skills
                 that passed, per match, standardised within his family, league and season).
  big games      his output against the top quarter of his league (season expected-goal difference) minus his output
                 against the rest.
Not readable from match totals, said so on the desk: field of view and scanning, decision speed; pace and work rate
exist only where tracking is published (Premier League and Champions League, 2024/25 on).

As first written the composites also held big chances per pass (vision), errors leading to a goal per touch
(composure) and penalties conceded per 90 (discipline): vision 0.563, composure 0.388, discipline 0.395. Read one by
one, the rare events don't repeat (big chances 0.24, penalties 0.35) or only seem to: errors leading to a goal score
0.51 because a zero count's residual is the system model's prediction, which is the same in both halves. Rare events
are therefore left out of season-level attributes (decided after seeing those results, and said so here); concentration,
built only from them, can't be read from a season and stays hidden.

    python gold/attributes.py      (Promesse venv) -> lake/gold/player_attributes.parquet, attributes_report.json
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roles  # noqa: E402
import signature  # noqa: E402

GOLD = Path((DATA_ROOT + "/lake/gold"))
KEY = signature.KEY
MIN_SEASON, MIN_SPLIT, GATE = 900, 1800, 0.5
KS = signature.KS
EXTRA = {"Dispossessed": "dispossessed", "Error led to goal": "err_goal", "Fouls committed": "fouls",
         "Conceded penalty": "pen_conceded", "Own goal": "own_goal", "Corners": "corners"}


def per(a: pd.Series, b: pd.Series) -> pd.Series:
    return a / b.replace(0, np.nan)


# attribute -> (label, what it reads, indicators: functions of a player's summed counts; higher = more of it)
ATTRS = {
    "vision": ("Vision", "what his passing finds for its volume (xA, chances, final-third passes per pass), beyond set-piece duty", [
        lambda s: per(s.xa, s.passes), lambda s: per(s.chances, s.passes), lambda s: per(s.final_third, s.passes)]),
    "composure": ("Composure", "keeps the ball when it's on him: how rarely he's dispossessed per touch, for how often he takes players on", [
        lambda s: -per(s.dispossessed, s.touches)]),
    "concentration": ("Concentration", "lapses per 90: errors leading to a goal, penalties conceded, own goals", [
        lambda s: -per(s.err_goal + s.pen_conceded + s.own_goal, s.minutes) * 90]),
    "discipline": ("Discipline", "how rarely he fouls, per 90 (cards aren't in these data)", [
        lambda s: -per(s.fouls, s.minutes) * 90]),
}
# read net of these too (found on the first sanity read,): set-piece duty fills chances and xA (the vision
# leaders were corner takers and crossing full-backs), and a dribbler loses the ball more by the nature of his game
COVARIATES = {
    "vision": [lambda s: per(s.corners, s.minutes) * 90],
    "composure": [lambda s: per(s.dribbles, s.touches)],
}
MATCH_ATTRS = {
    "consistency": ("Consistency", "how little his match-by-match output swings (matches of 60+ minutes)"),
    "big_games": ("Big games", "his output against the top quarter of his league, minus against the rest"),
}


def load(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    d = roles.rows(con)
    sel = ", ".join(f'coalesce("{k}", 0) as "{v}"' for k, v in EXTRA.items())
    extra = con.execute(f"""select match_id, player_id::varchar fid, {sel} from read_parquet('{roles.PM}', union_by_name=true)
                            where "Minutes played" > 0 and "Accurate passes (of)" is not null and team_id is not null""").df()
    return d.merge(extra.drop_duplicates(["match_id", "fid"]), on=["match_id", "fid"], how="left")


def summed(part: pd.DataFrame) -> pd.DataFrame:
    cols = list(roles.COUNTS.values()) + list(EXTRA.values()) + ["minutes"]
    s = part.groupby(KEY)[cols].sum().reset_index()
    s["league_id"] = s.league_id.astype("int64")
    return s


def read_rates(full: pd.DataFrame, halves: dict, dims: list, leagues: list) -> tuple[pd.DataFrame, dict]:
    """The T4 reading for each composite attribute: residual per indicator, averaged, shrunk, gated on the halves."""
    report, out = {}, pd.DataFrame(index=full.index)
    for key, (label, what, inds) in ATTRS.items():
        covs = COVARIATES.get(key, [])

        def X_of(df: pd.DataFrame) -> np.ndarray:
            base = signature.design(df, dims, leagues)
            if not covs:
                return base
            return np.hstack([base, np.column_stack([fn(df).fillna(0).to_numpy() for fn in covs])])
        comp_full, comp0, comp1, mins0 = [], [], [], []
        for fn in inds:
            full["_x"] = fn(full)
            for h in (0, 1):
                halves[h]["_x"] = fn(halves[h])
            res_full = pd.Series(np.nan, index=full.index)
            r0s, r1s = pd.Series(np.nan, index=halves[0].index), pd.Series(np.nan, index=halves[1].index)
            for fam_name, part in full.groupby("family"):
                ok = part._x.notna() & np.isfinite(part._x)
                if ok.sum() < 80:
                    continue
                X = X_of(part[ok])
                model = Ridge(alpha=5.0).fit(X, part.loc[ok, "_x"])
                sd = float(np.nanstd(part.loc[ok, "_x"] - model.predict(X))) or 1.0
                res_full.loc[part.index[ok]] = (part.loc[ok, "_x"] - model.predict(X)) / sd
                for h, rs in ((0, r0s), (1, r1s)):
                    hp = halves[h][(halves[h].family == fam_name) & halves[h]._x.notna() & np.isfinite(halves[h]._x)]
                    if len(hp):
                        rs.loc[hp.index] = (hp._x - model.predict(X_of(hp))) / sd
            comp_full.append(res_full)
            comp0.append(r0s)
            comp1.append(r1s)
        full[f"raw_{key}"] = pd.concat(comp_full, axis=1).mean(axis=1)
        h0 = halves[0].assign(c=pd.concat(comp0, axis=1).mean(axis=1)).set_index(KEY)
        h1 = halves[1].assign(c=pd.concat(comp1, axis=1).mean(axis=1)).set_index(KEY)
        both = h0[["c", "minutes"]].join(h1[["c"]], lsuffix="_0", rsuffix="_1", how="inner").dropna()
        r0, r1, m0 = both.c_0.to_numpy(), both.c_1.to_numpy(), both.minutes.to_numpy()
        best = max(KS, key=lambda k: -np.mean((r0 * m0 / (m0 + k) - r1) ** 2))
        rho = float(spearmanr(r0, r1).statistic)
        report[key] = {"label": label, "reads": what, "k_minutes": best, "split_half_spearman": round(rho, 3),
                       "pairs": int(len(both)), "passed": rho >= GATE}
        out[key] = full[f"raw_{key}"] * full.minutes / (full.minutes + best)
    full.drop(columns=["_x"], inplace=True)
    return out, report


def match_attrs(d: pd.DataFrame, fam: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Consistency and big games, from a per-match output index."""
    shown = [s for s, r in json.loads((GOLD / "skills_report.json").read_text(encoding="utf-8"))["by_skill"].items() if r.get("passed")]
    m = d[d.minutes >= 60].copy()
    m["league_id"] = m.league_id.astype("int64")
    m = m.merge(fam[KEY + ["family"]], on=KEY)
    m = m[m.family != "GK"]
    for s in shown:
        m[s] = signature.SKILLS[s][0](m)
        g = m.groupby(["family", "league_id", "season"])[s]
        m[s] = (m[s] - g.transform("mean")) / g.transform("std")
    m["index"] = m[shown].mean(axis=1)
    # opponent strength: his opponent's season expected-goal difference per match, top quarter of the league = big
    tm = pd.read_parquet(GOLD / "team_matches.parquet", columns=["match_id", "league_id", "season", "team_id", "opp_id", "xg"])
    opp_xg = tm[["match_id", "team_id", "xg"]].rename(columns={"team_id": "opp_id", "xg": "xga"})
    tm = tm.merge(opp_xg, on=["match_id", "opp_id"], how="left")
    strength = tm.assign(xgd=tm.xg - tm.xga).groupby(["league_id", "season", "team_id"]).xgd.mean().reset_index()
    strength["top"] = strength.groupby(["league_id", "season"]).xgd.rank(pct=True) > 0.75
    opp = tm[["match_id", "team_id", "opp_id"]].merge(
        strength.rename(columns={"team_id": "opp_id"})[["league_id", "season", "opp_id", "top"]], on="opp_id", how="left")
    opp = opp.drop_duplicates(["match_id", "team_id"])[["match_id", "team_id", "top"]]
    m = m.merge(opp, on=["match_id", "team_id"], how="left")
    m = m.sort_values("date")
    m["half"] = m.groupby(KEY).cumcount() % 2

    def consistency(g: pd.DataFrame) -> float:
        return -float(g["index"].std()) if len(g) >= 8 else np.nan

    def big(g: pd.DataFrame) -> float:
        a, b = g[g.top == True]["index"], g[g.top == False]["index"]   # noqa: E712 (NaN = unknown opponent)
        return float(a.mean() - b.mean()) if len(a) >= 3 and len(b) >= 3 else np.nan

    out, report = {}, {}
    for key, fn in (("consistency", consistency), ("big_games", big)):
        full = m.groupby(KEY).apply(fn, include_groups=False).rename(key)
        h = {i: m[m.half == i].groupby(KEY).apply(fn, include_groups=False) for i in (0, 1)}
        both = pd.concat([h[0].rename("a"), h[1].rename("b")], axis=1).dropna()
        rho = float(spearmanr(both.a, both.b).statistic) if len(both) > 40 else float("nan")
        label, what = MATCH_ATTRS[key]
        report[key] = {"label": label, "reads": what, "split_half_spearman": round(rho, 3), "pairs": int(len(both)),
                       "passed": bool(rho >= GATE)}
        out[key] = full
    return pd.concat(out.values(), axis=1).reset_index(), report


def main() -> None:
    con = duckdb.connect()
    d = load(con)
    rep = json.loads((GOLD / "team_style_report.json").read_text(encoding="utf-8"))
    dims = rep["dimensions_passed"]
    style = pd.read_parquet(GOLD / "team_style.parquet")[["league_id", "season", "team_id"] + [f"z_{c}" for c in dims]]
    fam = pd.read_parquet(GOLD / "player_roles.parquet")[KEY + ["family", "name", "tm_id", "team"]]
    fam["league_id"] = fam.league_id.astype("int64")

    def frame(part: pd.DataFrame) -> pd.DataFrame:
        return summed(part).merge(fam, on=KEY).merge(style, on=["league_id", "season", "team_id"], how="left")

    full = frame(d)
    full = full[(full.minutes >= MIN_SEASON) & (full.family != "GK")].reset_index(drop=True)   # keepers get their own
    d = d.sort_values("date")
    d["half"] = d.groupby(KEY).cumcount() % 2
    big = full[full.minutes >= MIN_SPLIT][KEY]
    halves = {h: frame(d[d.half == h]).merge(big, on=KEY).reset_index(drop=True) for h in (0, 1)}
    leagues = sorted(full.league_id.unique())

    vals, report = read_rates(full, halves, dims, leagues)
    out = pd.concat([full[KEY + ["family", "name", "tm_id", "team", "minutes"]], vals], axis=1)
    mvals, mreport = match_attrs(d, fam)
    mvals["league_id"] = mvals.league_id.astype("int64")
    out = out.merge(mvals, on=KEY, how="left")
    report.update(mreport)
    for a, r in report.items():
        out[f"pct_{a}"] = out.groupby(["family", "season"])[a].rank(pct=True).round(3)
    out.to_parquet(GOLD / "player_attributes.parquet", index=False)
    summary = {"player_seasons": int(len(out)),
               "shown": [r["label"] for r in report.values() if r["passed"]],
               "hidden": [r["label"] for r in report.values() if not r["passed"]],
               "gate": "an attribute is shown when a player's odd matches predict his even ones (Spearman >= 0.5, "
                       "player-seasons of 1,800+ minutes); keepers are read apart",
               "not_readable": {"field of view and scanning": "needs video or tracking (head movements before receiving)",
                                "decision speed": "needs event timing",
                                "pace and work rate": "tracking is published only for the Premier League and the Champions "
                                                      "League from 2024/25: a club's own tracking would add it"},
               "as_first_written": {"vision": 0.563, "composure": 0.388, "discipline": 0.395,
                                    "note": "rare events left out after seeing these (see the module's docstring)"},
               "by_attribute": report}
    (GOLD / "attributes_report.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    for a, r in report.items():
        print(f"  {r['label']:14s} split-half {r['split_half_spearman']}  pairs {r['pairs']}  "
              f"{'shown' if r['passed'] else 'hidden'}  k={r.get('k_minutes', '-')}")


if __name__ == "__main__":
    main()
