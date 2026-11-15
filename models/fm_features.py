"""Engine v2 inputs: what a player does in his minutes, from MatchData's player-match stats.

For every snapshot Y and player: the matches of the previous 365 days, from the main crawl and the backfill
(deduplicated on match and player). Per-90 rates over matches that carry stats, NaN under 450 stat-minutes. The league
adjusted copy (`_adj`) subtracts the mean per-90 of everyone in the same league over the same window (computed from
matches before the snapshot only).  MatchData's own rating is not read (it is a rater).

    python models/fm_features.py     (Promesse venv) -> lake/models/fm_feats.parquet
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

DATA = Path(DATA_ROOT)
LAKE = DATA / "lake"
OUT = LAKE / "models" / "fm_feats.parquet"
MIN_STAT_MIN = 450
RATE = {"chances90": ["Chances created"], "dribbles90": ["Successful dribbles"], "boxtouch90": ["Touches in opposition box"],
        "final3_90": ["Passes into final third"], "defact90": ["Tackles", "Interceptions", "Recoveries", "Clearances"],
        "xgxa90": ["Expected goals (xG)", "Expected assists (xA)"]}
NEED = sorted({c for v in RATE.values() for c in v} | {"Duels won", "Duels lost", "Accurate passes", "Accurate passes (of)", "Minutes played"})


def load() -> pd.DataFrame:
    con = duckdb.connect()
    parts = []
    for tree in ("matchdata", "matchdata_backfill"):
        g = (LAKE / tree / "player_matches").as_posix() + "/**/*.parquet"
        have = {r[0] for r in con.execute(f"describe select * from read_parquet('{g}', union_by_name=true)").fetchall()}
        sel = ", ".join(f'try_cast("{c}" as double) as "{c}"' if c in have else f'null::double as "{c}"' for c in NEED)
        parts.append(con.execute(f"""select match_id::varchar mid, player_id::varchar fid, league_id, season, role,
            try_cast(left(date::varchar, 10) as date) as date, {sel} from read_parquet('{g}', union_by_name=true)""").df())
    d = pd.concat(parts, ignore_index=True).drop_duplicates(["mid", "fid"])
    return d[d.date.notna()]


def window(d: pd.DataFrame, y: int) -> pd.DataFrame:
    snap = pd.Timestamp(y, 7, 1)
    w = d[(d.date < snap) & (d.date >= snap - pd.Timedelta(days=365))].copy()
    mins = w["Minutes played"]
    has = mins.notna() & w["Accurate passes"].notna()                      # a stat line exists
    w["stat_min"] = np.where(has, mins, 0.0)
    w["min_all"] = mins.fillna(0.0)
    w["started"] = (w.role == "starter").astype(float)
    for k, cols in RATE.items():
        w[k] = w[cols].sum(axis=1, min_count=1).where(has)
    w["duels"] = (w["Duels won"] + w["Duels lost"]).where(has)
    w["won"] = w["Duels won"].where(has)
    w["pass_ok"], w["pass_all"] = w["Accurate passes"].where(has), w["Accurate passes (of)"].where(has)
    return w


def per_player(w: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    g = w.groupby(by)
    out = pd.DataFrame({"fm2_min": g.min_all.sum(), "stat_min": g.stat_min.sum(),
                        "apps": g.min_all.apply(lambda s: (s > 0).sum()), "starts": g.started.sum()})
    for k in RATE:
        out[k] = g[k].sum() / out.stat_min * 90
    out["duel_rate"] = g.won.sum() / g.duels.sum()
    out["pass_acc"] = g.pass_ok.sum() / g.pass_all.sum()
    return out


def main() -> None:
    d = load()
    persons = pd.read_parquet(LAKE / "identity" / "persons.parquet", columns=["tm_id", "matchdata_id"]).dropna()
    persons["fid"] = persons.matchdata_id.astype(str).str.replace(r"\.0$", "", regex=True)
    link = persons.drop_duplicates("fid").set_index("fid").tm_id
    rows = []
    for y in range(2014, 2027):
        w = window(d, y)
        if w.empty:
            continue
        # league-window means of each rate over players with enough stat minutes (the yardstick of the _adj copy)
        pp = per_player(w, ["fid", "league_id"]).reset_index()
        ok = pp[pp.stat_min >= MIN_STAT_MIN]
        mean = ok.groupby("league_id")[list(RATE) + ["duel_rate", "pass_acc"]].mean()
        a = per_player(w, ["fid"])
        main_league = w.groupby("fid").league_id.agg(lambda s: s.value_counts().index[0])
        a["league_id"] = main_league.reindex(a.index)
        a = a.reset_index()
        a["tm_id"] = a.fid.map(link)
        a = a.dropna(subset=["tm_id"])
        stat_ok = a.stat_min >= MIN_STAT_MIN
        out = pd.DataFrame({"player_id": a.tm_id.astype("int64"), "snapshot": y,
                            "fm2_min_365": a.fm2_min, "fm2_start_share": (a.starts / a.apps).where(a.apps > 0),
                            "fm2_stat_cov": (a.stat_min / a.fm2_min).where(a.fm2_min > 0)})
        names = {"chances90": "fm2_chances90", "dribbles90": "fm2_dribbles90", "boxtouch90": "fm2_boxtouch90",
                 "final3_90": "fm2_final3_90", "defact90": "fm2_defact90", "duel_rate": "fm2_duel_rate", "pass_acc": "fm2_pass_acc"}
        for k, n in names.items():
            out[n] = a[k].where(stat_ok).to_numpy()
            out[n + "_adj"] = (a[k] - a.league_id.map(mean[k])).where(stat_ok).to_numpy()
        out["fm2_xgxa90"] = a.xgxa90.where(stat_ok).to_numpy()
        out["fm2_xgxa90_adj"] = (a.xgxa90 - a.league_id.map(mean.xgxa90)).where(stat_ok).to_numpy()
        rows.append(out.groupby(["player_id", "snapshot"], as_index=False).first())
        print(y, len(out), "with stats:", int(stat_ok.sum()), flush=True)
    res = pd.concat(rows, ignore_index=True).replace([np.inf, -np.inf], np.nan)   # a rate over zero duels or passes
    res.to_parquet(OUT, index=False)
    print(f"{len(res):,} player-snapshots -> {OUT}")


if __name__ == "__main__":
    main()
