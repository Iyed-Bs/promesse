"""A second Scout Desk on :8795 for headless checks: same code and data as the live desk (:8792), but its Shortlists
live in a scratch file, so a check never writes into scout/lists.json. Runs until stopped.

    python scout/checks/test_desk.py [scratch_dir]        (Promesse venv, from _research/football)
then: node scout/checks/desk_check.mjs                    (from <local path> for playwright-core)
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))       # _research/football, so `scout` and `gold` import
import uvicorn
from scout import api

api.LISTS = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.gettempdir()) / "lists_test.json"
uvicorn.run(api.app, host="127.0.0.1", port=8795, log_level="warning")
