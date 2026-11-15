"""The data contract: the canonical tables everything lands in, whoever measured it.

A club already pays for data (event feeds, tracking, GPS vests, video, scouting reports, a medical system). Promesse
does not ask it to change any of that: each source comes in through an adapter (connect/adapters.py) that writes one of
the tables below, keyed the same way, with where it came from and when it was known. Engines read the tables, never a
provider's format, so a new source is one adapter, not a rewrite.

Rules every table follows:
  - keys: `match_ref` and `player_ref` are "<source>:<id>" strings (the provider's own id, never rewritten); the bridge
    to our people is identity_links (connect/identity.py), so a wrong link can be fixed without touching the data
  - point in time: `known_at` is when the row could first have been known (a match: its date; a report: the day it was
    written; a medical status: the day it was entered). Engines filter on it, which is how no future leaks into a
    projection
  - provenance: `source` (adapter name) and `licence` on every row; licensed or scraped data never leaves the club
  - coordinates: metres on a 105 x 68 pitch, x along it, origin at a corner; attack direction as the adapter states
  - medical: availability only (available, injured, ill, suspended, away with a national team), never a diagnosis
"""
from __future__ import annotations

import pandas as pd

# table -> {column: (dtype, required, meaning)}. a new column is added here first, then in the adapters
TABLES: dict[str, dict[str, tuple[str, bool, str]]] = {
    "matches": {
        "match_ref": ("string", True, "source:id"), "source": ("string", True, "adapter"), "licence": ("string", True, "terms it came under"),
        "competition": ("string", False, ""), "season": ("string", False, ""), "date": ("datetime64[ns]", True, "kick-off date"),
        "home_team": ("string", True, ""), "away_team": ("string", True, ""), "home_score": ("Int64", False, ""), "away_score": ("Int64", False, ""),
        "known_at": ("datetime64[ns]", True, "when this row could first be known"),
    },
    "appearances": {
        "match_ref": ("string", True, ""), "player_ref": ("string", True, "source:id"), "player_name": ("string", False, ""),
        "team": ("string", True, ""), "starter": ("boolean", False, ""), "minutes": ("Float64", False, ""), "position": ("string", False, "the slot as the source names it"),
        "source": ("string", True, ""), "licence": ("string", True, ""), "known_at": ("datetime64[ns]", True, ""),
    },
    "events": {
        "match_ref": ("string", True, ""), "period": ("Int64", True, ""), "t": ("Float64", True, "seconds into the period"),
        "team": ("string", False, ""), "player_ref": ("string", False, ""), "type": ("string", True, "kloppy's event type, lower case"),
        "result": ("string", False, ""), "x0": ("Float64", False, "m"), "y0": ("Float64", False, "m"), "x1": ("Float64", False, "m"), "y1": ("Float64", False, "m"),
        "source": ("string", True, ""), "licence": ("string", True, ""), "known_at": ("datetime64[ns]", True, ""),
    },
    "tracking": {
        "match_ref": ("string", True, ""), "period": ("Int64", True, ""), "frame": ("Int64", True, ""), "t": ("Float64", True, "s"),
        "player_ref": ("string", True, "source:id, or 'ball'"), "team": ("string", False, ""), "x": ("Float64", True, "m"), "y": ("Float64", True, "m"),
        "source": ("string", True, ""), "licence": ("string", True, ""), "known_at": ("datetime64[ns]", True, ""),
    },
    "physical": {
        "player_ref": ("string", True, ""), "date": ("datetime64[ns]", True, ""), "session": ("string", True, "match | training"),
        "minutes": ("Float64", False, ""), "distance_m": ("Float64", False, ""), "hsr_m": ("Float64", False, "high-speed running, as the source defines it"),
        "sprint_m": ("Float64", False, ""), "sprints": ("Int64", False, ""), "top_speed_kmh": ("Float64", False, ""),
        "accels": ("Int64", False, ""), "decels": ("Int64", False, ""),
        "source": ("string", True, ""), "licence": ("string", True, ""), "known_at": ("datetime64[ns]", True, ""),
    },
    "availability": {
        "player_ref": ("string", True, ""), "date_from": ("datetime64[ns]", True, ""), "date_to": ("datetime64[ns]", False, "open if still out"),
        "status": ("string", True, "available | injured | ill | suspended | national team"),
        "source": ("string", True, ""), "licence": ("string", True, ""), "known_at": ("datetime64[ns]", True, ""),
    },
    "reports": {
        "player_ref": ("string", True, ""), "date": ("datetime64[ns]", True, ""), "scout": ("string", True, ""), "match_ref": ("string", False, ""),
        "grade": ("string", False, "the club's own scale, kept as written"), "role_seen": ("string", False, ""), "text": ("string", False, ""),
        "source": ("string", True, ""), "licence": ("string", True, ""), "known_at": ("datetime64[ns]", True, ""),
    },
    "identity_links": {
        "source": ("string", True, "provider"), "external_id": ("string", True, ""), "reep_id": ("string", False, ""),
        "tm_id": ("string", False, "our key"), "matchdata_id": ("string", False, ""), "confidence": ("Float64", True, "0..1"),
        "method": ("string", True, "how the link was made: provider id in Reep, Reep's name+birth date match, ours"),
    },
}


def conform(df: pd.DataFrame, table: str) -> pd.DataFrame:
    """Cast to the contract's types, add missing optional columns, fail loudly on a missing required one."""
    spec = TABLES[table]
    missing = [c for c, (_, req, _) in spec.items() if req and c not in df.columns]
    if missing:
        raise ValueError(f"{table}: missing required columns {missing}")
    out = pd.DataFrame(index=df.index)
    for c, (dtype, _, _) in spec.items():
        out[c] = df[c].astype(dtype) if c in df.columns else pd.Series(pd.NA, index=df.index, dtype=dtype)
    return out


def check(df: pd.DataFrame, table: str) -> dict:
    """What a steward reads before a source is trusted: rows, required columns filled, coordinate range."""
    spec, rep = TABLES[table], {"table": table, "rows": int(len(df))}
    rep["required_filled"] = {c: round(float(df[c].notna().mean()), 3) for c, (_, req, _) in spec.items() if req and len(df)}
    for c in ("x", "x0", "x1"):
        if c in df and df[c].notna().any():
            rep[f"{c}_in_pitch"] = round(float(df[c].between(-2, 107).mean()), 3)
    for c in ("y", "y0", "y1"):
        if c in df and df[c].notna().any():
            rep[f"{c}_in_pitch"] = round(float(df[c].between(-2, 70).mean()), 3)
    return rep
