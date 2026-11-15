"""ProEngine: moves and loans as facts of a career, point in time (moves are an input; fees stay
a benchmark, never read here).

From Transfermarkt's transfers (dated club changes). At snapshot Y, only moves dated before Y count; the table
also holds planned future moves (up to 2030), which never do. The data has no loan flag, so a loan is read the only way
that's knowable at the time: a completed round trip, A to B and back to A, both legs before Y.
  mv_moves_2y     club changes in the two years before the snapshot
  mv_loans_done   completed loans (round trips) before the snapshot
  mv_days_since   days since his last move before the snapshot (NaN if none)
  mv_last_step    the last move's step in level: the destination's strength minus the origin's, each club's Elo+
                  rating at its last game before the move date (gold/strength_tm.py, league levels included)

    python gold/moves.py      (Promesse venv) -> adds these columns to lake/gold/spine_extra.parquet
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

DATA = Path(DATA_ROOT)
GOLD = DATA / "lake" / "gold"
COLS = ("mv_moves_2y", "mv_loans_done", "mv_days_since", "mv_last_step")


def club_rating_at(moves: pd.DataFrame, side: str) -> pd.Series:
    """Each move's origin or destination club rating at its last game before the move date."""
    g = pd.read_parquet(GOLD / "tm_game_strength.parquet", columns=["date", "home_id", "away_id", "r_home", "r_away"])
    games = pd.concat([g[["date", "home_id", "r_home"]].set_axis(["date", "club", "r"], axis=1),
                       g[["date", "away_id", "r_away"]].set_axis(["date", "club", "r"], axis=1)])
    games["date"] = pd.to_datetime(games.date)
    games = games.sort_values("date")
    m = moves[["date", f"{side}_club_id"]].rename(columns={f"{side}_club_id": "club"}).reset_index().sort_values("date")
    m["club"] = m.club.astype("int64")
    games["club"] = games.club.astype("int64")
    out = pd.merge_asof(m, games, on="date", by="club", direction="backward", allow_exact_matches=False)
    return out.set_index("index").r.reindex(moves.index)


def main() -> None:
    c = duckdb.connect(str(DATA / "transfermarkt-datasets.duckdb"), read_only=True)
    mv = c.execute("""select player_id::bigint player_id, transfer_date::date date, from_club_id, to_club_id
                      from transfers where transfer_date is not null and from_club_id is not null and to_club_id is not null
                        and from_club_id <> to_club_id""").df()
    c.close()
    mv["date"] = pd.to_datetime(mv.date)
    mv = mv.sort_values(["player_id", "date"]).reset_index(drop=True)
    mv["step"] = club_rating_at(mv, "to") - club_rating_at(mv, "from")
    # a loan, as it's knowable: the next move goes back to the club he came from; dated at the return
    nxt = mv.groupby("player_id").shift(-1)
    mv["loan_return_date"] = np.where((nxt.to_club_id == mv.from_club_id) & (nxt.from_club_id == mv.to_club_id), nxt.date, pd.NaT)
    mv["loan_return_date"] = pd.to_datetime(mv.loan_return_date)

    extra = pd.read_parquet(GOLD / "spine_extra.parquet")
    extra = extra.drop(columns=[c for c in COLS if c in extra])
    rows = []
    for y in sorted(extra.snapshot.unique()):
        snap = pd.Timestamp(f"{y}-07-01")
        before = mv[mv.date < snap]
        recent = before[before.date >= snap - pd.Timedelta(days=730)]
        last = before.groupby("player_id").tail(1).set_index("player_id")
        f = pd.DataFrame({"mv_moves_2y": recent.groupby("player_id").size(),
                          "mv_loans_done": before[before.loan_return_date < snap].groupby("player_id").size(),
                          "mv_days_since": (snap - last.date).dt.days, "mv_last_step": last.step})
        f["snapshot"] = y
        rows.append(f.rename_axis("player_id").reset_index())
    feats = pd.concat(rows, ignore_index=True)
    extra = extra.merge(feats, on=["player_id", "snapshot"], how="left")
    for col in ("mv_moves_2y", "mv_loans_done"):
        extra[col] = extra[col].fillna(0)
    extra.to_parquet(GOLD / "spine_extra.parquet", index=False)
    print({c: f"{extra[c].notna().mean():.1%} known, {(extra[c].fillna(0) > 0).mean():.1%} > 0" for c in COLS}, f"{len(mv):,} moves")


if __name__ == "__main__":
    main()
