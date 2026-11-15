"""One queue for the whole lake: heavy distillers run one at a time so memory never runs out.

Order:
  1. SoccerMon, the archive already on disk (the next one starts downloading in the background)
  2. StatsBomb open data (raw clone deleted once verified)
  3. DFL tracking (raw position files deleted once verified)
  4. SoccerMon, the remaining archives (download -> distil -> verify -> delete -> next)
Every step skips what the manifest already records as verified, so the queue can be stopped and restarted.

Run (Patcher venv, from this folder):  python run_lake.py
"""
from __future__ import annotations

import dfl
import soccermon
import statsbomb
from common import log


def step(name: str, fn, *args) -> None:
    print(f"== {name}", flush=True)
    try:
        fn(*args)
    except Exception as e:                       # one source failing must not stop the others; the manifest keeps the raw data safe
        log({"source": "run_lake", "batch": name, "step": "failed", "error": f"{type(e).__name__}: {e}"})
        print(f"!! {name} failed: {type(e).__name__}: {e}", flush=True)


if __name__ == "__main__":
    step("soccermon first archive", soccermon.all_archives, 1)
    step("statsbomb", statsbomb.all_data)
    step("dfl", dfl.all_data)
    step("soccermon remaining archives", soccermon.all_archives)
    print("lake queue done", flush=True)
