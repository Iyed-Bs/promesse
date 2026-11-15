"""ProEngine: youth international football as a fact of a career (youth caps are an input).

From MatchData's career pages (section "national team"): every stint with a national team, its age level (U15 ... U23,
senior) and its dates. Point in time, without leakage: at snapshot Y, a stint counts only if it began before
the snapshot; its appearances count only if it also ended before it (a stint running across the snapshot gives its
selection, never its later matches).
  yi_apps        youth international appearances in stints finished before the snapshot
  yi_top_level   the oldest youth level he was selected for (17 for U17, 21 for U21...), 0 if none
  yi_selected    selected for any youth national team before the snapshot
  senior_cap     selected for the senior national team before the snapshot

    python gold/youth_caps.py      (Promesse venv) -> adds these columns to lake/gold/spine_extra.parquet
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


def main() -> None:
    con = duckdb.connect()
    nt = con.execute(f"""select player_id::varchar fid, team, try_cast(start as date) s, try_cast(nullif("end", '') as date) e,
                                coalesce(appearances, 0) apps
                         from read_parquet('{(DATA / 'matchdata_youth_careers.parquet').as_posix()}') where section = 'national team'""").df()
    ids = con.execute(f"""select matchdata_id::varchar fid, try_cast(tm_id as bigint) player_id
                          from read_parquet('{(GOLD.parent / 'identity' / 'persons.parquet').as_posix()}')
                          where matchdata_id is not null and tm_id is not null""").df().drop_duplicates("fid")
    nt = nt.merge(ids, on="fid").dropna(subset=["s"])
    lvl = nt.team.str.extract(r"U(\d{2})", flags=re.I)[0].astype(float)
    nt["level"] = lvl                                   # NaN = the senior national team
    nt["s"], nt["e"] = pd.to_datetime(nt.s), pd.to_datetime(nt.e)
    extra = pd.read_parquet(GOLD / "spine_extra.parquet")
    for c in ("yi_apps", "yi_top_level", "yi_selected", "senior_cap"):
        if c in extra:
            extra = extra.drop(columns=c)
    rows = []
    for y in sorted(extra.snapshot.unique()):
        snap = pd.Timestamp(f"{y}-07-01")
        began = nt[nt.s < snap]
        youth, senior = began[began.level.notna()], began[began.level.isna()]
        done = youth[youth.e.notna() & (youth.e < snap)]
        f = pd.DataFrame({"yi_apps": done.groupby("player_id")["apps"].sum(),
                          "yi_top_level": youth.groupby("player_id")["level"].max(),
                          "yi_selected": youth.groupby("player_id").size().clip(upper=1)})
        f["senior_cap"] = pd.Series(1, index=senior.player_id.unique()).reindex(f.index.union(senior.player_id.unique()))
        f = f.reindex(f.index.union(senior.player_id.unique()))
        f["snapshot"] = y
        rows.append(f.rename_axis("player_id").reset_index())
    caps = pd.concat(rows, ignore_index=True)
    extra = extra.merge(caps, on=["player_id", "snapshot"], how="left")
    for c in ("yi_apps", "yi_top_level", "yi_selected", "senior_cap"):
        extra[c] = extra[c].fillna(0)
    extra["yi_apps"] = np.log1p(extra.yi_apps)
    extra.to_parquet(GOLD / "spine_extra.parquet", index=False)
    print({c: f"{(extra[c] > 0).mean():.1%} with any" for c in ("yi_apps", "yi_selected", "senior_cap")}, f"{len(caps):,} rows")


if __name__ == "__main__":
    main()
