"""ProEngine: youth international selection, point in time (replaces the career-page youth caps,
withdrawn as unverified: models/inputs.py UNVERIFIED).

The squads of the U16/U17/U19/U20 world and continental finals (youth_u17_tournaments.parquet) are fixed by the
tournament itself: a call-up can't be filled in later the way a profile field can. What can still leak is the link to
a player: the squads came linked to Transfermarkt for 35 % of their members, more often for players who became known.
So every member is linked again the same way, by birth date and surname against the open datasets' players table
(a unique match only), whatever became of him. A tournament counts at snapshot Y only if it was played in an
earlier calendar year: the dates aren't held, and U17 World Cups and U19 Euros run past the start of July.
  yt_selected   in the squad of at least one youth final before the snapshot
  yt_squads     how many (log 1 + n)
  yt_top_level  the oldest age group he was selected for (16, 17, 19, 20), 0 if none
Every spine row gets the three columns (0 = no squad), the current snapshot included.

    python gold/youth_tournaments.py      (Promesse venv) -> adds these columns to lake/gold/spine_extra.parquet
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import unicodedata
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

DATA = Path(DATA_ROOT)
GOLD = DATA / "lake" / "gold"
COLS = ("yt_selected", "yt_squads", "yt_top_level")


def surname(s) -> str:
    """The last word of a name, accents and case removed."""
    if not isinstance(s, str) or not s.strip():
        return ""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().replace("-", " ").split()[-1]


def main() -> None:
    sq = pd.read_parquet(DATA / "youth_u17_tournaments.parquet")
    sq = sq[sq.dob.notna()].copy()
    sq["dob"], sq["sn"] = pd.to_datetime(sq.dob).dt.normalize(), sq.name.map(surname)
    tm = duckdb.connect(str(DATA / "transfermarkt-datasets.duckdb"), read_only=True)
    pl = tm.sql("select player_id::bigint player_id, name, date_of_birth::date dob from players where date_of_birth is not null").df()
    tm.close()
    pl["dob"], pl["sn"] = pd.to_datetime(pl.dob).dt.normalize(), pl.name.map(surname)
    unique = pl.groupby(["dob", "sn"]).filter(lambda g: len(g) == 1)          # an ambiguous key links nobody
    sq = sq.merge(unique[["dob", "sn", "player_id"]].rename(columns={"player_id": "relinked"}), on=["dob", "sn"], how="left")
    before = sq.player_id.notna().mean()
    sq["pid"] = sq.relinked.fillna(sq.player_id)
    print(f"squad members with a birth date: {len(sq):,}; linked as delivered {before:.1%}, after relinking {sq.pid.notna().mean():.1%}")
    sq = sq[sq.pid.notna()].copy()
    sq["pid"] = sq.pid.astype("int64")
    sq["level"] = sq.age_group.str.extract(r"U(\d{2})")[0].astype(float)

    extra = pd.read_parquet(GOLD / "spine_extra.parquet").drop(columns=[c for c in COLS], errors="ignore")
    pairs = pd.concat([pd.read_parquet(GOLD / f, columns=["player_id", "snapshot"]) for f in ("spine.parquet", "spine_current.parquet")])
    pairs = pairs.drop_duplicates()
    rows = []
    for y in sorted(pairs.snapshot.unique()):
        done = sq[sq.year < y]
        g = done.groupby("pid")
        f = pd.DataFrame({"yt_selected": 1.0, "yt_squads": np.log1p(g.size()), "yt_top_level": g["level"].max()})
        f["snapshot"] = y
        rows.append(f.rename_axis("player_id").reset_index())
    yt = pd.concat(rows, ignore_index=True)
    pairs = pairs.merge(yt, on=["player_id", "snapshot"], how="left")
    for c in COLS:
        pairs[c] = pairs[c].fillna(0.0)
    extra = extra.merge(pairs, on=["player_id", "snapshot"], how="outer")     # every spine row gets the columns
    extra.to_parquet(GOLD / "spine_extra.parquet", index=False)
    s = pairs[pairs.snapshot.between(2014, 2022)]
    print(f"{(s.yt_selected > 0).mean():.2%} of 2014-2022 spine rows selected before the snapshot; {len(extra):,} rows in spine_extra")


if __name__ == "__main__":
    main()
