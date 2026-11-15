"""Promesse: every EA rating we hold in one table, each dated by when it was known (D3).

  fifa_all_updates.parquet   FIFA 15 to FIFA 23, weekly updates (the update's date)
  FC 24 (kaggle)             the launch ratings, 2023
  FC 25 (kaggle, gamerating_a)     the earlier update
  FC 26 / FC 27              EA's own ratings pages at launch (2026 as release dates)

All on EA's player ids (gamerating_a uses them), which identity v3 links to Transfermarkt.

    python gold/ea_ratings.py      (Promesse venv) -> lake/gold/ea_ratings.parquet
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
from pathlib import Path

import pandas as pd

DATA = Path(DATA_ROOT)
KAGGLE = DATA / "kaggle"
OUT = DATA / "lake" / "gold" / "ea_ratings.parquet"


def main() -> None:
    parts = []
    u = pd.read_parquet(DATA / "fifa_all_updates.parquet", columns=["player_id", "fifa_update_date", "overall", "potential"])
    parts.append(u.rename(columns={"player_id": "ea_id", "fifa_update_date": "date"}).assign(source="fifa_all_updates"))
    fc24 = pd.read_csv(KAGGLE / "stefanoleone992__ea-sports-fc-24-complete-player-dataset" / "male_players.csv",
                       usecols=["player_id", "fifa_version", "update_as_of", "overall", "potential"], low_memory=False)
    fc24 = fc24[fc24.fifa_version == 24]
    parts.append(fc24.rename(columns={"player_id": "ea_id", "update_as_of": "date"})
                 [["ea_id", "date", "overall", "potential"]].assign(source="fc24_launch"))
    fc25 = pd.read_csv(KAGGLE / "aniss7__fifa-player-data-from-gamerating_a-2025-06-03" / "player-data-full-2025-june.csv",
                       usecols=["player_id", "version", "overall_rating", "potential"], low_memory=False)
    parts.append(fc25.rename(columns={"player_id": "ea_id", "version": "date", "overall_rating": "overall"})
                 .assign(source="fc25_june2025"))
    for name, released in (("ea_fc26.parquet", "2025-09-26"), ("ea_fc27.parquet", "2026-09-26")):
        f = pd.read_parquet(DATA / name)
        pot = f["potential"] if "potential" in f.columns else pd.Series(float("nan"), index=f.index)
        parts.append(pd.DataFrame({"ea_id": f["ea_id"], "date": released, "overall": f["overall"], "potential": pot,
                                   "source": name.replace(".parquet", "")}))
    ea = pd.concat(parts, ignore_index=True)
    ea["ea_id"] = pd.to_numeric(ea["ea_id"], errors="coerce")
    ea["date"] = pd.to_datetime(ea["date"], errors="coerce")
    ea["overall"] = pd.to_numeric(ea["overall"], errors="coerce")
    ea["potential"] = pd.to_numeric(ea["potential"], errors="coerce")
    ea = ea.dropna(subset=["ea_id", "date", "overall"]).drop_duplicates(["ea_id", "date"])
    ea["ea_id"] = ea["ea_id"].astype("int64")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ea.to_parquet(OUT, index=False)
    print(ea.groupby("source").agg(rows=("ea_id", "size"), first=("date", "min"), last=("date", "max")).to_string())


if __name__ == "__main__":
    main()
