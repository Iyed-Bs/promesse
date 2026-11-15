"""ProT6, step 1: game models and coach spells over MORE seasons, in their own folder.

T1's team-style job (gold/team_style.py) and T2's coach job (gold/coach_style.py) rerun unchanged, except that they read
the main crawl AND the backfill (through lake/matchdata_all/player_matches, two directory junctions) and write to
lake/gold_t6v2/ instead of lake/gold/ (the desk keeps its own files). Dimensions that need shot maps stay failed.

    python models/t6v2_data.py     (Promesse venv)
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "gold"))
import coach_style as cs  # noqa: E402
import team_style as ts  # noqa: E402

ALL = (ts.LAKE / "matchdata_all" / "player_matches").as_posix() + "/**/*.parquet"
OUT = ts.LAKE / "gold_t6v2"
OUT.mkdir(exist_ok=True)
for mod in (ts, cs):
    mod.PM = ALL
    mod.GOLD = OUT

if __name__ == "__main__":
    ts.main()
    cs.main()
