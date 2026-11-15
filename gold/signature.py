"""Promesse T4: signature skills. What a player does beyond what his system and his league explain.

1. Every player-season (900+ minutes, MatchData's detailed stats) gets its action rates: per 90, and a few ratios.
2. For each skill and each positional family (T3), a ridge regression predicts the rate from his team's game model (T1,
   the eleven reliable dimensions, standardised within the league-season) and his league. The residual is his own part:
   a centre-back in a possession side passes more, and that isn't a skill of his.
3. Shrinkage by evidence: residual x m / (m + k), with k chosen per skill so that the shrunk residual of a season's
   odd matches best predicts the residual of its even matches. A short season can't make a signature.
4. Gate (T4): a skill is shown only if, after shrinkage, odd-match residuals predict even-match residuals with a
   Spearman correlation of 0.5 or more (player-seasons of 1,800+ minutes). A player's signature skills are the shown
   skills where he sits at the 90th percentile of his family or above.

    python gold/signature.py       (Promesse venv) -> lake/gold/player_skills.parquet, skills_report.json
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
import roles  # noqa: E402  (the player-match rows and the families)

GOLD = Path((DATA_ROOT + "/lake/gold"))
MIN_SEASON, MIN_SPLIT = 900, 1800
KS = (150, 300, 600, 900, 1500, 2500, 4000)
# skill -> (how it is computed from the season's counts, its name in football's words)
SKILLS = {
    "aerial_won": (lambda s: s.aerial_won / s.minutes * 90, "Wins his headers"),
    "aerial_rate": (lambda s: s.aerial_won / s.aerials.replace(0, np.nan), "Aerial duel success"),
    "drib_succ": (lambda s: s.drib_succ / s.minutes * 90, "Beats his man"),
    "chances": (lambda s: s.chances / s.minutes * 90, "Creates chances"),
    "xa": (lambda s: s.xa / s.minutes * 90, "Quality of the chances he creates"),
    "xg": (lambda s: s.xg / s.minutes * 90, "Gets into scoring positions"),
    "final_third": (lambda s: s.final_third / s.minutes * 90, "Moves the ball into the final third"),
    "box": (lambda s: s.box / s.minutes * 90, "Arrives in the box"),
    "interceptions": (lambda s: s.interceptions / s.minutes * 90, "Reads the game"),
    "ball_winning": (lambda s: (s.tackles + s.recoveries) / s.minutes * 90, "Wins the ball back"),
    "fouled": (lambda s: s.fouled / s.minutes * 90, "Draws fouls"),
    "pass_acc": (lambda s: s.pass_acc / s.passes.replace(0, np.nan), "Secure passer"),
    "long_acc": (lambda s: s.long_acc / s.longs.replace(0, np.nan), "Long-range passing"),
    "crosses": (lambda s: s.crosses / s.minutes * 90, "Crosses"),
    "touches": (lambda s: s.touches / s.minutes * 90, "Involvement"),
}
KEY = ["fid", "team_id", "league_id", "season"]


def season_rates(d: pd.DataFrame) -> pd.DataFrame:
    counts = list(roles.COUNTS.values())
    s = d.groupby(KEY)[counts + ["minutes"]].sum()
    out = pd.DataFrame(index=s.index)
    for k, (fn, _) in SKILLS.items():
        out[k] = fn(s)
    out["minutes"] = s.minutes
    return out


def design(df: pd.DataFrame, dims: list[str], leagues: list) -> np.ndarray:
    x = df[[f"z_{c}" for c in dims]].fillna(0).to_numpy()
    lg = (df.league_id.to_numpy()[:, None] == np.array(leagues)[None, :]).astype(float)
    return np.hstack([x, lg])


def main() -> None:
    con = duckdb.connect()
    d = roles.rows(con)
    rep = json.loads((GOLD / "team_style_report.json").read_text(encoding="utf-8"))
    dims = rep["dimensions_passed"]
    style = pd.read_parquet(GOLD / "team_style.parquet")[["league_id", "season", "team_id"] + [f"z_{c}" for c in dims]]
    fam = pd.read_parquet(GOLD / "player_roles.parquet")[KEY + ["family", "name", "tm_id", "team"]]
    fam["league_id"] = fam.league_id.astype("int64")

    def frame(part: pd.DataFrame) -> pd.DataFrame:
        r = season_rates(part).reset_index()
        r["league_id"] = r.league_id.astype("int64")
        return r.merge(fam, on=KEY).merge(style, on=["league_id", "season", "team_id"], how="left")

    full = frame(d)
    full = full[full.minutes >= MIN_SEASON].copy()
    d = d.sort_values("date")
    d["half"] = d.groupby(KEY).cumcount() % 2
    big = full[full.minutes >= MIN_SPLIT][KEY]
    halves = {h: frame(d[d.half == h]).merge(big, on=KEY) for h in (0, 1)}

    leagues = sorted(full.league_id.unique())
    report, out = {}, full[KEY + ["family", "name", "tm_id", "team", "minutes"]].copy()
    for skill, (_, label) in SKILLS.items():
        report[skill] = {"label": label, "by_family": {}}
        resid_full = pd.Series(np.nan, index=full.index)
        r0_all, r1_all, m0_all = [], [], []
        for fam_name, part in full.groupby("family"):
            ok = part[skill].notna()
            if ok.sum() < 80:
                continue
            model = Ridge(alpha=5.0).fit(design(part[ok], dims, leagues), part.loc[ok, skill])
            sd = float(np.nanstd(part.loc[ok, skill] - model.predict(design(part[ok], dims, leagues)))) or 1.0
            resid_full.loc[part.index[ok]] = (part.loc[ok, skill] - model.predict(design(part[ok], dims, leagues))) / sd
            h0 = halves[0][halves[0].family == fam_name].set_index(KEY)
            h1 = halves[1][halves[1].family == fam_name].set_index(KEY)
            both = h0.join(h1, lsuffix="_0", rsuffix="_1", how="inner")
            both = both[both[f"{skill}_0"].notna() & both[f"{skill}_1"].notna()]
            if len(both) < 40:
                continue
            for h, suf in ((0, "_0"), (1, "_1")):
                cols = {f"z_{c}{suf}": f"z_{c}" for c in dims}
                cols[f"{skill}{suf}"] = skill
                hh = both.rename(columns=cols).reset_index()
                pred = model.predict(design(hh, dims, leagues))
                (r0_all if h == 0 else r1_all).append((hh[skill].to_numpy() - pred) / sd)
            m0_all.append(both["minutes_0"].to_numpy())
        if not r0_all:
            continue
        r0, r1, m0 = np.concatenate(r0_all), np.concatenate(r1_all), np.concatenate(m0_all)
        # the shrinkage that makes the first half's residual the best predictor of the second half's
        best = max(KS, key=lambda k: -np.mean((r0 * m0 / (m0 + k) - r1) ** 2))
        rho = float(spearmanr(r0, r1).statistic)
        report[skill].update({"k_minutes": best, "split_half_spearman": round(rho, 3), "pairs": int(len(r0)),
                              "passed": rho >= 0.5})
        out[f"res_{skill}"] = resid_full * full.minutes / (full.minutes + best)
    shown = [s for s, r in report.items() if r.get("passed")]
    for s in shown:
        out[f"pct_{s}"] = out.groupby(["family", "season"])[f"res_{s}"].rank(pct=True).round(3)
    out["signature"] = out.apply(lambda r: [SKILLS[s][1] for s in shown if r.get(f"pct_{s}", 0) >= 0.9], axis=1)
    out.to_parquet(GOLD / "player_skills.parquet", index=False)
    summary = {"player_seasons": int(len(out)), "skills_shown": [SKILLS[s][1] for s in shown],
               "skills_hidden": [SKILLS[s][1] for s in SKILLS if s not in shown],
               "gate_t4": {"rule": "a skill is shown when, after shrinkage, odd-match residuals predict even-match residuals "
                                   "(Spearman >= 0.5, player-seasons of 1,800+ minutes)", "skills_passed": len(shown)},
               "by_skill": {s: {k: v for k, v in r.items() if k != "by_family"} for s, r in report.items()}}
    (GOLD / "skills_report.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("player_seasons", "skills_shown", "skills_hidden", "gate_t4")}, indent=1, ensure_ascii=False))
    for s, r in summary["by_skill"].items():
        print(f"  {r['label']:38s} split-half {r.get('split_half_spearman')}  k={r.get('k_minutes')}")


if __name__ == "__main__":
    main()
