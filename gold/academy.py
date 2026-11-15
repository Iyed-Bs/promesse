"""ProEngine: academy pedigree, point in time (the project notes, the loop's queue: "academy pedigree (youth
stints at clubs, point in time)").

From MatchData's career pages (section "youth"): every youth stint, its team ("Barcelona U19", "Chelsea U21") and dates.
The academy is the club behind the youth team. At snapshot Y:
  - his academies are the youth teams whose stint began before Y;
  - an academy's record at Y is how often its earlier players became regulars (y_reg3: half his club's league minutes
    within three seasons), counting only players whose outcome was already settled by Y (their snapshot at 17-19, plus
    three years, no later than Y), never the player himself;
  - the record is shrunk toward the overall rate by its number of players (m = 20), so a small academy says little.
  ac_rate   the best record among his academies (NaN if none of his academies has a settled record yet)
  ac_alumni log of that academy's settled players (how much the record rests on)
  ac_any    a youth stint at a known academy before Y

    python gold/academy.py      (Promesse venv) -> adds these columns to lake/gold/spine_extra.parquet
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

DATA = Path(DATA_ROOT)
GOLD = DATA / "lake" / "gold"
M = 20                                  # shrinkage: an academy's record counts as much as M players at the overall rate
COLS = ("ac_rate", "ac_alumni", "ac_any")
_YOUTH = re.compile(r"\s+(u\d{2}|ii|b|youth|reserves?|academy|juvenil a|primavera|jong)$", re.I)


def academy_of(team: str) -> str:
    """'Barcelona U19' -> 'barcelona', 'Jong Ajax' -> 'ajax': the club behind the youth team."""
    t = re.sub(r"^jong\s+", "", str(team).strip(), flags=re.I)
    while True:
        u = _YOUTH.sub("", t)
        if u == t:
            return t.lower()
        t = u


def main() -> None:
    con = duckdb.connect()
    yc = con.execute(f"""select player_id::varchar fid, team, try_cast(start as date) s
                         from read_parquet('{(DATA / 'matchdata_youth_careers.parquet').as_posix()}') where section = 'youth'""").df()
    ids = con.execute(f"""select matchdata_id::varchar fid, try_cast(tm_id as bigint) player_id
                          from read_parquet('{(GOLD.parent / 'identity' / 'persons.parquet').as_posix()}')
                          where matchdata_id is not null and tm_id is not null""").df().drop_duplicates("fid")
    yc = yc.merge(ids, on="fid").dropna(subset=["s"])
    yc["s"] = pd.to_datetime(yc.s)
    yc["academy"] = yc.team.map(academy_of)
    sp = pd.read_parquet(GOLD / "spine.parquet", columns=["player_id", "snapshot", "age"])
    tg = pd.read_parquet(GOLD / "targets.parquet", columns=["player_id", "snapshot", "y_reg3"])
    sp = sp.merge(tg, on=["player_id", "snapshot"], how="left")

    # each academy's alumni: one outcome per player, at his first snapshot aged 17-19 after he joined; settled 3 years on
    first = yc.groupby(["player_id", "academy"]).s.min().reset_index()
    al = first.merge(sp[sp.age.between(17, 19.99) & sp.y_reg3.notna()], on="player_id")
    al = al[al.s < pd.to_datetime(al.snapshot.astype(str) + "-07-01")]
    al = al.sort_values("snapshot").groupby(["player_id", "academy"]).head(1)
    al["settled"] = al.snapshot + 3

    extra = pd.read_parquet(GOLD / "spine_extra.parquet")
    extra = extra.drop(columns=[c for c in COLS if c in extra])
    rows = []
    for y in sorted(extra.snapshot.unique()):
        snap = pd.Timestamp(f"{y}-07-01")
        known = al[al.settled <= y]
        overall = known.y_reg3.mean() if len(known) else np.nan
        rec = known.groupby("academy").agg(n=("y_reg3", "size"), k=("y_reg3", "sum"))
        mine = yc[yc.s < snap][["player_id", "academy"]].drop_duplicates()
        mine = mine.merge(rec, left_on="academy", right_index=True, how="left")
        # never the player himself: take his own settled outcome out of his academy's record
        own = known[["player_id", "academy", "y_reg3"]].rename(columns={"y_reg3": "own"})
        mine = mine.merge(own, on=["player_id", "academy"], how="left")
        mine["n"] = mine.n.fillna(0) - mine.own.notna()
        mine["k"] = mine.k.fillna(0) - mine.own.fillna(0)
        mine["rate"] = np.where(mine.n > 0, (mine.k + M * overall) / (mine.n + M), np.nan)
        best = mine.sort_values("rate", ascending=False).groupby("player_id").head(1)
        f = pd.DataFrame({"player_id": best.player_id, "ac_rate": best.rate, "ac_alumni": np.log1p(best.n.clip(lower=0)),
                          "ac_any": 1.0, "snapshot": y})
        rows.append(f)
    ac = pd.concat(rows, ignore_index=True)
    extra = extra.merge(ac, on=["player_id", "snapshot"], how="left")
    extra["ac_any"] = extra.ac_any.fillna(0)
    extra["ac_alumni"] = extra.ac_alumni.fillna(0)
    extra.to_parquet(GOLD / "spine_extra.parquet", index=False)
    young = extra.merge(sp[["player_id", "snapshot", "age"]], on=["player_id", "snapshot"])
    young = young[young.age < 21]
    print(f"{len(al):,} alumni outcomes over {al.academy.nunique():,} academies | under-21 spine rows with a known academy "
          f"{young.ac_any.mean():.1%}, with a settled record {young.ac_rate.notna().mean():.1%}")
    top = al[al.settled <= 2023].groupby("academy").y_reg3.agg(["size", "mean"]).query("size >= 25").sort_values("mean", ascending=False)
    print("best records (25+ settled players):", top.head(8).round(2).to_dict("index"))


if __name__ == "__main__":
    main()
