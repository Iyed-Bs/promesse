"""The lake's housekeeping loop: turn what the collectors fetched into clean, checked, model-ready tables, again and again.

Every pass is incremental and idempotent (only new or changed batches are processed) and never deletes raw data:
  1. matchdata     raw match details -> lake/matchdata/player_matches/league_id=../season=../  (one row per player per match),
                with checks: unique (match, player), minutes 0-130, ages 12-45
  2. strength   an Elo rating for every team in every competition collected (youth and lower tiers included), from the
                fixture lists -> lake/strength/elo_matches.parquet + team_ratings.parquet: the "quality minutes" base
  3. encyclopedia  as-of snapshots -> lake/text/encyclopedia_asof.parquet
  4. research   catalogue of the open research datasets: files, sizes, columns -> lake/research_catalog.parquet
  5. disk       free space report; a warning under 25 GB on D:
  6. identity   identity v3 rebuilt weekly (or after 1,000 new gamerating_b pages), in its own venv, stable ids kept
  0. inseason   the current season fetched again from MatchData every 3 days (waits for the backfill, at most 7 days)
Each pass is logged to the manifest.

Run (Patcher venv, from this folder):  python maintain.py once     |    python maintain.py loop [hours]   (default 3)
"""
from __future__ import annotations

import gzip
import io
import json
import shutil
import sys
import time
from pathlib import Path

import pandas as pd

from common import DATA, LAKE, log, write_part

sys.path.insert(0, str(Path(__file__).parents[1] / "collect"))
import matchdata_matches as fm  # noqa: E402

STATE = LAKE / "maintain_state.json"


def state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save(st: dict) -> None:
    STATE.write_text(json.dumps(st, indent=0), encoding="utf-8")


# ── 1. MatchData player-matches ─────────────────────────────────────────────────────────────────────────────────────
def matchdata(st: dict) -> None:
    done = st.setdefault("matchdata", {})
    new_parts = rows_total = 0
    for folder in sorted(p for p in fm.RAW.glob("*/*") if p.is_dir()):
        lid, season = folder.parts[-2], folder.name
        files = sorted(folder.glob("*.json.gz"))
        key = f"{lid}/{season}"
        if not files or done.get(key) == len(files):
            continue
        rows = []
        for p in files:
            try:
                rows += fm.rows_of(fm.read_gz(p), int(lid), season.replace("-", "/"))
            except Exception:
                pass
        if not rows:
            done[key] = len(files)
            continue
        df = pd.DataFrame(rows)
        before = len(df)
        df = df.drop_duplicates(["match_id", "player_id"])
        mins = pd.to_numeric(df.get("Minutes played"), errors="coerce") if "Minutes played" in df else pd.Series(dtype=float)
        if len(mins):
            df.loc[(mins < 0) | (mins > 130), "Minutes played"] = None
        if "age" in df:
            df.loc[(df.age < 12) | (df.age > 45), "age"] = None
        for c in df.columns:                                    # one type per column across partitions
            if df[c].dtype == object:
                df[c] = df[c].astype("string")
        write_part(df, LAKE / "matchdata" / "player_matches" / f"league_id={lid}" / f"season={season}", "part-000")
        done[key] = len(files)
        new_parts += 1
        rows_total += len(df)
        if before != len(df):
            log({"source": "matchdata", "batch": key, "step": "deduplicated", "dropped": before - len(df)})
    save(st)
    log({"source": "matchdata", "batch": "player_matches", "step": "maintained", "partitions_written": new_parts, "rows_written": rows_total})
    print(f"matchdata: {new_parts} partitions refreshed, {rows_total:,} player-match rows", flush=True)


# ── 2. Strength ratings (Elo) ────────────────────────────────────────────────────────────────────────────────────
TIER_PRIOR = {**{i: 1650 for i in (47, 87, 55, 54, 53)},                                  # big five
              **{i: 1500 for i in (57, 61, 40, 46, 38, 69, 64, 59, 67)},                  # other top flights
              **{i: 1400 for i in (110, 48, 146, 140, 86, 111, 185, 168, 203, 85)},       # second tiers
              **{i: 1300 for i in (8970, 208, 9195, 512, 8968, 9138, 147)},               # third tiers and reserves
              **{i: 1250 for i in fm.YOUTH}}                                               # youth competitions (their own scale)


def elo_run(df: pd.DataFrame, K: float, HOME: float, prior: dict):
    """One chronological pass: ratings before each match, the home-win expectation, final ratings."""
    rating: dict[str, float] = {}
    pre_h, pre_a, exp = [], [], []
    for r in df.itertuples():
        rh, ra = rating.get(r.home_id, prior.get(r.home_id, 1200.0)), rating.get(r.away_id, prior.get(r.away_id, 1200.0))
        pre_h.append(rh)
        pre_a.append(ra)
        e = 1 / (1 + 10 ** ((ra - rh - HOME) / 400))
        exp.append(e)
        margin = (abs(r.hg - r.ag) + 1) ** 0.5                  # bigger wins move ratings a little more
        rating[r.home_id] = rh + K * margin * (r.res - e)
        rating[r.away_id] = ra - K * margin * (r.res - e)
    return rating, pre_h, pre_a, pd.Series(exp, index=df.index)


def strength(st: dict) -> None:
    rows = []
    for p in fm.RAW.glob("*/league_*.json.gz"):
        try:
            L = fm.read_gz(p)
        except Exception:
            continue
        comp = (L.get("details") or {}).get("name")
        for m in (L.get("fixtures") or {}).get("allMatches", []):
            s = m.get("status") or {}
            if not s.get("finished") or not s.get("scoreStr") or "-" not in s["scoreStr"]:
                continue
            try:
                hg, ag = [int(x) for x in s["scoreStr"].replace(" ", "").split("-")[:2]]
            except ValueError:
                continue
            rows.append({"match_id": str(m["id"]), "date": (s.get("utcTime") or "")[:10], "competition": comp, "league_id": p.parts[-2],
                         "home_id": str(m["home"]["id"]), "home": m["home"]["name"], "away_id": str(m["away"]["id"]), "away": m["away"]["name"],
                         "hg": hg, "ag": ag})
    if not rows:
        return
    df = pd.DataFrame(rows).drop_duplicates("match_id").sort_values("date").reset_index(drop=True)
    df["res"] = (df.hg > df.ag).astype(float) + 0.5 * (df.hg == df.ag)      # home win 1, draw 0.5, loss 0
    # Each team starts at the level of its usual league, so leagues that never meet still sit at sensible heights.
    league_of = pd.concat([df[["home_id", "league_id"]].set_axis(["team", "league"], axis=1),
                           df[["away_id", "league_id"]].set_axis(["team", "league"], axis=1)])
    league_of = league_of[league_of.league.astype(int).map(TIER_PRIOR).notna()]
    home_league = league_of.groupby("team").league.agg(lambda s: s.value_counts().index[0])
    prior = {t: TIER_PRIOR[int(l)] for t, l in home_league.items()}
    # Home advantage and update speed are chosen on 2023/24, then judged once on 2024/25 onwards (out of time).
    best = None
    for K in (15.0, 20.0, 30.0):
        for HOME in (20.0, 40.0, 60.0, 80.0):
            _, _, _, exp = elo_run(df, K, HOME, prior)
            val = (df.date >= "2023-07-01") & (df.date < "2024-07-01")
            brier = float(((exp[val] - df.res[val]) ** 2).mean()) if val.any() else 1.0
            if best is None or brier < best[0]:
                best = (brier, K, HOME)
    _, K, HOME = best
    rating, pre_h, pre_a, exp = elo_run(df, K, HOME, prior)
    test = df.date >= "2024-07-01"
    test_brier = float(((exp[test] - df.res[test]) ** 2).mean()) if test.any() else None
    df["elo_home_before"], df["elo_away_before"], df["p_home"] = pre_h, pre_a, exp
    write_part(df, LAKE / "strength", "elo_matches")
    log({"source": "strength", "batch": "elo", "step": "calibrated", "K": K, "home_advantage": HOME,
         "validation_brier_2023_24": round(best[0], 4), "test_brier_2024_on": round(test_brier, 4) if test_brier else None,
         "expected_home_rate_test": round(float(exp[test].mean()), 3) if test.any() else None,
         "actual_home_rate_test": round(float(df.res[test].mean()), 3) if test.any() else None})
    names = pd.concat([df[["home_id", "home"]].set_axis(["team_id", "team"], axis=1), df[["away_id", "away"]].set_axis(["team_id", "team"], axis=1)])
    names = names.drop_duplicates("team_id", keep="last").set_index("team_id").team
    teams = pd.DataFrame({"team_id": list(rating), "elo": list(rating.values())})
    teams["team"] = teams.team_id.map(names)
    write_part(teams.sort_values("elo", ascending=False), LAKE / "strength", "team_ratings")
    log({"source": "strength", "batch": "elo", "step": "maintained", "matches": len(df), "teams": len(teams)})
    print(f"strength: Elo over {len(df):,} results, {len(teams):,} teams; K={K:g}, home={HOME:g}; "
          f"Brier validation {best[0]:.4f}, test {test_brier:.4f}", flush=True)


# ── 2b. Identity: MatchData youth players -> Transfermarkt (-> EA through the existing links) ───────────────────────
def identity(st: dict) -> None:
    """Exact birth date + name similarity. Transfermarkt's open data only holds players with top-flight minutes, so a
    youth player who links has already reached senior football: the link rate is itself an early outcome."""
    import duckdb
    from rapidfuzz import fuzz
    from unidecode import unidecode
    raw = DATA / "raw" / "matchdata_youth_players" / "player"
    files = list(raw.glob("*.json.gz")) if raw.exists() else []
    if not files or st.get("identity") == len(files):
        return
    youth = []
    for p in files:
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        dob = ((d.get("birthDate") or {}).get("utcTime") or "")[:10]
        if d.get("id") and d.get("name") and dob:
            youth.append({"matchdata_id": str(d["id"]), "name": d["name"], "dob": dob, "team": (d.get("primaryTeam") or {}).get("teamName")})
    yf = pd.DataFrame(youth)
    c = duckdb.connect()
    c.execute(f"ATTACH '{(DATA / 'transfermarkt-datasets.duckdb').as_posix()}' AS tm (READ_ONLY)")
    tm = c.execute("SELECT player_id AS tm_id, name AS tm_name, CAST(date_of_birth AS DATE)::VARCHAR AS dob, current_club_name FROM tm.players "
                   "WHERE date_of_birth IS NOT NULL").df()
    norm = lambda s: " ".join(unidecode(str(s)).lower().replace("-", " ").split())
    by_dob = tm.groupby("dob")
    out = []
    for r in yf.itertuples():
        if r.dob not in by_dob.groups:
            continue
        cands = by_dob.get_group(r.dob)
        best = max(((fuzz.token_set_ratio(norm(r.name), norm(t.tm_name)), t) for t in cands.itertuples()), key=lambda x: x[0])
        if best[0] >= 85:
            out.append({"matchdata_id": r.matchdata_id, "tm_id": int(best[1].tm_id), "score": best[0], "name": r.name, "tm_name": best[1].tm_name, "dob": r.dob})
    links = pd.DataFrame(out)
    ea = pd.read_parquet(DATA / "link_ea_tm_v2.parquet") if (DATA / "link_ea_tm_v2.parquet").exists() else None
    if ea is not None and len(links):
        tm_col = next((c for c in ea.columns if "tm" in c.lower()), None)
        ea_col = next((c for c in ea.columns if "ea" in c.lower() and c != tm_col), None)
        if tm_col and ea_col:
            links = links.merge(ea[[tm_col, ea_col]].rename(columns={tm_col: "tm_id", ea_col: "ea_id"}).drop_duplicates("tm_id"), on="tm_id", how="left")
    write_part(links, LAKE / "identity", "matchdata_youth_tm")
    st["identity"] = len(files)
    save(st)
    log({"source": "identity", "batch": "matchdata_youth_tm", "step": "maintained", "youth": len(yf), "linked_tm": len(links)})
    print(f"identity: {len(links):,} of {len(yf):,} youth players linked to Transfermarkt (already in senior top-flight data)", flush=True)


# ── 3. an open encyclopedia as-of snapshots ─────────────────────────────────────────────────────────────────────────────────
def encyclopedia(st: dict) -> None:
    raw = DATA / "raw" / "encyclopedia_asof"
    files = list(raw.glob("*.json.gz")) if raw.exists() else []
    if not files or st.get("encyclopedia") == len(files):
        return
    rows = []
    for p in files:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            rows.append(json.load(f))
    df = pd.DataFrame(rows)
    df["text"] = df.get("text", pd.Series(dtype=str)).astype("string")
    write_part(df, LAKE / "text", "encyclopedia_asof")
    st["encyclopedia"] = len(files)
    save(st)
    print(f"encyclopedia: {len(df):,} snapshots ({df.exists.mean():.0%} with an article at that age)", flush=True)


# ── 4. Research datasets catalogue ───────────────────────────────────────────────────────────────────────────────
def research(st: dict) -> None:
    root = DATA / "open" / "research"
    man = json.loads((root / "manifest.json").read_text(encoding="utf-8")) if (root / "manifest.json").exists() else {}
    if not man or st.get("research") == len(man):
        return
    rows = []
    for key, e in man.items():
        for f in e.get("files", []):
            p = root / key / f
            cols = ""
            try:
                if p.suffix.lower() == ".csv":
                    cols = ", ".join(pd.read_csv(p, nrows=5, sep=None, engine="python").columns.astype(str))[:500]
                elif p.suffix.lower() in (".xlsx", ".xls"):
                    cols = ", ".join(pd.read_excel(p, nrows=5).columns.astype(str))[:500]
            except Exception:
                cols = "(unreadable as a table)"
            rows.append({"dataset": key, "title": e["title"], "licence": e["licence"], "citation": e["citation"], "file": f,
                         "bytes": p.stat().st_size if p.exists() else None, "columns": cols})
    write_part(pd.DataFrame(rows), LAKE, "research_catalog")
    st["research"] = len(man)
    save(st)
    print(f"research: catalogue of {len(man)} datasets, {len(rows)} files", flush=True)


# ── 5. Disk ──────────────────────────────────────────────────────────────────────────────────────────────────────
def disk(st: dict) -> None:
    free = shutil.disk_usage("<local path>").free / 1e9
    msg = f"disk: D: {free:.0f} GB free"
    if free < 25:
        msg += "  WARNING: under 25 GB; hold new downloads until a verified raw batch is deleted"
    log({"source": "disk", "batch": "D:", "step": "checked", "free_gb": round(free, 1)})
    print(msg, flush=True)


# ── 6. Integrity ─────────────────────────────────────────────────────────────────────────────────────────────────
def integrity(st: dict) -> None:
    """The data integrity audit (integrity.py) after every refresh: quarantine, flags, readiness, evidence tiers."""
    import integrity as audit
    audit.main()


def events(st: dict) -> None:
    """Shots and timed goals/subs/cards (matchdata_events.py), re-extracted only when new match files arrived."""
    n = sum(1 for _ in fm.RAW.glob("*/*/*.json.gz"))
    if st.get("events_files") == n:
        return
    import matchdata_events
    matchdata_events.main()
    st["events_files"] = n
    save(st)
    log({"source": "matchdata events", "batch": "all", "step": "extracted", "files": n})


def registries(st: dict) -> None:
    """Phase 0 registries (registry.py); a league id a new crawl brings in fails the gate until it is mapped."""
    import duckdb
    import registry
    g = registry.build(duckdb.connect())
    log({"source": "registry", "batch": "gate", "step": "passed" if g["passed"] else "failed",
         "unmapped": g["league ids unmapped"], "orphans": g["orphan teams"]})


# ── Identity v3: one person id per player across every source, rebuilt weekly ────────────────────────────────────
IDENTITY = Path(__file__).parents[1] / "identity"
IDENTITY_PY = Path("<local path>")   # its own venv (Splink, DuckDB)
NO_WINDOW = 0x08000000                                               # never flash a console window


def identity_v3(st: dict) -> None:
    """Rebuilds identity v3 (identity/README.md) once a week, or as soon as 1,000 new gamerating_b pages have landed from the
    youth crawl: records -> link -> ids (stable ids kept, merges and splits logged) -> the agreement with v2."""
    import os
    import subprocess
    s = st.setdefault("identity_v3", {})
    pages = sum(1 for _ in (DATA / "raw" / "gamerating_b").rglob("*.html"))
    due = time.time() - s.get("last", 0) > 7 * 86400 or pages - s.get("pages", 0) >= 1000
    if not due or not IDENTITY_PY.exists():
        return
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    last = []
    for script in ("records.py", "link.py", "ids.py", "eval.py"):
        r = subprocess.run([str(IDENTITY_PY), script], cwd=IDENTITY, capture_output=True, text=True, env=env,
                           stdin=subprocess.DEVNULL,   # a detached loop has no console handle to pass down
                           timeout=7200, creationflags=NO_WINDOW)
        if r.returncode:
            raise RuntimeError(f"{script}: {r.stderr.strip()[-300:]}")
        last.append((r.stdout.strip().splitlines() or [""])[-1])
    s.update(last=time.time(), pages=pages)
    save(st)
    log({"source": "identity v3", "batch": "weekly", "step": "rebuilt", "ids": last[2], "pairs": last[3][:200]})
    print(f"identity v3: {last[2]}", flush=True)


def inseason(st: dict) -> None:
    """The current season's MatchData matches, fetched again every 3 days. Until this loop only folded raw files in
    and never fetched, so 2026/27 stood still from 19 to. It waits while another MatchData crawl runs (the backfill
    held apart, so MatchData never sees two of ours at once), but never more than 7 days; the next pass folds the new files
    in (step 1)."""
    import subprocess
    s = st.setdefault("inseason", {})
    log_path = DATA / "matchdata_inseason.log"
    last = s.get("last") or (log_path.stat().st_mtime if log_path.exists() else 0)
    age = time.time() - last
    if age < 3 * 86400:
        return
    bf = DATA / "matchdata_backfill.log"
    busy = bf.exists() and time.time() - bf.stat().st_mtime < 3600 and "backfill done" not in bf.read_text(encoding="utf-8", errors="ignore")[-300:]
    if busy and age < 7 * 86400:
        print(f"inseason: waiting for the backfill ({age / 86400:.1f} days since the last refresh)", flush=True)
        return
    with open(log_path, "a", encoding="utf-8") as out:
        r = subprocess.run([sys.executable, "matchdata_matches.py", "crawl"], cwd=Path(__file__).parents[1] / "collect", stdout=out,
                           stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=6 * 3600, creationflags=NO_WINDOW)
    s.update(last=time.time(), ok=r.returncode == 0)
    save(st)
    log({"source": "matchdata", "batch": "in-season", "step": "fetched" if r.returncode == 0 else "failed"})
    print(f"inseason: {'ok' if r.returncode == 0 else 'FAILED'}", flush=True)


def promesse_build(st: dict) -> None:
    """Rebuilds the Promesse chain once a week, after identity v3: strength on Transfermarkt's
    games, careers, targets, EA, the spine, M3, the ladder, the projections. Every gate lands in the project notes, so
    new data reaches the models without anyone running anything."""
    import os
    import subprocess
    s = st.setdefault("promesse_build", {})
    if time.time() - s.get("last", 0) < 7 * 86400:
        return
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, "build.py", "--from", "strength_tm"], cwd=Path(__file__).parents[1],
                       capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL, timeout=4 * 3600,
                       creationflags=NO_WINDOW)
    s.update(last=time.time(), ok=r.returncode == 0)
    save(st)
    log({"source": "promesse build", "batch": "weekly", "step": "built" if r.returncode == 0 else "failed",
         "tail": (r.stdout.strip().splitlines() or [""])[-1][:200]})
    print(f"promesse build: {'ok' if r.returncode == 0 else 'FAILED'}", flush=True)


def once() -> None:
    st = state()
    for step in (disk, inseason, matchdata, events, strength, identity, encyclopedia, research, registries, identity_v3, promesse_build,
                 integrity):
        try:
            step(st)
        except Exception as e:
            log({"source": "maintain", "batch": step.__name__, "step": "failed", "error": f"{type(e).__name__}: {e}"})
            print(f"!! {step.__name__}: {type(e).__name__}: {e}", flush=True)


def loop(hours: float = 3.0) -> None:
    while True:
        print(f"== pass {time.strftime('%Y-%m-%d %H:%M')}", flush=True)
        once()
        time.sleep(hours * 3600)


if __name__ == "__main__":
    if sys.argv[1] == "loop":
        loop(float(sys.argv[2]) if len(sys.argv) > 2 else 3.0)
    else:
        once()
