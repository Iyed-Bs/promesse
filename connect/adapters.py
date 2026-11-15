"""Adapters: one per source a club (or the open world) can hand us, each writing contract tables (connect/contract.py).

Event and tracking feeds go through kloppy (PySport, BSD-3), which already reads 15 providers' formats (Hudl StatsBomb,
Wyscout, Stats Perform/Opta, Sportec/DFL, Impect, SkillCorner, Second Spectrum, TRACAB, Metrica, PFF FC, HawkEye...),
so an adapter here is a thin mapping from kloppy's model to the contract. GPS, availability and scouting reports come
as the CSV exports clubs already make; their column names are a mapping a club fills in once (presets below).

Coordinates: kloppy's normalised pitch (0..1 both ways) scaled to 105 x 68 m. Attack direction: as kloppy delivers it
for that provider (stated per adapter in the run report).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd

from connect.contract import conform

REGISTRY: dict[str, dict] = {}


def adapter(name: str, kind: str, provider: str, licence: str, reads: str):
    """register an adapter: what it is called, which tables it writes, whose format it reads, under which terms"""
    def wrap(fn: Callable):
        REGISTRY[name] = {"fn": fn, "kind": kind, "provider": provider, "licence": licence, "reads": reads}
        return fn
    return wrap


def _day(d) -> pd.Timestamp:
    """a date as a naive day (providers send some with a time zone)"""
    t = pd.Timestamp(d)
    return (t.tz_convert("UTC").tz_localize(None) if t.tzinfo else t).normalize()


def _ref(source: str, x) -> object:
    return pd.NA if x is None or (isinstance(x, float) and pd.isna(x)) or str(x) in ("", "None", "nan") else f"{source}:{x}"


def kloppy_events(ds, source: str, licence: str, match_id: str, date) -> dict[str, pd.DataFrame]:
    """a kloppy EventDataset -> events + appearances (+ the match row)"""
    df = ds.to_df()
    pid = df.get("player_id")
    ev = pd.DataFrame({
        "match_ref": f"{source}:{match_id}", "period": df["period_id"], "t": pd.to_timedelta(df["timestamp"]).dt.total_seconds(),
        "team": df.get("team_id").astype(str), "player_ref": [_ref(source, x) for x in (pid if pid is not None else [None] * len(df))],
        "type": df["event_type"].astype(str).str.lower(), "result": df.get("result").astype(str).str.lower() if "result" in df else pd.NA,
        "x0": df.get("coordinates_x") * 105, "y0": df.get("coordinates_y") * 68,
        "x1": df["end_coordinates_x"] * 105 if "end_coordinates_x" in df else pd.NA,
        "y1": df["end_coordinates_y"] * 68 if "end_coordinates_y" in df else pd.NA,
        "source": source, "licence": licence, "known_at": _day(date),
    })
    teams = ds.metadata.teams
    app = pd.DataFrame([{
        "match_ref": f"{source}:{match_id}", "player_ref": f"{source}:{p.player_id}", "player_name": p.full_name or p.name,
        "team": t.name, "starter": bool(p.starting), "position": str(p.starting_position) if p.starting_position else pd.NA,
        "source": source, "licence": licence, "known_at": _day(date)} for t in teams for p in t.players])
    match = pd.DataFrame([{"match_ref": f"{source}:{match_id}", "source": source, "licence": licence, "date": _day(date),
                           "home_team": teams[0].name, "away_team": teams[1].name, "known_at": _day(date)}])
    return {"events": conform(ev, "events"), "appearances": conform(app, "appearances"), "matches": conform(match, "matches")}


def kloppy_tracking(ds, source: str, licence: str, match_id: str, date) -> dict[str, pd.DataFrame]:
    """a kloppy TrackingDataset -> tracking, long (one row per player per frame) + appearances"""
    df = ds.to_df()
    rows = []
    xs = [c for c in df.columns if c.endswith("_x")]
    for c in xs:
        who = c[:-2]
        sub = df[["period_id", "frame_id", "timestamp", c, who + "_y"]].dropna()
        rows.append(pd.DataFrame({"match_ref": f"{source}:{match_id}", "period": sub["period_id"], "frame": sub["frame_id"],
                                  "t": pd.to_timedelta(sub["timestamp"]).dt.total_seconds(),
                                  "player_ref": "ball" if who == "ball" else f"{source}:{who}",
                                  "x": sub[c] * 105, "y": sub[who + "_y"] * 68}))
    tr = pd.concat(rows, ignore_index=True).assign(source=source, licence=licence, known_at=_day(date))
    teams = ds.metadata.teams
    app = pd.DataFrame([{"match_ref": f"{source}:{match_id}", "player_ref": f"{source}:{p.player_id}", "player_name": p.full_name or p.name,
                         "team": t.name, "starter": bool(p.starting), "source": source, "licence": licence, "known_at": _day(date)}
                        for t in teams for p in t.players])
    return {"tracking": conform(tr, "tracking"), "appearances": conform(app, "appearances")}


# ── event feeds ───────────────────────────────────────────────────────────────────────────────────────────────────
@adapter("impect", "events", "Impect", "Impect open data: research only, credit Impect, no redistribution", "events_<id>.json + lineups_<id>.json + squads/players per season")
def impect(root: Path, match_id: str, date=None) -> dict[str, pd.DataFrame]:
    from kloppy import impect as K
    it = next((root / "squads").glob("*.json"))
    pl = next((root / "players").glob("*.json"))
    ds = K.load(event_data=str(root / "events" / f"events_{match_id}.json"), lineup_data=str(root / "lineups" / f"lineups_{match_id}.json"),
                squads_data=str(it), players_data=str(pl))
    return kloppy_events(ds, "impect", REGISTRY["impect"]["licence"], match_id, date or ds.metadata.date or "2023-08-01")


@adapter("dfl", "events+tracking", "Sportec Solutions / DFL", "IDSSE open data, CC BY 4.0", "DFL_02_01 match information + DFL_03_02 events (+ DFL_04_03 positions)")
def dfl(root: Path, match_id: str, date=None, tracking: bool = False) -> dict[str, pd.DataFrame]:
    from kloppy import sportec as K
    meta = next(root.glob(f"DFL_02_01_matchinformation_*_{match_id}.xml"))
    out = kloppy_events(K.load_event(event_data=str(next(root.glob(f"DFL_03_02_events_raw_*_{match_id}.xml"))), meta_data=str(meta)),
                        "dfl", REGISTRY["dfl"]["licence"], match_id, date or "2022-08-01")
    raw = list(root.glob(f"DFL_04_03_positions_raw_observed_*_{match_id}.xml"))
    if tracking and raw:
        tr = kloppy_tracking(K.load_tracking(raw_data=str(raw[0]), meta_data=str(meta), sample_rate=1 / 25, limit=1500),
                             "dfl", REGISTRY["dfl"]["licence"], match_id, date or "2022-08-01")
        out["tracking"] = tr["tracking"]
    return out


@adapter("metrica", "events+tracking", "Metrica Sports", "Metrica sample data (anonymised)", "Sample_Game_3: events JSON, metadata XML, tracking EPTS")
def metrica(root: Path, game: str = "Sample_Game_3", date=None) -> dict[str, pd.DataFrame]:
    from kloppy import metrica as K
    d = root / game
    meta = str(d / f"{game}_metadata.xml")
    out = kloppy_events(K.load_event(event_data=str(d / f"{game}_events.json"), meta_data=meta), "metrica",
                        REGISTRY["metrica"]["licence"], game, date or "2020-01-01")
    tr = kloppy_tracking(K.load_tracking_epts(meta_data=meta, raw_data=str(d / f"{game}_tracking.txt"), sample_rate=1 / 25, limit=1500),
                         "metrica", REGISTRY["metrica"]["licence"], game, date or "2020-01-01")
    out["tracking"] = tr["tracking"]
    return out


# ── tracking ─────────────────────────────────────────────────────────────────────────────────────────────────────
@adapter("skillcorner", "tracking", "SkillCorner", "SkillCorner open data, MIT", "<id>_match.json + <id>_tracking_extrapolated.jsonl (broadcast tracking, 10 fps)")
def skillcorner(root: Path, match_id: str, date=None) -> dict[str, pd.DataFrame]:
    from kloppy import skillcorner as K
    d = root / match_id
    ds = K.load(meta_data=str(d / f"{match_id}_match.json"), raw_data=str(d / f"{match_id}_tracking_extrapolated.jsonl"), sample_rate=1 / 10, limit=1500)
    return kloppy_tracking(ds, "skillcorner", REGISTRY["skillcorner"]["licence"], match_id, date or ds.metadata.date or "2024-10-01")


# ── a club's own exports: the columns are a mapping it fills in once ─────────────────────────────────────────────
# these are examples of the mapping, not any vendor's documented format; a club checks them against its export
GPS_PRESETS = {
    "generic": {"player": "player_id", "date": "date", "session": "session_type", "minutes": "duration_min", "distance_m": "total_distance_m",
                "hsr_m": "hsr_distance_m", "sprint_m": "sprint_distance_m", "sprints": "sprint_count", "top_speed_kmh": "max_speed_kmh",
                "accels": "accelerations", "decels": "decelerations"},
}


@adapter("gps_csv", "physical", "the club's GPS system (vest exports)", "the club's own data, stays with the club", "one row per player per session, mapped by GPS_PRESETS")
def gps_csv(path: Path, preset: str = "generic", source: str = "gps") -> dict[str, pd.DataFrame]:
    m = GPS_PRESETS[preset]
    raw = pd.read_csv(path)
    df = pd.DataFrame({k: raw[v] for k, v in m.items() if v in raw.columns})
    df["player_ref"] = [_ref(source, x) for x in df.pop("player")]
    df["date"] = pd.to_datetime(df["date"])
    df = df.assign(source=source, licence=REGISTRY["gps_csv"]["licence"], known_at=df["date"])
    return {"physical": conform(df, "physical")}


@adapter("availability_csv", "availability", "the club's medical system (status only)", "the club's own data, stays with the club", "player, from, to, status; never a diagnosis")
def availability_csv(path: Path, source: str = "medical") -> dict[str, pd.DataFrame]:
    raw = pd.read_csv(path)
    keep = {"available", "injured", "ill", "suspended", "national team"}
    df = pd.DataFrame({"player_ref": [_ref(source, x) for x in raw["player_id"]], "date_from": pd.to_datetime(raw["from"]),
                       "date_to": pd.to_datetime(raw.get("to"), errors="coerce"), "status": raw["status"].str.lower()})
    bad = ~df["status"].isin(keep)
    if bad.any():
        raise ValueError(f"availability: statuses outside the contract ({sorted(df.loc[bad, 'status'].unique())}); diagnoses never come in")
    df = df.assign(source=source, licence=REGISTRY["availability_csv"]["licence"], known_at=pd.to_datetime(raw.get("entered", raw["from"])))
    return {"availability": conform(df, "availability")}


@adapter("reports_csv", "reports", "the club's scouting reports", "the club's own data, stays with the club", "player, date, scout, grade, role seen, text")
def reports_csv(path: Path, source: str = "scouting") -> dict[str, pd.DataFrame]:
    raw = pd.read_csv(path)
    df = pd.DataFrame({"player_ref": [_ref(source, x) for x in raw["player_id"]], "date": pd.to_datetime(raw["date"]), "scout": raw["scout"],
                       "match_ref": raw.get("match"), "grade": raw.get("grade"), "role_seen": raw.get("role"), "text": raw.get("text")})
    df = df.assign(source=source, licence=REGISTRY["reports_csv"]["licence"], known_at=df["date"])
    return {"reports": conform(df, "reports")}
