"""StatsBomb open data -> Promesse lake: match-day event data, compact and lossless enough to drop the raw JSON.

Source: StatsBomb open data (github.com/statsbomb/open-data), free for research with attribution: their licence and
README are copied next to the tables. Every event keeps its scalar fields as columns (dotted names, e.g. pass.length,
shot.statsbomb_xg); locations become numeric x / y (and z); nested lists stay as JSON text so nothing is lost.

Tables (lake/statsbomb/):
  competitions, matches, lineups (one row per player per match, positions held as JSON)
  events/competition_id=../season_id=../      one row per event
  shot_frames/...                             the players around each shot (StatsBomb freeze frames)
  frames_360/...                              360 data: every visible player at each event (teammate, actor, keeper, x, y)
  visible_area/...                            the camera's visible polygon per 360 event (JSON)

Run (Patcher venv, from this folder):  python statsbomb.py all      (distil -> verify per match -> delete the raw clone)
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd

from common import LAKE, OPEN, delete_raw, done, log, rows_in, write_part

SRC = OPEN / "statsbomb-open-data"
D = SRC / "data"
OUT = LAKE / "statsbomb"


def jsonify(df: pd.DataFrame) -> pd.DataFrame:
    """Lists / dicts -> JSON text; all-null and mixed object columns -> string, so every part shares simple types."""
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].map(lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else (None if v is None or (isinstance(v, float) and np.isnan(v)) else str(v)))
        elif df[c].isna().all():
            df[c] = df[c].astype("string")
    return df


def load_list(path, key: str) -> tuple[list, int]:
    """A JSON list, record by record when the file is damaged (one published 360 file holds a block of NUL bytes):
    every intact record is kept, a broken one is dropped and counted, parsing resumes at the next record."""
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text), 0
    except json.JSONDecodeError:
        pass
    dec, items, dropped = json.JSONDecoder(), [], 0
    start = re.compile(r'\{\s*"' + key + '"')
    i = text.index("[") + 1
    while True:
        i = re.compile(r"[\s,]*").match(text, i).end()
        if i >= len(text) or text[i] == "]":
            break
        try:
            obj, i = dec.raw_decode(text, i)
            items.append(obj)
        except json.JSONDecodeError:
            dropped += 1
            m = start.search(text, i + 1)
            if not m:
                break
            i = m.start()
    return items, dropped


def split_xyz(df: pd.DataFrame, col: str, prefix: str) -> None:
    if col in df.columns:
        v = df[col].map(lambda a: a if isinstance(a, list) else [None, None, None])
        df[f"{prefix}x"] = v.map(lambda a: a[0] if len(a) > 0 else None).astype(float)
        df[f"{prefix}y"] = v.map(lambda a: a[1] if len(a) > 1 else None).astype(float)
        if v.map(len).max() > 2:
            df[f"{prefix}z"] = v.map(lambda a: a[2] if len(a) > 2 else None).astype(float)
        df.drop(columns=col, inplace=True)


def distil_season(comp: int, season: int, match_ids: list[int] | None = None) -> dict:
    """One competition-season, or (comp 0, season 0) the event files no upstream season listing mentions."""
    if match_ids is None:
        match_ids = [m["match_id"] for m in json.loads((D / "matches" / str(comp) / f"{season}.json").read_text(encoding="utf-8"))]
    part = f"competition_id={comp}/season_id={season}"
    ev_all, shots, vis, counts = [], [], [], {"matches": 0, "events": 0, "shot_frames": 0, "frames_360": 0, "missing": 0}
    f360 = {k: [] for k in ("match_id", "event_uuid", "teammate", "actor", "keeper", "x", "y")}   # columns, not millions of dicts
    for mid in match_ids:
        p = D / "events" / f"{mid}.json"
        if not p.exists():
            counts["missing"] += 1
            continue
        raw, lost = load_list(p, "id")
        counts["dropped_events"] = counts.get("dropped_events", 0) + lost
        ev = pd.json_normalize(raw, sep=".")
        ev.insert(0, "match_id", mid)
        for col in [c for c in ev.columns if c.endswith("freeze_frame") and c.startswith("shot")]:
            for _, r in ev[["id", col]].dropna().iterrows():
                for f in r[col]:
                    loc = f.get("location") or [None, None]
                    shots.append({"match_id": mid, "event_id": r["id"], "player_id": (f.get("player") or {}).get("id"),
                                  "player": (f.get("player") or {}).get("name"), "position": (f.get("position") or {}).get("name"),
                                  "teammate": f.get("teammate"), "x": loc[0], "y": loc[1]})
            ev.drop(columns=col, inplace=True)
        split_xyz(ev, "location", "")
        for col in [c for c in ev.columns if c.endswith("end_location")]:
            split_xyz(ev, col, col.replace("end_location", "end_"))
        ev_all.append(ev)
        counts["matches"] += 1
        counts["events"] += len(raw)
        p360 = D / "three-sixty" / f"{mid}.json"
        if p360.exists():
            frames, lost = load_list(p360, "event_uuid")
            counts["dropped_360_records"] = counts.get("dropped_360_records", 0) + lost
            for fr in frames:
                vis.append({"match_id": mid, "event_uuid": fr["event_uuid"], "visible_area": json.dumps(fr.get("visible_area"))})
                for f in fr.get("freeze_frame") or []:
                    loc = f.get("location") or [None, None]
                    for k, v in (("match_id", mid), ("event_uuid", fr["event_uuid"]), ("teammate", f.get("teammate")),
                                 ("actor", f.get("actor")), ("keeper", f.get("keeper")), ("x", loc[0]), ("y", loc[1])):
                        f360[k].append(v)
    counts["shot_frames"], counts["frames_360"] = len(shots), len(f360["x"])
    if ev_all:
        write_part(jsonify(pd.concat(ev_all, ignore_index=True)), OUT / "events" / part, "part-000")
    if shots:
        write_part(pd.DataFrame(shots), OUT / "shot_frames" / part, "part-000")
    if f360["x"]:
        fr = pd.DataFrame(f360)
        fr["event_uuid"] = fr.event_uuid.astype("category")
        fr[["x", "y"]] = fr[["x", "y"]].astype("float32")
        write_part(fr, OUT / "frames_360" / part, "part-000")
        write_part(pd.DataFrame(vis), OUT / "visible_area" / part, "part-000")
    return {"comp": comp, "season": season, "part": part, **counts}


def all_data(workers: int = 2) -> None:
    if done("statsbomb", "open-data"):
        print("statsbomb already distilled", flush=True)
        return
    comps = json.loads((D / "competitions.json").read_text(encoding="utf-8"))
    write_part(pd.DataFrame(comps), OUT, "competitions")
    seasons = sorted({(c["competition_id"], c["season_id"]) for c in comps if (D / "matches" / str(c["competition_id"]) / f"{c['season_id']}.json").exists()})
    mt = []
    for comp, season in seasons:
        for m in json.loads((D / "matches" / str(comp) / f"{season}.json").read_text(encoding="utf-8")):
            mt.append(m)
    write_part(jsonify(pd.json_normalize(mt, sep=".")), OUT, "matches")
    lu = []
    for p in (D / "lineups").glob("*.json"):
        for team in json.loads(p.read_text(encoding="utf-8")):
            for pl in team.get("lineup") or []:
                pos = pl.get("positions") or []
                lu.append({"match_id": int(p.stem), "team_id": team["team_id"], "team": team["team_name"], "player_id": pl["player_id"],
                           "player": pl["player_name"], "nickname": pl.get("player_nickname"), "jersey": pl.get("jersey_number"),
                           "country": (pl.get("country") or {}).get("name"), "started": any(x.get("start_reason") == "Starting XI" for x in pos),
                           "first_position": pos[0]["position"] if pos else None, "positions": json.dumps(pos), "cards": json.dumps(pl.get("cards") or [])})
    write_part(pd.DataFrame(lu), OUT, "lineups")

    # The open-data repo also ships event files for matches no season listing mentions (274, e.g. 7298
    # and 3890259-3890267). Kept as their own batch, competition_id=0 / season_id=0: events and 360 data, no match sheet.
    listed = {m["match_id"] for m in mt}
    unlisted = sorted(int(f.stem) for f in (D / "events").glob("*.json") if int(f.stem) not in listed)
    print(f"  {len(unlisted)} event files without a season listing -> competition_id=0/season_id=0", flush=True)

    results = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(distil_season, c, s) for c, s in seasons]
        if unlisted:
            futs.append(pool.submit(distil_season, 0, 0, unlisted))
        for k, f in enumerate(as_completed(futs)):
            r = f.result()
            results.append(r)
            print(f"  {k + 1}/{len(futs)} {r['part']}: {r['matches']} matches, {r['events']:,} events, {r['frames_360']:,} 360 rows", flush=True)

    # Verify from disk: every event file read back, every 360 frame written.
    ev_files = len(list((D / "events").glob("*.json")))
    n_matches, n_events = sum(r["matches"] for r in results), sum(r["events"] for r in results)
    n_360 = sum(r["frames_360"] for r in results)
    events_ok = rows_in(OUT / "events") == n_events
    frames_ok = rows_in(OUT / "frames_360") == n_360 if n_360 else True
    ok = events_ok and frames_ok and n_matches == ev_files
    log({"source": "statsbomb", "batch": "open-data", "step": "distilled", "matches": n_matches, "event_files": ev_files,
         "events": n_events, "frames_360": n_360, "shot_frames": sum(r["shot_frames"] for r in results), "lineup_rows": len(lu),
         "missing_event_files": sum(r["missing"] for r in results), "unlisted_matches": len(unlisted),
         "dropped_damaged_records": {"events": sum(r.get("dropped_events", 0) for r in results), "frames_360_events": sum(r.get("dropped_360_records", 0) for r in results)}})
    if not ok:
        raise RuntimeError(f"statsbomb verification failed: {n_matches} matches vs {ev_files} files, events on disk {rows_in(OUT / 'events')} vs {n_events}")
    for f in ("LICENSE.pdf", "README.md"):
        if (SRC / f).exists():
            shutil.copy2(SRC / f, OUT / f"STATSBOMB_{f}")
    log({"source": "statsbomb", "batch": "open-data", "step": "verified"})
    print(f"statsbomb verified: {n_matches:,} matches, {n_events:,} events, {n_360:,} 360 rows", flush=True)
    delete_raw(SRC, "statsbomb", "open-data")
    print("statsbomb raw clone deleted", flush=True)


if __name__ == "__main__":
    {"all": all_data}[sys.argv[1]]()
