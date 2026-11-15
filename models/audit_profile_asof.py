"""Audit, are height and foot filled in once a player is known? The same test as the moves
(audit_moves_asof.py), on the open datasets' players table: the oldest archived copy (Kaggle version 455, about January
2025) against today's (679). The clean case is the 2023 snapshot's players who first became regulars in 2025/26,
after the old copy: if their height and foot were already on record in January 2025 as often as for players who never
made it, the fields aren't completed on notability; if they were missing then and filled in since, they are, and their
absence leaks the outcome.

Read-only.  python models/audit_profile_asof.py   (Promesse venv) -> lake/models/audit_profile_asof.json
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
from pathlib import Path

import pandas as pd

DATA = Path(DATA_ROOT)
ARCH = DATA / "kaggle" / "tm_archive" / "datasets" / "davidcariboo" / "player-scores" / "versions"
OUT = DATA / "lake" / "models" / "audit_profile_asof.json"


def load(v: int) -> pd.DataFrame:
    p = ARCH / str(v) / "players.csv"
    d = pd.read_csv(p, usecols=["player_id", "height_in_cm", "foot"])
    return d.set_index("player_id")


def main() -> None:
    old, new = load(455), load(679)
    t = pd.read_parquet(DATA / "lake" / "gold" / "targets.parquet", columns=["player_id", "snapshot", "y_reg3", "y_reg1"])
    first_reg = t[t.y_reg1 == 1].groupby("player_id").snapshot.min()
    rows = t[t.snapshot.between(2021, 2023) & t.y_reg3.notna()].copy()
    rows["first_reg"] = rows.player_id.map(first_reg)
    rows["group"] = "never a regular (to 2025/26)"
    rows.loc[rows.y_reg3 == 1, "group"] = "regular within three seasons"
    rows.loc[(rows.y_reg3 == 1) & (rows.first_reg >= 2025), "group"] = "first regular in 2025/26 (after the old copy)"
    out = {}
    for f in ("height_in_cm", "foot"):
        rows[f"{f}_now"] = rows.player_id.map(new[f]).notna()
        rows[f"{f}_in_old_table"] = rows.player_id.isin(old.index)
        rows[f"{f}_jan25"] = rows.player_id.map(old[f]).notna()
        g = rows.groupby(["snapshot", "group"]).agg(n=("player_id", "size"), in_old_table=(f"{f}_in_old_table", "mean"),
                                                   filled_jan25=(f"{f}_jan25", "mean"), filled_now=(f"{f}_now", "mean")).round(3)
        out[f] = {f"{s} | {grp}": r.to_dict() for (s, grp), r in g.iterrows()}
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    for f, v in out.items():
        print(f)
        for k, r in v.items():
            print("  ", k, r)


if __name__ == "__main__":
    main()
