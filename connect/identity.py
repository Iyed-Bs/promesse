"""Who is who across providers: a club's Wyscout id, SkillCorner id or Impect id, onto our people (keyed on Transfermarkt).

The bridge is the Reep register (github.com/withqwerty/reep, CC0): one id per person, with that person's id at 30+
providers, from Wikidata plus mappings Reep made itself (name and birth date, with a confidence). We use its v0 CSV
release (data_version 2026.25, ), held at open/reep.
Every link keeps its method and confidence. A link Reep made by name and birth date is a candidate: we check it against
our own record of the player (birth date and name) before an engine may use it (`audit`).
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
import unicodedata
from functools import lru_cache
from pathlib import Path

import pandas as pd

REEP = Path((DATA_ROOT + "/open/reep/data"))
PERSONS = Path((DATA_ROOT + "/lake/identity/persons.parquet"))
# provider -> Reep's column for it (a new provider)
KEYS = {"transfermarkt": "key_transfermarkt", "matchdata": "key_matchdata", "wyscout": "key_wyscout", "skillcorner": "key_skillcorner",
        "impect": "key_impect", "opta": "key_opta", "sofascore": "key_sofascore", "fbref": "key_fbref", "gamerating_a": "key_gamerating_a",
        "whoscored": "key_whoscored", "understat": "key_understat"}


@lru_cache(maxsize=1)
def people() -> pd.DataFrame:
    cols = ["reep_id", "type", "name", "date_of_birth"] + list(KEYS.values())
    return pd.read_csv(REEP / "people.csv", dtype=str, usecols=lambda c: c in cols).query("type == 'player'")


@lru_cache(maxsize=1)
def custom() -> pd.DataFrame:
    """Reep's own mappings for providers Wikidata doesn't carry (MatchData, Opta, Wyscout...), each with a confidence."""
    rows = json.loads((REEP / "custom_ids.json").read_text(encoding="utf-8"))
    return pd.DataFrame(rows).astype({"external_id": str})


def links(provider: str, ids: list[str]) -> pd.DataFrame:
    """identity_links rows for a provider's ids: through Reep's own column first (Wikidata, confidence 1.0), then
    through its custom mappings (their confidence), each joined to the person's Transfermarkt id."""
    ids = [str(i) for i in ids]
    p = people()
    col = KEYS.get(provider)
    out = []
    if col and col in p:
        hit = p[p[col].isin(ids)][["reep_id", col, "key_transfermarkt", "key_matchdata"]].rename(columns={col: "external_id"})
        hit = hit.assign(confidence=1.0, method="provider id in Reep (Wikidata)")
        out.append(hit)
    c = custom()
    ch = c[(c.provider == provider) & c.external_id.isin(ids)][["reep_id", "external_id", "confidence", "source"]]
    if len(ch):
        ch = ch.merge(p[["reep_id", "key_transfermarkt", "key_matchdata"]], on="reep_id", how="left")
        ch["method"] = "Reep's own match (" + ch.pop("source") + ")"
        out.append(ch)
    if not out:
        return pd.DataFrame(columns=["source", "external_id", "reep_id", "tm_id", "matchdata_id", "confidence", "method"])
    df = pd.concat(out, ignore_index=True).drop_duplicates("external_id")
    return df.rename(columns={"key_transfermarkt": "tm_id", "key_matchdata": "matchdata_id"}).assign(source=provider)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace("-", " ").split())


def audit(lk: pd.DataFrame) -> pd.DataFrame:
    """Check each link against our own record: same birth date, and the surname appears in our name. Adds `agrees`."""
    if lk.empty:
        return lk.assign(agrees=pd.Series(dtype="boolean"))
    ours = pd.read_parquet(PERSONS, columns=["tm_id", "name", "dob"]).dropna(subset=["tm_id"])
    ours["tm_id"] = ours["tm_id"].astype("Int64").astype(str)
    p = people()[["reep_id", "name", "date_of_birth"]]
    x = lk.merge(p, on="reep_id", how="left").merge(ours, on="tm_id", how="left", suffixes=("_reep", "_ours"))
    same_dob = pd.to_datetime(x["date_of_birth"], errors="coerce") == pd.to_datetime(x["dob"], errors="coerce")
    sur = x["name_reep"].map(lambda n: _norm(n).split()[-1] if isinstance(n, str) and n.strip() else "")
    in_name = [bool(s) and s in _norm(o) for s, o in zip(sur, x["name_ours"])]
    lk = lk.copy()
    lk["agrees"] = pd.array((same_dob & pd.Series(in_name, index=x.index)).to_numpy(), dtype="boolean")
    lk.loc[x["name_ours"].isna().to_numpy(), "agrees"] = pd.NA       # a person we don't hold: nothing to check against
    return lk


def coverage(tm_ids: list[str]) -> dict:
    """Of these players (Transfermarkt ids), how many Reep carries, and with which providers' ids."""
    p = people()
    hit = p[p["key_transfermarkt"].isin([str(t) for t in tm_ids])]
    n = len(set(map(str, tm_ids)))
    return {"players": n, "in_reep": int(hit["key_transfermarkt"].nunique()),
            **{k: int(hit[c].notna().sum()) for k, c in KEYS.items() if c in hit and k != "transfermarkt"}}
