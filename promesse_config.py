"""The one place that says where the data lives (replaces the paths that used to be written in each script).

Set the environment variable PROMESSE_DATA to the folder that holds your data; the default is ./data next to this file.
Layout under it:
    lake/       the cleaned tables the build reads and writes (lake/gold, lake/models, lake/quality)
    scout/      the Scout Desk's database (scout.duckdb) and log
    kaggle/     downloaded open datasets (kaggle/tm_archive: dated copies of the Transfermarkt datasets)
PROMESSE_PYTHON: the interpreter build.py uses for its steps (default: the one running it).
PROMESSE_IDENTITY_PYTHON: the interpreter for the identity step (default: same).
PROMESSE_CLUBS: where a club's board files sit for the desk's club pages (default: DATA_ROOT/clubs).
"""
import os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_ROOT = os.environ.get("PROMESSE_DATA", str(ROOT / "data")).replace("\\", "/")
PYTHON = os.environ.get("PROMESSE_PYTHON", sys.executable)
IDENTITY_PYTHON = os.environ.get("PROMESSE_IDENTITY_PYTHON", PYTHON)
CLUBS_ROOT = os.environ.get("PROMESSE_CLUBS", DATA_ROOT + "/clubs").replace("\\", "/")
