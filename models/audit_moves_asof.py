"""Audit, do the moves inputs leak the outcome? The engine's edge over the raters comes with them (on T2: level
without, +0.021 with). A move dated before the snapshot can still have been recorded after it: Transfermarkt fills in
the history of players who become notable, and the open datasets widen the set of players they collect. Either way
the 2026 copy we train on would hold moves no model could have seen at the time, more often for players who made it.

The test: the oldest archived copy of the open datasets' transfers table (Kaggle davidcariboo/player-scores, version
455, about January 2025) against the current one (version 679, September 2026). For every T2/T3 row (snapshots
2021-2023), the moves gold/moves.py counts (dated in the two years before the start of July of the snapshot year) are matched in
the old copy. If the share already on record in January 2025 is the same for players who became regulars and those
who didn't, the moves carry no recording leak; if future regulars' moves are missing from the old copy more often,
they do. Split further by when he first became a regular: before 2025/26 (notable by January 2025) or in 2025/26
(not yet notable: the clean case).

Read-only. Archived copies live in <data root>/kaggle/tm_archive (private, never published).

    python models/audit_moves_asof.py      (Promesse venv) -> lake/models/audit_moves_asof.json
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
from pathlib import Path

import pandas as pd

DATA = Path(DATA_ROOT)
ARCH = DATA / "kaggle" / "tm_archive" / "datasets" / "davidcariboo" / "player-scores" / "versions"
OLD, NEW = 455, 679
OUT = DATA / "lake" / "models" / "audit_moves_asof.json"
KEY = ["player_id", "transfer_date", "from_club_id", "to_club_id"]


def load(v: int) -> pd.DataFrame:
    d = pd.read_csv(ARCH / str(v) / "transfers.csv", usecols=KEY)
    d["transfer_date"] = pd.to_datetime(d.transfer_date)
    return d.drop_duplicates()


def main() -> None:
    old, new = load(OLD), load(NEW)
    old["on_record"] = True
    t = pd.read_parquet(DATA / "lake" / "gold" / "targets.parquet", columns=["player_id", "snapshot", "y_reg3", "y_reg1"])
    first_reg = t[t.y_reg1 == 1].groupby("player_id").snapshot.min()          # the first season he was a regular
    rows = t[t.snapshot.between(2021, 2023) & t.y_reg3.notna()].copy()
    rows["first_reg"] = rows.player_id.map(first_reg)
    out = {"old_version": OLD, "new_version": NEW, "rows": {}, "by_group": {}}
    m = new.merge(rows, on="player_id")
    cut = pd.to_datetime(m.snapshot.astype(str) + "-07-01")
    m = m[(m.transfer_date < cut) & (m.transfer_date >= cut - pd.DateOffset(years=2))]
    m = m.merge(old, on=KEY, how="left")
    m["on_record"] = m.on_record.fillna(False).astype(bool)
    m["group"] = "never a regular (to 2025/26)"
    m.loc[m.y_reg3 == 1, "group"] = "regular within three seasons"
    m.loc[(m.y_reg3 == 1) & (m.first_reg >= 2025), "group"] = "first regular in 2025/26 (after the old copy)"
    g = m.groupby(["snapshot", "group"]).on_record.agg(["mean", "size"]).round(3)
    out["by_group"] = {f"{s} | {grp}": {"share_on_record_jan_2025": float(r["mean"]), "moves": int(r["size"])}
                       for (s, grp), r in g.iterrows()}
    pooled = m.groupby("group").on_record.agg(["mean", "size"]).round(3)
    out["pooled"] = {grp: {"share_on_record_jan_2025": float(r["mean"]), "moves": int(r["size"])} for grp, r in pooled.iterrows()}
    out["rows"] = {"old_transfers": int(len(old)), "new_transfers": int(len(new)), "moves_checked": int(len(m))}
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out["pooled"], indent=1)); print(json.dumps(out["by_group"], indent=0))


if __name__ == "__main__":
    main()
