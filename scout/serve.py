"""Start the Scout Desk detached, with no console window (no window on the user's screen): http://127.0.0.1:8792

    python scout/serve.py          (Promesse venv, from _research/football)
"""
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
LOG = Path((DATA_ROOT + "/scout/serve.log"))
DETACHED, NO_WINDOW = 0x00000008, 0x08000000
with open(LOG, "ab") as log:
    subprocess.Popen([sys.executable, "-m", "uvicorn", "scout.api:app", "--host", "127.0.0.1", "--port", "8792"],
                     cwd=HERE, stdout=log, stderr=log, stdin=subprocess.DEVNULL, creationflags=DETACHED | NO_WINDOW)
print("Scout Desk: http://127.0.0.1:8792")
