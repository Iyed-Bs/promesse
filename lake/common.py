"""Promesse data lake: shared paths, the manifest, and the only way raw data gets deleted.

The lake turns large public raw downloads into compact, model-ready Parquet tables, one source batch at a time:
    download -> distil -> verify -> record in the manifest -> delete the raw batch -> next batch.
Each batch lands as its own partition of a dataset (e.g. lake/soccermon/seconds/team=B/season=2020/), so later
batches merge with earlier ones simply by being read together (pyarrow.dataset or duckdb read_parquet('.../**')).

Raw sources are all public and re-downloadable; the manifest keeps where each batch came from.
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import datetime as dt
import json
import os
import shutil
import stat
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

DATA = Path(DATA_ROOT)
OPEN = DATA / "open"
LAKE = DATA / "lake"
MANIFEST = LAKE / "manifest.jsonl"
LAKE.mkdir(parents=True, exist_ok=True)


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def log(entry: dict) -> None:
    """Append one line to the manifest: what was distilled, from where, into what, with counts."""
    with MANIFEST.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": now(), **entry}, ensure_ascii=False) + "\n")


def done(source: str, batch: str) -> bool:
    """True when this batch was distilled and verified before (the pipeline can be re-run safely)."""
    if not MANIFEST.exists():
        return False
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e.get("source") == source and e.get("batch") == batch and e.get("step") == "verified":
            return True
    return False


def write_part(table: pa.Table | "pd.DataFrame", folder: Path, name: str) -> Path:
    """Write one part file of a partitioned dataset (zstd, compact)."""
    import pandas as pd
    if isinstance(table, pd.DataFrame):
        table = pa.Table.from_pandas(table, preserve_index=False)
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{name}.parquet"
    tmp = out.with_suffix(".tmp")
    pq.write_table(table, tmp, compression="zstd", compression_level=6)
    tmp.replace(out)
    return out


def rows_in(folder: Path) -> int:
    """Rows across every part file under a folder (re-read from disk: the check that counts)."""
    return sum(pq.ParquetFile(p).metadata.num_rows for p in folder.rglob("*.parquet"))


def size_gb(path: Path) -> float:
    if path.is_file():
        return path.stat().st_size / 1e9
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) / 1e9


def delete_raw(path: Path, source: str, batch: str) -> None:
    """Delete a raw batch, but only after its distilled output was verified and logged."""
    if not done(source, batch):
        raise RuntimeError(f"refusing to delete {path}: {source}/{batch} is not verified in the manifest")
    if not str(path).startswith(str(OPEN)):
        raise RuntimeError(f"refusing to delete {path}: outside {OPEN}")
    gb = size_gb(path) if path.exists() else 0.0
    if path.is_dir():
        def writable_then_retry(func, p, exc):                   # git marks its pack files read-only on Windows
            os.chmod(p, stat.S_IWRITE)
            func(p)
        shutil.rmtree(path, onexc=writable_then_retry)
    elif path.exists():
        path.unlink()
    log({"source": source, "batch": batch, "step": "raw deleted", "path": str(path), "freed_gb": round(gb, 2)})
