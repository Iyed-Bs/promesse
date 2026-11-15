"""Promesse data: open research datasets on football (youth growth, talent identification, injuries, personality,
scouting, market), found on Zenodo, Figshare and Harvard Dataverse.

Journals increasingly require the raw data behind a paper: maturation measures, physical tests, academy injury logs,
personality inventories, scouting surveys. One by one they are small; together they are the club-side half of the
player file that public match data cannot see. This script triages the candidates, records each one's licence and
citation, and downloads the files of relevant ones (open licence, 200 MB or less per file).

Run (Patcher venv):  python open_datasets.py search    refresh the candidate list (raw/open_dataset_candidates.json)
                     python open_datasets.py fetch     triage + download into open/research/<source>-<id>/
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
import re
import sys
import time
from pathlib import Path

import requests

DATA = Path(DATA_ROOT)
CAND = DATA / "raw" / "open_dataset_candidates.json"
OUT = DATA / "open" / "research"
S = requests.Session()
S.headers["user-agent"] = "ApplicationResearch/0.1"
MAX_FILE = 200e6
QUERIES = ["youth soccer", "youth football players", "football academy", "peak height velocity soccer", "maturation soccer players",
           "talent identification football", "relative age effect football", "GPS youth soccer", "elite youth football training load",
           "football scouting", "soccer player development", "football player market value", "football tracking data",
           "football injuries dataset", "soccer personality", "football coach behaviour", "football transfer market", "soccer bio-banding",
           "football manager dismissal", "soccer coach tactics", "football playing style clustering", "soccer formation dataset",
           "football club finance", "football wages salaries", "football player migration", "football agents intermediaries",
           "soccer academy graduates", "football talent development environment", "soccer scouting reports text", "football commentary corpus",
           "soccer player ratings newspaper", "football economics replication", "soccer match event data", "football expected goals"]
FOOTBALL = re.compile(r"soccer|football|futbol|fútbol|calcio|fussball", re.I)
RELEVANT = re.compile(r"youth|academ|matur|talent|injur|personality|scout|relative age|birth quart|sprint|jump|growth|adolescen|"
                      r"market|valu|transfer|salar|teammate|playing time|tracking|spatiotemporal|load|wearable|coach|career|U-?1\d|"
                      r"performance|psycholog|bio-?band|selection|development|coach|manager|tactic|formation|style|financ|wage|"
                      r"migra|agent|intermediar|commentar|rating|expected goals|event data", re.I)
OPEN = re.compile(r"cc[- ]?by|cc[- ]?0|creative commons|public domain|odc|mit|attribution", re.I)


def search() -> None:
    hits = {}
    for q in QUERIES:
        try:
            z = S.get("https://zenodo.org/api/records", params={"q": q, "type": "dataset", "size": 25, "sort": "mostrecent"}, timeout=40).json()
            for h in z.get("hits", {}).get("hits", []):
                m = h["metadata"]
                hits.setdefault(f"zenodo-{h['id']}", {"src": "zenodo", "id": h["id"], "title": m.get("title", ""), "date": m.get("publication_date")})
        except Exception as e:
            print("zenodo", q, e)
        try:
            f = S.post("https://api.figshare.com/v2/articles/search", json={"search_for": q, "item_type": 3, "page_size": 25}, timeout=40).json()
            for a in f if isinstance(f, list) else []:
                hits.setdefault(f"figshare-{a['id']}", {"src": "figshare", "id": a["id"], "title": a.get("title", ""), "date": (a.get("published_date") or "")[:10]})
        except Exception as e:
            print("figshare", q, e)
        try:
            d = S.get("https://dataverse.harvard.edu/api/search", params={"q": q, "type": "dataset", "per_page": 20}, timeout=40).json()
            for it in d.get("data", {}).get("items", []):
                hits.setdefault(f"dataverse-{it.get('global_id')}", {"src": "dataverse", "id": it.get("global_id"), "title": it.get("name", ""),
                                                                      "date": (it.get("published_at") or "")[:10]})
        except Exception as e:
            print("dataverse", q, e)
        time.sleep(0.5)
    keep = [v for v in hits.values() if FOOTBALL.search(v["title"])]
    CAND.write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(keep)} football datasets among {len(hits)} hits")


def files_of(c: dict) -> tuple[str, str, list[dict]]:
    """(licence, citation, [{name, size, url}]) from each repository's own API."""
    if c["src"] == "zenodo":
        j = S.get(f"https://zenodo.org/api/records/{c['id']}", timeout=40).json()
        lic = (j.get("metadata", {}).get("license") or {}).get("id", "")
        cite = f"{', '.join(a.get('name', '') for a in j['metadata'].get('creators', [])[:3])} ({c['date'][:4]}). {c['title']}. Zenodo. doi:{j.get('doi')}"
        return lic, cite, [{"name": f["key"], "size": f["size"], "url": f["links"]["self"]} for f in j.get("files", [])]
    if c["src"] == "figshare":
        j = S.get(f"https://api.figshare.com/v2/articles/{c['id']}", timeout=40).json()
        lic = (j.get("license") or {}).get("name", "")
        cite = j.get("citation") or f"{c['title']}. figshare. doi:{j.get('doi')}"
        return lic, cite, [{"name": f["name"], "size": f["size"], "url": f["download_url"]} for f in j.get("files", [])]
    pid = c["id"]
    j = S.get("https://dataverse.harvard.edu/api/datasets/:persistentId/", params={"persistentId": pid}, timeout=40).json()
    v = j.get("data", {}).get("latestVersion", {})
    lic = (v.get("license") or {}).get("name", "") if isinstance(v.get("license"), dict) else str(v.get("license", ""))
    out = []
    for f in v.get("files", []):
        df = f.get("dataFile", {})
        out.append({"name": df.get("filename"), "size": df.get("filesize", 0), "url": f"https://dataverse.harvard.edu/api/access/datafile/{df.get('id')}"})
    return lic, f"{c['title']}. Harvard Dataverse. {pid}", out


def fetch() -> None:
    cands = json.loads(CAND.read_text(encoding="utf-8"))
    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    for c in cands:
        key = f"{c['src']}-{str(c['id']).replace('/', '_').replace(':', '_')}"
        if key in manifest or not RELEVANT.search(c["title"]):
            continue
        try:
            lic, cite, files = files_of(c)
        except Exception as e:
            print("skip", key, e)
            continue
        entry = {"title": c["title"], "date": c["date"], "licence": lic, "citation": cite, "files": [], "skipped": []}
        if not OPEN.search(lic or ""):
            entry["skipped"].append(f"licence not open: {lic or 'unknown'}")
        else:
            for f in files:
                if (f["size"] or 0) > MAX_FILE:
                    entry["skipped"].append(f"{f['name']} ({(f['size'] or 0) / 1e6:.0f} MB)")
                    continue
                dest = OUT / key / re.sub(r'[<>:"/\\|?*]', "_", f["name"])
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with S.get(f["url"], stream=True, timeout=120) as r:
                        r.raise_for_status()
                        with open(dest, "wb") as w:
                            for chunk in r.iter_content(1 << 20):
                                w.write(chunk)
                    entry["files"].append(dest.name)
                except Exception as e:
                    entry["skipped"].append(f"{f['name']}: {e}")
                time.sleep(0.5)
        manifest[key] = entry
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{key}: {len(entry['files'])} files, licence {lic or '?'}{' | skipped ' + '; '.join(entry['skipped']) if entry['skipped'] else ''}", flush=True)
    got = sum(1 for e in manifest.values() if e["files"])
    print(f"done: {got} datasets downloaded, {len(manifest) - got} recorded without files", flush=True)


if __name__ == "__main__":
    {"search": search, "fetch": fetch}[sys.argv[1]]()
