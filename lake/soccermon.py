"""SoccerMon -> Promesse lake: training-day data, distilled archive by archive.

Source: SoccerMon (Midoglu et al., Scientific Data 2024), two elite women's teams (Norway, 2020-2021), CC-BY 4.0,
Zenodo record 10033832. Objective data: one Parquet file per player per day, GPS at 10 Hz (position, Doppler speed,
heart rate, signal quality) and an inertial unit at 100 Hz (accelerometer, gyroscope). Subjective data: wellness,
session RPE, injuries, illness, self-rated game performance.

What we keep (enough to retrain any load model without the raw files):
  seconds   one row per player-second: position in metres, mean / peak speed, distance, high-speed and sprint
            distance, PlayerLoad (accelerometer), peak acceleration in g, effort starts, heart rate, GPS quality
  minutes   one row per player-minute: the same, summed
  sessions  one row per player-day: totals, speed-zone distances, efforts, peak 1/3/5-minute intensity, quality flags
  wellness  long table (player, date, metric, value) + injuries, illness, game performance, session RPE
  player_day  the modelling table: wellness + sRPE load + GPS load + injury / illness flags per player per day

Thresholds (all in m/s, documented so they can be changed from the seconds table): high-speed 5.5 (19.8 km/h),
sprint 7.0 (25.2 km/h); accelerations / decelerations at 2 and 3 m/s2 held for 0.5 s; sprints held for 1 s.

Run (Patcher venv, from this folder):
    python soccermon.py subjective          wellness tables (small, instant)
    python soccermon.py all                 every GPS archive: download -> distil -> verify -> delete -> next
"""
from __future__ import annotations

import io
import json
import sys
import threading
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import requests

from common import LAKE, OPEN, delete_raw, done, log, rows_in, write_part

SRC = OPEN / "soccermon"
OUT = LAKE / "soccermon"
ZENODO = "https://zenodo.org/api/records/10033832"
ARCHIVES = ["objective-TeamB-2020.zip", "objective-TeamA-2020.zip", "objective-TeamB-2021.zip", "objective-TeamA-2021.zip"]
HSR, SPRINT = 5.5, 7.0
ZONES = [0, 2.0, 4.0, 5.5, 7.0, 99]                     # walk / jog / run / high-speed / sprint
COLS = ["player_name", "time", "lat", "lon", "speed", "heart_rate", "hdop", "num_satellites", "inst_acc_impulse",
        "accl_x", "accl_y", "accl_z"]


# ── One player-day ────────────────────────────────────────────────────────────────────────────────────────────
def run_starts(mask: np.ndarray, min_len: int) -> np.ndarray:
    """Indices where a run of True lasting at least min_len samples begins."""
    m = np.concatenate([[False], mask, [False]]).astype(np.int8)
    d = np.diff(m)
    starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
    return starts[(ends - starts) >= min_len]


def distil_member(zip_path: str, name: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    with zipfile.ZipFile(zip_path) as z:
        tbl = pq.read_table(io.BytesIO(z.read(name)), columns=COLS)
    date = pd.Timestamp(Path(name).parts[2])
    session = {"member": name, "date": date, "rows_raw": tbl.num_rows}
    if tbl.num_rows == 0:
        return pd.DataFrame(), pd.DataFrame(), {**session, "status": "empty"}
    # Text columns stay in Arrow (no 700,000 Python strings per file): the player id is constant, time is parsed in place.
    player = tbl.column("player_name")[0].as_py()
    hms = pc.split_pattern(tbl.column("time"), ":")
    part = lambda i: pc.cast(pc.list_element(hms, i), pa.float64()).to_numpy()
    t = part(0) * 3600 + part(1) * 60 + part(2)
    df = tbl.drop_columns(["player_name", "time"]).to_pandas()

    # GPS rows repeat inside each 0.1 s (the IMU samples at 100 Hz): one row per GPS tick.
    gps = df[["lat", "lon", "speed", "heart_rate", "hdop", "num_satellites"]].assign(ts=np.round(t, 1))
    gps = gps.groupby("ts", sort=True).first().reset_index()
    ts = gps.ts.to_numpy()
    speed = np.clip(gps.speed.to_numpy(), 0, 11.0)
    dtv = np.diff(ts, prepend=ts[0] - 0.1).clip(0, 1.0)
    dist = speed * dtv
    smooth = pd.Series(speed).rolling(5, center=True, min_periods=1).mean().to_numpy()
    acc = np.clip(np.gradient(smooth, ts) if len(ts) > 1 else np.zeros_like(smooth), -10, 10)
    lat0, lon0 = np.nanmedian(gps.lat), np.nanmedian(gps.lon)
    ok = (gps.lat != 0) & (gps.lon != 0)
    x = np.where(ok, (gps.lon - lon0) * np.cos(np.radians(lat0)) * 111_320, np.nan)
    y = np.where(ok, (gps.lat - lat0) * 110_540, np.nan)
    sec = np.floor(ts).astype(np.int32)

    tick = pd.DataFrame({"second": sec, "x": x, "y": y, "speed": speed, "dist": dist,
                         "dist_hsr": np.where(speed > HSR, dist, 0.0), "dist_sprint": np.where(speed > SPRINT, dist, 0.0),
                         "hr": gps.heart_rate.where(gps.heart_rate > 0).to_numpy(), "hdop": gps.hdop, "sats": gps.num_satellites})
    events = {"acc2": run_starts(acc > 2, 5), "acc3": run_starts(acc > 3, 5), "dec2": run_starts(acc < -2, 5),
              "dec3": run_starts(acc < -3, 5), "sprints": run_starts(speed > SPRINT, 10), "hsr_efforts": run_starts(speed > HSR, 10)}

    # Inertial unit at 100 Hz: PlayerLoad (sum of acceleration change, /100) and the hardest impact each second.
    a = df[["accl_x", "accl_y", "accl_z"]].to_numpy(dtype=np.float32)
    jerk = np.sqrt((np.diff(a, axis=0, prepend=a[:1]) ** 2).sum(axis=1)) / 100.0
    mag = np.sqrt((a ** 2).sum(axis=1))
    imu = pd.DataFrame({"second": np.floor(t).astype(np.int32), "pl": jerk, "acc_peak_g": mag,
                        "impulse": df.inst_acc_impulse.to_numpy()}).groupby("second").agg(
        pl=("pl", "sum"), acc_peak_g=("acc_peak_g", "max"), impulse_max=("impulse", "max"))

    s = tick.groupby("second").agg(x=("x", "mean"), y=("y", "mean"), speed_mean=("speed", "mean"), speed_max=("speed", "max"),
                                   dist=("dist", "sum"), dist_hsr=("dist_hsr", "sum"), dist_sprint=("dist_sprint", "sum"),
                                   hr=("hr", "mean"), hdop=("hdop", "mean"), sats=("sats", "mean"))
    s = s.join(imu, how="outer")
    for k, idx in events.items():
        s[k] = pd.Series(sec[idx]).value_counts().reindex(s.index).fillna(0).astype(np.int16).to_numpy() if len(idx) else 0
    s = s.reset_index()
    s.insert(0, "player", player)
    s.insert(1, "date", date)
    f32 = ["x", "y", "speed_mean", "speed_max", "dist", "dist_hsr", "dist_sprint", "hr", "hdop", "sats", "pl", "acc_peak_g", "impulse_max"]
    s[f32] = s[f32].astype(np.float32)

    m = s.assign(minute=(s.second // 60).astype(np.int32)).groupby(["player", "date", "minute"]).agg(
        dist=("dist", "sum"), dist_hsr=("dist_hsr", "sum"), dist_sprint=("dist_sprint", "sum"), pl=("pl", "sum"),
        speed_max=("speed_max", "max"), acc_peak_g=("acc_peak_g", "max"), hr=("hr", "mean"),
        acc2=("acc2", "sum"), dec2=("dec2", "sum"), acc3=("acc3", "sum"), dec3=("dec3", "sum"),
        sprints=("sprints", "sum"), hsr_efforts=("hsr_efforts", "sum"), seconds=("second", "size")).reset_index()

    full = s.set_index("second").reindex(range(int(s.second.min()), int(s.second.max()) + 1))
    roll = lambda col, w: float(full[col].fillna(0).rolling(w, min_periods=1).sum().max())
    zones = np.histogram(speed, bins=ZONES, weights=dist)[0]
    session.update({"player": player, "status": "ok", "start_s": int(s.second.min()), "end_s": int(s.second.max()),
                    "seconds_recorded": int(len(s)), "seconds_moving": int((s.speed_mean > 0.5).sum()),
                    "dist": float(dist.sum()), "dist_hsr": float(zones[3] + zones[4]), "dist_sprint": float(zones[4]),
                    **{f"dist_z{i + 1}": float(v) for i, v in enumerate(zones)},
                    "speed_peak": float(speed.max()), "pl": float(jerk.sum()),
                    **{k: int(len(v)) for k, v in events.items()},
                    "peak_dist_1min": roll("dist", 60), "peak_dist_3min": roll("dist", 180), "peak_dist_5min": roll("dist", 300),
                    "peak_pl_1min": roll("pl", 60), "impacts_3g": int((s.acc_peak_g > 3).sum()), "impacts_5g": int((s.acc_peak_g > 5).sum()),
                    "hr_mean": float(np.nanmean(tick.hr)) if tick.hr.notna().any() else np.nan,
                    "hr_max": float(np.nanmax(tick.hr)) if tick.hr.notna().any() else np.nan,
                    "hdop_mean": float(gps.hdop.mean()), "sats_mean": float(gps.num_satellites.mean())})
    session["low_gps_quality"] = session["hdop_mean"] > 5
    del tbl, df, gps, tick
    pa.default_memory_pool().release_unused()                           # hand Arrow's freed buffers back to Windows
    return s, m, session


# ── One archive ───────────────────────────────────────────────────────────────────────────────────────────────
def zenodo_files() -> dict:
    for k in range(5):
        try:
            return {f["key"]: (f["size"], f["links"]["self"]) for f in requests.get(ZENODO, timeout=60).json()["files"]}
        except Exception:
            time.sleep(30 * (k + 1))
    raise RuntimeError("Zenodo record unreachable")


def download(name: str) -> Path:
    """Fetch one archive until its size matches the record, resuming the .part file with HTTP Range after each drop.

    Zenodo answers Range requests with 206, so a broken connection costs only the lost chunk, not
    the whole 31 GB. A server that ignores the Range header (200) restarts the file from zero, never appends twice.
    Gives up after 12 attempts in a row with no progress at all.
    """
    size, url = zenodo_files()[name]
    out = SRC / name
    tmp = out.with_suffix(".part")
    SRC.mkdir(parents=True, exist_ok=True)
    stalls = 0
    while stalls < 12:
        if out.exists() and out.stat().st_size == size:
            return out
        have = tmp.stat().st_size if tmp.exists() else 0
        if have > size:                                                  # never trust a part larger than the record
            tmp.unlink()
            have = 0
        if have == size:
            tmp.replace(out)
            log({"source": "soccermon", "batch": name, "step": "downloaded", "bytes": size})
            return out
        try:
            headers = {"Range": f"bytes={have}-"} if have else {}
            with requests.get(url, stream=True, timeout=300, headers=headers) as r:
                r.raise_for_status()
                mode = "ab" if have and r.status_code == 206 else "wb"   # 200 = full body: start over
                with open(tmp, mode) as w:
                    for chunk in r.iter_content(8 << 20):
                        w.write(chunk)
        except Exception as e:
            print(f"download {name} at {have / 1e9:.2f}/{size / 1e9:.2f} GB: {e}", flush=True)
        now = tmp.stat().st_size if tmp.exists() else 0
        stalls = 0 if now > have else stalls + 1
        if now < size:
            time.sleep(30 if stalls == 0 else 60 * stalls)
    raise RuntimeError(f"could not download {name}")


def distil_archive(zip_path: Path, workers: int = 4) -> None:
    name = zip_path.name
    team, season = name.split("-")[1].replace("Team", ""), name.split("-")[2][:4]
    part = f"team={team}/season={season}"
    with zipfile.ZipFile(zip_path) as z:
        members = [i.filename for i in z.infolist() if not i.is_dir() and i.filename.endswith(".parquet")]
    print(f"{name}: {len(members)} player-days", flush=True)
    for table in ("seconds", "minutes", "sessions"):                 # re-runs start clean for this partition
        for p in (OUT / table / part).glob("*.parquet"):
            p.unlink()
    secs, mins, sessions, n_sec, chunk = [], [], [], 0, 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(distil_member, str(zip_path), m) for m in members]
        for k, f in enumerate(as_completed(futs)):
            try:
                s, m, sess = f.result()
            except Exception as e:
                sess, s, m = {"member": "?", "status": f"error: {type(e).__name__}: {e}"}, pd.DataFrame(), pd.DataFrame()
            sessions.append(sess)
            if len(s):
                secs.append(s)
                mins.append(m)
                n_sec += len(s)
            if len(secs) >= 75 or k == len(futs) - 1:
                if secs:
                    write_part(pd.concat(secs, ignore_index=True), OUT / "seconds" / part, f"part-{chunk:03d}")
                    write_part(pd.concat(mins, ignore_index=True), OUT / "minutes" / part, f"part-{chunk:03d}")
                    chunk += 1
                secs, mins = [], []
                print(f"  {k + 1}/{len(futs)} player-days", flush=True)
    ses = pd.DataFrame(sessions)
    write_part(ses, OUT / "sessions" / part, "part-000")

    # Verify from disk before anything is deleted: every member accounted for, every second written.
    errors = ses[ses.status.astype(str).str.startswith("error")]
    on_disk = rows_in(OUT / "seconds" / part)
    ok = len(ses) == len(members) and errors.empty and on_disk == n_sec and rows_in(OUT / "sessions" / part) == len(members)
    log({"source": "soccermon", "batch": name, "step": "distilled", "members": len(members), "errors": len(errors),
         "seconds_rows": on_disk, "minutes_rows": rows_in(OUT / "minutes" / part), "partition": part})
    if not ok:
        raise RuntimeError(f"{name}: verification failed ({len(errors)} errors, {on_disk} vs {n_sec} seconds rows)")
    log({"source": "soccermon", "batch": name, "step": "verified", "partition": part})
    print(f"{name}: verified ({on_disk:,} player-seconds)", flush=True)


# ── Subjective data and the modelling table ───────────────────────────────────────────────────────────────────
def subjective() -> None:
    z = zipfile.ZipFile(SRC / "subjective.zip")
    long = []
    for n in z.namelist():
        if not n.endswith(".csv") or n.split("/")[1] not in ("wellness", "training-load"):
            continue
        df = pd.read_csv(io.BytesIO(z.read(n)))
        df = df.rename(columns={df.columns[0]: "date"}).melt(id_vars="date", var_name="player", value_name="value")
        df["metric"] = Path(n).stem
        long.append(df.dropna(subset=["value"]))
    w = pd.concat(long, ignore_index=True)
    w["date"] = pd.to_datetime(w.date, format="%d.%m.%Y")
    w["team"] = w.player.str[4]
    write_part(w, OUT / "wellness", "wellness")

    inj = pd.read_csv(io.BytesIO(z.read("subjective/injury/injury.csv")))
    inj["date"] = pd.to_datetime(inj.timestamp, format="%d.%m.%Y")
    parsed = inj.type.map(json.loads)
    inj = inj.assign(body_part=parsed.map(lambda d: ", ".join(d)), severity=parsed.map(lambda d: ", ".join(d.values())))
    write_part(inj.drop(columns="timestamp"), OUT / "events", "injuries")
    ill = pd.read_csv(io.BytesIO(z.read("subjective/illness/illness.csv")))
    ill["date"] = pd.to_datetime(ill.timestamp, format="%d.%m.%Y")
    write_part(ill.drop(columns="timestamp"), OUT / "events", "illness")
    gp = pd.read_csv(io.BytesIO(z.read("subjective/game-performance/game-performance.csv")))
    gp["date"] = pd.to_datetime(gp.timestamp, format="%d.%m.%Y")
    write_part(gp.drop(columns="timestamp"), OUT / "events", "game_performance")
    sess = json.loads(z.read("subjective/training-load/session.json"))
    srpe = pd.DataFrame([{"player": p, **s} for p, lst in sess.items() for s in lst])
    srpe["date"] = pd.to_datetime(srpe.date, format="%d.%m.%Y")
    write_part(srpe, OUT / "events", "session_rpe")
    log({"source": "soccermon", "batch": "subjective.zip", "step": "verified", "wellness_rows": len(w), "injuries": len(inj),
         "illness": len(ill), "game_performance": len(gp), "sessions_rpe": len(srpe)})
    print(f"subjective: {len(w):,} wellness values, {len(inj)} injuries, {len(ill)} illness, {len(srpe):,} RPE sessions", flush=True)


def player_day() -> None:
    """Wellness + sRPE + GPS load + injury / illness flags per player per day: the table models train on."""
    import duckdb
    root = OUT.as_posix()
    q = f"""
    WITH w AS (PIVOT read_parquet('{root}/wellness/*.parquet') ON metric USING first(value) GROUP BY player, date),
         r AS (SELECT player, date, sum(srpe) AS srpe, sum(duration) AS rpe_minutes, max(rpe) AS rpe_max, count(*) AS rpe_sessions
               FROM read_parquet('{root}/events/session_rpe.parquet') GROUP BY ALL),
         g AS (SELECT player, date, sum(dist) AS gps_dist, sum(dist_hsr) AS gps_hsr, sum(dist_sprint) AS gps_sprint, sum(pl) AS gps_pl,
                      max(speed_peak) AS gps_speed_peak, sum(acc3 + dec3) AS gps_hard_changes, max(peak_dist_1min) AS gps_peak_1min,
                      sum(seconds_moving) / 60.0 AS gps_minutes_moving
               FROM read_parquet('{root}/sessions/**/*.parquet', hive_partitioning = true) WHERE status = 'ok' GROUP BY ALL),
         i AS (SELECT player_name AS player, date, 1 AS injury, string_agg(body_part, '; ') AS injury_where, string_agg(severity, '; ') AS injury_severity
               FROM read_parquet('{root}/events/injuries.parquet') GROUP BY ALL),
         s AS (SELECT player_name AS player, date, 1 AS illness FROM read_parquet('{root}/events/illness.parquet') GROUP BY ALL)
    SELECT * FROM w FULL JOIN r USING (player, date) FULL JOIN g USING (player, date)
                    LEFT JOIN i USING (player, date) LEFT JOIN s USING (player, date)
    ORDER BY player, date"""
    df = duckdb.sql(q).df()
    df["team"] = df.player.str[4]
    df[["injury", "illness"]] = df[["injury", "illness"]].fillna(0).astype(int)
    write_part(df, OUT, "player_day")
    print(f"player_day: {len(df):,} player-days, {df.gps_dist.notna().sum():,} with GPS", flush=True)


# ── The staged pipeline ───────────────────────────────────────────────────────────────────────────────────────
PREFETCH: dict[str, threading.Thread] = {}                              # downloads running in the background, by archive


def all_archives(limit: int | None = None) -> None:
    """Every archive not yet verified, oldest first; limit=1 does one batch and leaves the next one downloading."""
    if not done("soccermon", "subjective.zip"):
        subjective()
    todo = [a for a in ARCHIVES if not done("soccermon", a)]
    for k, name in enumerate(todo[:limit] if limit else todo):
        if name in PREFETCH:
            PREFETCH[name].join()                                        # never two downloads of the same file
        zip_path = download(name)
        if k + 1 < len(todo) and todo[k + 1] not in PREFETCH:            # fetch the next archive while this one is distilled
            nxt = todo[k + 1]
            PREFETCH[nxt] = threading.Thread(target=download, args=(nxt,), daemon=True)
            PREFETCH[nxt].start()
        distil_archive(zip_path)
        delete_raw(zip_path, "soccermon", name)
        player_day()                                                     # the merged modelling table, rebuilt each batch
    print("soccermon done", flush=True)


if __name__ == "__main__":
    {"subjective": subjective, "all": all_archives, "player_day": player_day}[sys.argv[1]]()
