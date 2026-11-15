"""DFL / IDSSE open data -> Promesse lake: official Bundesliga tracking at 25 Hz, losslessly compacted.

Source: Bassek, Rein, Weber & Memmert (2025), "An integrated dataset of spatiotemporal and event data in elite soccer",
Scientific Data; figshare 28196177, CC-BY 4.0. Seven matches (Bundesliga and 2. Bundesliga), each with match
information, raw events and positions of every player, referee and the ball at 25 frames per second.

Tables (lake/dfl/):
  positions/match=<id>/   one row per object per frame: section, team, person, frame, x, y, z, speed, acceleration,
                          distance, minute, ball possession / status (every attribute DFL sends, as numbers)
  frame_times/match=<id>/ frame number -> timestamp, once per frame (instead of once per object per frame)
  events                  every raw event, flattened: event attributes plus the nested play / pass / shot attributes
The small match-information and event XML files stay in open/dfl-idsse; only the large position files are deleted,
each one after its rows were counted back from disk.

Run (Patcher venv, from this folder):  python dfl.py all
"""
from __future__ import annotations

import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd
from lxml import etree

from common import LAKE, OPEN, delete_raw, done, log, rows_in, write_part

SRC = OPEN / "dfl-idsse"
OUT = LAKE / "dfl"
NUM = {"N": np.int32, "X": np.float32, "Y": np.float32, "Z": np.float32, "S": np.float32, "A": np.float32, "D": np.float32,
       "M": np.int16, "BallPossession": np.int8, "BallStatus": np.int8}


def positions(path: str) -> dict:
    match = path.split("_")[-1].replace(".xml", "")
    cols = {k: [] for k in ("section", "team", "person", *NUM)}
    times, seen_t, frames = [], set(), 0
    cur = {}
    for ev, el in etree.iterparse(path, events=("start", "end"), huge_tree=True):
        if ev == "start" and el.tag == "FrameSet":
            cur = {"section": el.get("GameSection"), "team": el.get("TeamId"), "person": el.get("PersonId")}
        elif ev == "end" and el.tag == "Frame":
            a = el.attrib
            cols["section"].append(cur["section"])
            cols["team"].append(cur["team"])
            cols["person"].append(cur["person"])
            for k in NUM:
                v = a.get(k)
                cols[k].append(float(v) if v is not None else np.nan)
            key = (cur["section"], a.get("N"))
            if key not in seen_t:
                seen_t.add(key)
                times.append({"section": cur["section"], "frame": int(a.get("N")), "t": a.get("T")})
            frames += 1
            el.clear()
        elif ev == "end" and el.tag == "FrameSet":
            el.clear()
    df = pd.DataFrame(cols)
    for c in ("section", "team", "person"):
        df[c] = df[c].astype("category")
    for k, t in NUM.items():
        df[k] = df[k].astype(np.float32) if t is np.float32 or df[k].isna().any() else df[k].astype(t)
    df = df.rename(columns={"N": "frame", "X": "x", "Y": "y", "Z": "z", "S": "speed", "A": "acc", "D": "dist", "M": "minute",
                            "BallPossession": "ball_possession", "BallStatus": "ball_status"})
    write_part(df, OUT / "positions" / f"match={match}", "part-000")
    write_part(pd.DataFrame(times), OUT / "frame_times" / f"match={match}", "part-000")
    return {"match": match, "path": path, "frames_parsed": frames, "frame_tags_in_file": count_frames(path)}


def count_frames(path: str) -> int:
    """Count '<Frame ' tags straight from the bytes: an independent check on the parser."""
    pat, n, prev = b"<Frame ", 0, b""
    with open(path, "rb") as f:
        while chunk := f.read(64 << 20):
            buf = prev + chunk
            n += buf.count(pat)
            prev = buf[-(len(pat) - 1):]                    # too short to hold a whole tag: nothing is counted twice
    return n


def events() -> int:
    rows = []
    for p in sorted(SRC.glob("DFL_03_02_events_raw_*.xml")):
        match = p.stem.split("_")[-1]
        for ev in etree.parse(str(p)).getroot().iter("Event"):
            r = {"match": match, **{f"event.{k}": v for k, v in ev.attrib.items()}}
            path = []
            for d in ev.iterdescendants():
                path.append(d.tag)
                r.update({f"{d.tag}.{k}": v for k, v in d.attrib.items()})
            r["type"] = "/".join(path)
            rows.append(r)
    write_part(pd.DataFrame(rows).astype("string"), OUT, "events")
    return len(rows)


def all_data() -> None:
    files = sorted(str(p) for p in SRC.glob("DFL_04_03_positions_raw_observed_*.xml"))
    n_events = events()
    print(f"dfl events: {n_events:,}", flush=True)
    with ProcessPoolExecutor(max_workers=2) as pool:
        futs = [pool.submit(positions, f) for f in files if not done("dfl", f.split("_")[-1])]
        for f in as_completed(futs):
            r = f.result()
            on_disk = rows_in(OUT / "positions" / f"match={r['match']}")
            ok = r["frames_parsed"] == r["frame_tags_in_file"] == on_disk
            log({"source": "dfl", "batch": r["match"], "step": "distilled", "frames": on_disk, "frame_tags": r["frame_tags_in_file"]})
            if not ok:
                print(f"{r['match']}: MISMATCH parsed {r['frames_parsed']} / tags {r['frame_tags_in_file']} / disk {on_disk}", flush=True)
                continue
            log({"source": "dfl", "batch": r["match"], "step": "verified"})
            from pathlib import Path
            delete_raw(Path(r["path"]), "dfl", r["match"])
            print(f"{r['match']}: {on_disk:,} object-frames verified, raw positions deleted", flush=True)
    print("dfl done", flush=True)


if __name__ == "__main__":
    {"all": all_data}[sys.argv[1]]()
