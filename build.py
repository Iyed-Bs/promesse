"""Promesse, one command: rebuild everything from the data on disk, in dependency order, and check every gate.

When the crawls finish, this is the whole job: run it, read the project notes. Each step is a script that reads only the
published tables of the steps before it (ARCHITECTURE D4) and writes its own, with a report the gate reads.

    python build.py                 every step
    python build.py --from spine    from one step on (the earlier tables are reused)
    python build.py --only ladder   one step

(Promesse venv; identity runs in its own venv, as the maintenance loop does.)
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[0]))
from promesse_config import DATA_ROOT  # the one config file
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = Path(DATA_ROOT)
LAKE = DATA / "lake"
from promesse_config import PYTHON
PY = Path(PYTHON)
from promesse_config import IDENTITY_PYTHON
IDENTITY_PY = Path(IDENTITY_PYTHON)
NO_WINDOW = 0x08000000           # never flash a console window


def _json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


# (name, interpreter, working dir, command, gate reader -> (passed or None, one line))
STEPS = [
    ("registry", PY, HERE / "lake", ["registry.py"],
     lambda: ((lambda g: bool(g) and not g.get("league ids unmapped"))(_json(LAKE / "registry" / "gate.json")),
              "Phase 0: every league id mapped")),
    ("identity", IDENTITY_PY, HERE / "identity", ["records.py", "link.py", "ids.py", "eval.py"],
     lambda: (None, "Phase 1: persons rebuilt (gate: identity/gate.py score, 300 labelled pairs)")),
    ("strength_matchdata", PY, HERE / "lake", ["strength_v2.py"],
     lambda: ((lambda l: bool(l) and l["blend"]["test"] < l["elo (the loop's)"]["test"])(_json(LAKE / "strength" / "v2_ladder.json").get("ladder")),
              "Phase 2: strength v2 beats the loop's Elo (MatchData results)")),
    ("bridge", PY, HERE / "lake", ["strength_bridge.py"],
     lambda: ((lambda r: r and r["ci95"][1] < 0)(_json(LAKE / "strength" / "bridge_report.json")),
              "Phase 2: the player bridge beats one youth offset, out of time")),
    ("strength_tm", PY, HERE, ["gold/strength_tm.py"],
     lambda: (_json(LAKE / "gold" / "tm_strength_report.json").get("gate_passed"), "Phase 2b: Elo+ beats plain Elo on Transfermarkt games")),
    ("careers", PY, HERE, ["gold/careers.py"],
     lambda: (None, "Phase 2c: quality minutes and careers")),
    ("targets", PY, HERE, ["gold/targets.py"],
     lambda: (None, "Phase 3: targets v1 (frozen)")),
    ("ea", PY, HERE, ["gold/ea_ratings.py"],
     lambda: (None, "EA ratings: FIFA 15 to FC 26, each dated by when it was known")),
    ("spine", PY, HERE, ["gold/spine.py"],
     lambda: (_json(LAKE / "gold" / "leakage_audit.json").get("passed"), "Phase 3: the spine, leakage audit")),
    ("spine_extra", PY, HERE, ["gold/spine_extra.py", "gold/youth_caps.py", "gold/moves.py", "gold/youth_tournaments.py"],
     lambda: (None, "Engine v2 inputs: the shape of a career, youth international football, moves and loans (point in time)")),
    ("m3", PY, HERE, ["models/m3_fusion.py"],
     lambda: (None, "Phase 5: M3, the fused rating (Kalman), fitted on the training years")),
    ("ladder", PY, HERE, ["models/ladder.py"],
     lambda: (_json(LAKE / "models" / "ladder_y_reg3.json").get("gate_phase4", {}).get("passed"),
              "Phase 4: Promesse's engine (what happened only) beats the strongest benchmark on T2")),
    ("projection", PY, HERE, ["models/projection.py"],
     lambda: (_json(LAKE / "models" / "projection_qmin3.json").get("gate_phase6", {}).get("passed"),
              "Phase 6: projections' 80 % bands hold on T2 (tiers of 500+: 77-83 %; smaller: within sampling error)")),
    ("score", PY, HERE, ["models/score_current.py"],
     lambda: (None, "Scores the start of the 2026/27 season with the models whose gates passed (for the Scout Desk)")),
    ("score_v2c", PY, HERE, ["models/score_v2c.py"],
     lambda: (None, "Scores the start of the 2026/27 season with ProEngine, the call the desk shows (level with market value, gate not passed)")),
    ("scout", PY, HERE, ["scout/precompute.py"],
     lambda: (None, "The Scout Desk's tables (people, careers, matches, outlooks, boards)")),
    ("ladder_m3", PY, HERE, [],
     lambda: (_json(LAKE / "models" / "ladder_y_reg3.json").get("gate_phase5", {}).get("passed"),  # paused: M3 is EA-anchored (models/inputs.py)
              "Phase 5: M3's fused rating improves the best model on T2")),
]


def run_step(name, py, cwd, scripts) -> tuple[bool, float, str]:
    t0 = time.time()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    for s in scripts:
        r = subprocess.run([str(py), s], cwd=cwd, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL,
                           creationflags=NO_WINDOW, timeout=4 * 3600)
        if r.returncode:
            return False, time.time() - t0, (r.stderr.strip().splitlines() or ["?"])[-1][:200]
    return True, time.time() - t0, ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start")
    ap.add_argument("--only")
    a = ap.parse_args()
    names = [s[0] for s in STEPS]
    todo = names[names.index(a.start):] if a.start else [a.only] if a.only else names
    rows = []
    for name, py, cwd, scripts, gate in STEPS:
        if name not in todo:
            continue
        print(f"== {name}", flush=True)
        ok, secs, err = run_step(name, py, cwd, scripts)
        passed, what = gate() if ok else (False, "")
        rows.append((name, ok, secs, passed, what, err))
        print(f"   {'ok' if ok else 'FAILED'} in {secs:.0f} s" + (f" · gate {'passed' if passed else 'not passed'}" if passed is not None else "")
              + (f" · {err}" if err else ""), flush=True)
        if not ok:
            break
    # every step's last result is kept, so a partial run (--from, --only) still shows the whole chain
    state_file = HERE / "build_state.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    for n, ok, secs, p, w, err in rows:
        state[n] = {"ok": ok, "secs": round(secs), "passed": p, "what": w, "err": err, "at": f"{datetime.now():%Y-%m-%d %H:%M}"}
    state_file.write_text(json.dumps(state, indent=1), encoding="utf-8")
    mark = lambda p: "passed" if p else ("—" if p is None else "**not passed**")
    lines = ["# Promesse build status", "", f"Last run {datetime.now():%Y-%m-%d %H:%M} by `build.py` "
             f"({'from ' + a.start if a.start else 'only ' + a.only if a.only else 'every step'}); each row is that "
             "step's latest result.", "",
             "| Step | Ran | When | Time | Gate | What it checks |", "|---|---|---|---|---|---|"]
    for n in names:
        r = state.get(n)
        if r:
            lines.append(f"| {n} | {'ok' if r['ok'] else 'FAILED: ' + r['err']} | {r['at']} | {r['secs']} s | "
                         f"{mark(r['passed'])} | {r['what']} |")
        else:
            lines.append(f"| {n} | not run yet | | | | |").write_text("\n".join(lines) + "\n", encoding="utf-8")
    sys.exit(0 if all(r[1] for r in rows) else 1)


if __name__ == "__main__":
    main()
