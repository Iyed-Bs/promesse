"""Prove the plug: run every adapter we can on data we hold, check what lands, link the people.

    python -m connect.run      (from the football folder, Promesse venv)
      -> lake/connect/<adapter>/<table>.parquet and lake/connect/connect_report.json (read by the desk's Connect page)

What it shows a club: its feeds (event, tracking) come through the same adapters as these open samples; its people land
on ours through the Reep register; the contract's checks say what arrived before anything is trusted. What it can't
show: the club's own exports (GPS, medical status, reports); their adapters are written and run on a club's files.
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
import time
import traceback
from pathlib import Path

import pandas as pd

from connect import identity
from connect.adapters import REGISTRY, dfl, impect, metrica, skillcorner
from connect.contract import TABLES, check

DATA = Path(DATA_ROOT)
OPEN = DATA / "open"
OUT = DATA / "lake" / "connect"


def save(name: str, tables: dict[str, pd.DataFrame]) -> dict:
    d = OUT / name
    d.mkdir(parents=True, exist_ok=True)
    rep = {}
    for t, df in tables.items():
        df.to_parquet(d / f"{t}.parquet", index=False)
        rep[t] = check(df, t)
    return rep


def merge(parts: list[dict[str, pd.DataFrame]]) -> dict[str, pd.DataFrame]:
    out: dict[str, list] = {}
    for p in parts:
        for t, df in p.items():
            out.setdefault(t, []).append(df)
    return {t: pd.concat(v, ignore_index=True) for t, v in out.items()}


def people_of(tables: dict[str, pd.DataFrame], provider: str) -> dict:
    """the people in these tables, linked through Reep, then checked against our own record"""
    app = tables.get("appearances")
    if app is None or app.empty:
        return {}
    ids = app["player_ref"].dropna().str.split(":", n=1).str[1].unique().tolist()
    lk = identity.audit(identity.links(provider, ids))
    return {"people": len(ids), "linked": int(lk["external_id"].nunique()), "linked_share": round(lk["external_id"].nunique() / max(1, len(ids)), 3),
            "checked_agree": int((lk["agrees"] == True).sum()), "checked_disagree": int((lk["agrees"] == False).sum()),  # noqa: E712
            "by_method": lk["method"].value_counts().to_dict()}


def main() -> None:
    report = {"built": pd.Timestamp.now().isoformat(timespec="seconds"), "contract": {t: list(c) for t, c in TABLES.items()},
              "adapters": {k: {x: v[x] for x in ("kind", "provider", "licence", "reads")} for k, v in REGISTRY.items()}, "runs": {}}
    jobs = {
        "impect": lambda: merge([impect(OPEN / "impect" / "data", m) for m in
                                 sorted(p.stem.split("_")[1] for p in (OPEN / "impect" / "data" / "events").glob("events_*.json"))[:4]]),
        "dfl": lambda: merge([dfl(OPEN / "dfl-idsse", m, tracking=(i == 0)) for i, m in enumerate(
            sorted({p.stem.rsplit("_", 1)[1] for p in (OPEN / "dfl-idsse").glob("DFL_03_02_events_raw_*.xml")})[:3])]),
        "metrica": lambda: metrica(OPEN / "metrica-sample-data" / "data"),
        "skillcorner": lambda: merge([skillcorner(OPEN / "skillcorner-opendata" / "data" / "matches", m) for m in
                                      sorted(p.name for p in (OPEN / "skillcorner-opendata" / "data" / "matches").iterdir() if p.is_dir())[:2]]),
    }
    reep_provider = {"impect": "impect", "skillcorner": "skillcorner"}
    for name, job in jobs.items():
        t0 = time.time()
        try:
            tables = job()
            rep = {"ok": True, "seconds": round(time.time() - t0, 1), "tables": save(name, tables),
                   "matches": int(pd.concat([df["match_ref"] for df in tables.values() if "match_ref" in df]).nunique())}
            if name in reep_provider:
                rep["identity"] = people_of(tables, reep_provider[name])
        except Exception as e:  # a source that fails is reported, never hidden
            rep = {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1200:]}
        report["runs"][name] = rep
        print(name, json.dumps({k: v for k, v in rep.items() if k != "trace"}, ensure_ascii=False)[:900])
    # the desk's own players (the 22,000 seats of Discover, from the running desk; else the current cohort): how many a
    # club's provider ids would land on through Reep
    try:
        import urllib.request
        d = json.loads(urllib.request.urlopen("http://127.0.0.1:8792/api/bowl", timeout=30).read())
        tm, report["coverage_of"] = [str(r[d["cols"].index("tm_id")]) for r in d["rows"]], "the desk's players (Discover)"
    except Exception:
        import duckdb
        spine = (DATA / "lake" / "gold" / "spine_current.parquet").as_posix()
        tm = [x[0] for x in duckdb.sql(f"SELECT DISTINCT CAST(CAST(player_id AS BIGINT) AS VARCHAR) FROM '{spine}' WHERE player_id IS NOT NULL").fetchall()]
        report["coverage_of"] = "the current cohort (gold/spine_current)"
    report["desk_coverage"] = identity.coverage(tm)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "connect_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print("desk coverage", report.get("desk_coverage"))


if __name__ == "__main__":
    main()
