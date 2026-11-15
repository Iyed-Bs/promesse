"""Promesse, Phase 5 (v1): M3, the Promesse rating. One latent ability per player, fused from every source over time.

State-space model (ARCHITECTURE §5, M3), kept small and testable:
  state        θ(t): ability on EA's overall scale; between two dated observations it drifts by the age curve and
               gains process noise q·Δt (years)
  measurements each source s is θ seen through its own offset, scale and noise:  y = a_s + b_s·θ + e_s, e_s ~ N(0, r_s)
                 ea      EA overall (the anchor: a = 0, b = 1, its noise estimated)
                 pes     the mean of PES's main abilities (the edition's release date)
                 fm      MatchData rating, minutes-weighted per player and half-season (2021 on)
                 level   the club level (Elo vs the big five) of a season he held at 40 %+ (the season's end)
  filter       Kalman, per player, in date order; the state at a snapshot uses only observations dated before it

Everything is estimated on the training years only (dates before the start of the 2019/20 season, T1's train window): the age curve and
q from EA's own year-on-year changes; each source's a, b, r by regressing it on the EA overall known at the time.
The gate (Phase 5): the fused rating and its uncertainty, added to the spine, improve the ladder on T2.

    python models/m3_fusion.py      (Promesse venv) -> lake/models/m3_states.parquet (player, snapshot, θ, var, n_obs),
                                                       m3_params.json
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import glob
import json
import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

DATA = Path(DATA_ROOT)
LAKE = DATA / "lake"
GOLD = LAKE / "gold"
OUT = LAKE / "models"
TM = DATA / "transfermarkt-datasets.duckdb"
FIT_BEFORE = pd.Timestamp("2019-07-01")
PES_MAIN = ["Attacking Prowess", "Ball Control", "Dribbling", "Low Pass", "Lofted Pass", "Finishing", "Header",
            "Defensive Prowess", "Ball Winning", "Kicking Power", "Speed", "Explosive Power", "Body Control",
            "Physical Contact", "Jump", "Stamina"]


def observations() -> pd.DataFrame:
    """Every dated observation of every Transfermarkt player: (player_id, date, source, value)."""
    con = duckdb.connect()
    persons = con.sql(f"""select try_cast(tm_id as bigint) tm, try_cast(ea_id as bigint) ea, try_cast(konami_id as bigint) km,
                          matchdata_id::varchar fm from read_parquet('{(LAKE / 'identity' / 'persons.parquet').as_posix()}')
                          where tm_id is not null""").df()
    ea = pd.read_parquet(GOLD / "ea_ratings.parquet", columns=["ea_id", "date", "overall"])
    ea = ea.merge(persons[["tm", "ea"]].dropna(), left_on="ea_id", right_on="ea")
    # one EA observation per player and month is plenty (weekly updates repeat the same number)
    ea["m"] = ea.date.dt.to_period("M")
    ea = ea.sort_values("date").drop_duplicates(["tm", "m"], keep="last")
    obs = [pd.DataFrame({"player_id": ea.tm, "date": ea.date, "source": "ea", "value": ea.overall})]
    pes = []
    for f in sorted(glob.glob(str(DATA / "gamerating_b_pes*.parquet"))):
        d = pd.read_parquet(f)
        cols = [c for c in PES_MAIN if c in d.columns]
        if "pes_id" not in d.columns or not cols:
            continue
        year = int(re.search(r"(\d{4})", str(d["edition"].iloc[0])).group(1))
        pes.append(pd.DataFrame({"km": pd.to_numeric(d.pes_id, errors="coerce"), "date": pd.Timestamp(year - 1, 9, 15),
                                 "value": d[cols].apply(pd.to_numeric, errors="coerce").mean(axis=1)}))
    if pes:
        p = pd.concat(pes).merge(persons[["tm", "km"]].dropna(), on="km")
        obs.append(pd.DataFrame({"player_id": p.tm, "date": p.date, "source": "pes", "value": p.value}))
    fm_files = (LAKE / "matchdata" / "player_matches").as_posix() + "/**/*.parquet"
    fm = con.sql(f"""select player_id::varchar fm, try_cast(left(date, 10) as date) d, "matchdata rating" r, "Minutes played" mi
                     from read_parquet('{fm_files}', union_by_name=true) where "matchdata rating" is not null and "Minutes played" > 0""").df()
    fm["d"] = pd.to_datetime(fm["d"])
    fm["half"] = fm.d.dt.year * 2 + (fm.d.dt.month >= 7)
    fm["rm"] = fm.r * fm.mi
    g = fm.groupby(["fm", "half"]).agg(rm=("rm", "sum"), mi=("mi", "sum"), d=("d", "max")).reset_index()
    g = g[g.mi >= 450]                                   # five full games' worth before a half-season counts
    g = g.merge(persons[["tm", "fm"]].dropna(), on="fm")
    obs.append(pd.DataFrame({"player_id": g.tm, "date": g.d, "source": "fm", "value": g.rm / g.mi}))
    pcs = pd.read_parquet(GOLD / "player_club_seasons.parquet")
    pcs = pcs[pcs.share >= 0.4].dropna(subset=["team_level_rel"])
    lv = pcs.groupby(["player_id", "season"])["team_level_rel"].max().reset_index()
    obs.append(pd.DataFrame({"player_id": lv.player_id, "date": pd.to_datetime((lv.season + 1).astype(str) + "-06-15"),
                             "source": "level", "value": lv.team_level_rel}))
    o = pd.concat(obs, ignore_index=True).dropna()
    o["player_id"] = o.player_id.astype("int64")
    return o.sort_values(["player_id", "date"]).reset_index(drop=True)


def births() -> pd.Series:
    c = duckdb.connect(str(TM), read_only=True)
    d = c.sql("select player_id::bigint p, date_of_birth::date dob from players where date_of_birth is not null").df()
    c.close()
    return pd.Series(pd.to_datetime(d.dob).values, index=d.p)


def fit(o: pd.DataFrame, dob: pd.Series) -> dict:
    """Age curve, process noise and each source's (a, b, r), from observations before FIT_BEFORE only."""
    tr = o[o.date < FIT_BEFORE].copy()
    tr["age"] = (tr.date - tr.player_id.map(dob)).dt.days / 365.25
    e = tr[tr.source == "ea"].sort_values(["player_id", "date"])
    # year-on-year EA changes (pairs 300-430 days apart) give the age curve and the process noise
    e["next_v"] = e.groupby("player_id").value.shift(-12)
    e["next_d"] = e.groupby("player_id").date.shift(-12)
    pair = e.dropna(subset=["next_v", "age"])
    gap = (pair.next_d - pair.date).dt.days
    pair = pair[(gap > 300) & (gap < 430)]
    pair = pair.assign(dv=pair.next_v - pair.value, a=pair.age.round().clip(15, 36))
    curve = pair.groupby("a").dv.mean().to_dict()
    q = float(pair.groupby("a").dv.var().median())
    params = {"age_curve": {int(k): round(float(v), 3) for k, v in curve.items()}, "q_per_year": round(q, 3)}
    # each source against the EA overall known at the time (within 120 days before it)
    ea_asof = e[["player_id", "date", "value"]].rename(columns={"value": "ea"}).sort_values("date")
    src = {"ea": {"a": 0.0, "b": 1.0}}
    for s in ("pes", "fm", "level"):
        x = tr[tr.source == s][["player_id", "date", "value"]].sort_values("date")
        if len(x) < 200:
            src[s] = None
            continue
        j = pd.merge_asof(x, ea_asof, on="date", by="player_id", tolerance=pd.Timedelta(days=120), direction="backward").dropna()
        if len(j) < 200:
            src[s] = None
            continue
        b, a = np.polyfit(j.ea, j.value, 1)
        src[s] = {"a": float(a), "b": float(b), "r": float(np.var(j.value - (a + b * j.ea))), "n": int(len(j))}
    # EA's own noise: the spread of month-to-month changes within one edition is small; take a floor of 1 point²
    src["ea"]["r"] = 1.0
    params["sources"] = src
    return params


def run_filter(o: pd.DataFrame, dob: pd.Series, params: dict, snapshots: pd.DataFrame) -> pd.DataFrame:
    """Kalman filter per player; at each of his snapshots, the state given the observations dated before it."""
    curve = {int(k): v for k, v in params["age_curve"].items()}
    q = params["q_per_year"]
    src = {k: v for k, v in params["sources"].items() if v}
    o = o[o.source.isin(src)]
    by_player = {p: g for p, g in o.groupby("player_id")}
    out = []
    for p, snaps in snapshots.groupby("player_id"):
        g = by_player.get(p)
        born = dob.get(p)
        theta, var, last, n = 55.0, 100.0, None, 0          # a wide prior: an unknown youngster
        events = [] if g is None else list(zip(g.date, g.source, g.value))
        k = 0
        for s_date in sorted(pd.to_datetime(snaps.snapshot.astype(str) + "-07-01")):
            while k < len(events) and events[k][0] < s_date:
                d, s, y = events[k]
                if last is not None:
                    dt = max((d - last).days / 365.25, 0.0)
                    age = (d - born).days / 365.25 if pd.notna(born) else 22.0
                    theta += curve.get(int(round(min(max(age, 15), 36))), 0.0) * dt
                    var += q * dt
                m = src[s]
                pred = m["a"] + m["b"] * theta
                S = m["b"] ** 2 * var + m["r"]
                K = var * m["b"] / S
                theta += K * (y - pred)
                var *= (1 - K * m["b"])
                last, n = d, n + 1
                k += 1
            th, va = theta, var
            if last is not None:                              # carried forward to the snapshot
                dt = max((s_date - last).days / 365.25, 0.0)
                age = (s_date - born).days / 365.25 if pd.notna(born) else 22.0
                th += curve.get(int(round(min(max(age, 15), 36))), 0.0) * dt
                va += q * dt
            out.append((p, s_date.year, th, va, n))
    return pd.DataFrame(out, columns=["player_id", "snapshot", "m3_theta", "m3_var", "m3_n_obs"])


def main() -> None:
    o = observations()
    dob = births()
    params = fit(o, dob)
    sp = pd.read_parquet(GOLD / "spine.parquet", columns=["player_id", "snapshot"])
    states = run_filter(o, dob, params, sp)
    OUT.mkdir(parents=True, exist_ok=True)
    states.to_parquet(OUT / "m3_states.parquet", index=False)
    params["observations"] = o.source.value_counts().to_dict()
    params["states"] = int(len(states))
    params["with_evidence"] = int((states.m3_n_obs > 0).sum())
    (OUT / "m3_params.json").write_text(json.dumps(params, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in params.items() if k != "age_curve"}, indent=1))


if __name__ == "__main__":
    main()
