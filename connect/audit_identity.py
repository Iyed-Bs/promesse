"""How right is our identity layer? Our links (lake/identity/persons.parquet: one person, his Transfermarkt, MatchData, EA,
Wyscout ids) checked against an independent register (Reep, CC0: Wikidata plus its own name and birth-date matches).

For every person we link to Transfermarkt AND another provider, and Reep links the same Transfermarkt id to that
provider: do the two agree? Split by how Reep made its link (Wikidata, or its own match with a confidence), so a
disagreement can be read: Wikidata disagreeing with us points at our error; Reep's own low-confidence match
disagreeing points at theirs. Disagreements are listed for review, never fixed automatically. Also: the identity
conflicts we hold back (lake/identity/review.parquet), with what Reep says about each.

    python -m connect.audit_identity     (from the football folder) -> lake/quality/identity_vs_reep.json + .csv
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
from pathlib import Path

import pandas as pd

from connect import identity

LAKE = Path((DATA_ROOT + "/lake"))
OUT = LAKE / "quality"
# Reep provider -> our column. EA is not checked: Reep's "gamerating_a" column is not EA's numbering (Messi: 229397 there,
# 158023 at EA), so it can say nothing about our EA links (2 of 3,748 "agreed", by chance)
OURS = {"matchdata": "matchdata_id", "wyscout": "wyscout_id"}


def reep_links(provider: str) -> pd.DataFrame:
    """tm_id -> the provider's id(s), with how Reep knows it"""
    p = identity.people()
    col = identity.KEYS[provider]
    out = []
    if col in p:
        w = p[p[col].notna() & p["key_transfermarkt"].notna()][["key_transfermarkt", col]].rename(columns={"key_transfermarkt": "tm_id", col: "ext"})
        out.append(w.assign(method="Wikidata", confidence=1.0))
    c = identity.custom()
    c = c[c.provider == provider].merge(p[["reep_id", "key_transfermarkt"]].dropna(), on="reep_id")
    if len(c):
        out.append(c.rename(columns={"key_transfermarkt": "tm_id", "external_id": "ext"})[["tm_id", "ext", "confidence"]].assign(method="Reep's own match"))
    if not out:
        return pd.DataFrame(columns=["tm_id", "ext", "method", "confidence"])
    df = pd.concat(out, ignore_index=True)
    df["ext"] = df["ext"].astype(str).str.replace(r"\.0$", "", regex=True)
    df["tm_id"] = df["tm_id"].astype(str)
    return df


def main() -> None:
    ours = pd.read_parquet(LAKE / "identity" / "persons.parquet")
    ours = ours[ours["tm_id"].notna()].copy()
    ours["tm_id"] = ours["tm_id"].astype("Int64").astype(str)
    report, rows = {"built": pd.Timestamp.now().isoformat(timespec="seconds"), "persons_with_tm": int(len(ours)), "providers": {},
                    "not_checked": {"ea": "Reep's gamerating_a column is not EA's numbering (Messi 229397 vs EA 158023)"}}, []
    for prov, col in OURS.items():
        mine = ours[ours[col].notna()][["person_id", "name", "tm_id", col]].copy()
        mine["ours"] = mine[col].astype("Int64").astype(str) if pd.api.types.is_numeric_dtype(mine[col]) else mine[col].astype(str).str.replace(r"\.0$", "", regex=True)
        theirs = reep_links(prov)
        both = mine.merge(theirs, on="tm_id", how="inner")
        if both.empty:
            report["providers"][prov] = {"ours": int(len(mine)), "checked": 0}
            continue
        # a tm id can carry several provider ids in Reep (duplicates at the provider): agree if ours is among them
        g = both.groupby(["person_id", "tm_id", "ours", "name"]).agg(agree=("ext", lambda s: False), exts=("ext", lambda s: sorted(set(s))),
                                                                       method=("method", lambda s: "Wikidata" if (s == "Wikidata").any() else "Reep's own match"),
                                                                       confidence=("confidence", "max")).reset_index()
        g["agree"] = [o in e for o, e in zip(g["ours"], g["exts"])]
        rep = {"ours": int(len(mine)), "checked": int(len(g)), "agree": int(g["agree"].sum()), "agree_share": round(float(g["agree"].mean()), 4)}
        for m, sub in g.groupby("method"):
            rep[m] = {"checked": int(len(sub)), "agree_share": round(float(sub["agree"].mean()), 4)}
        hi = g[g["confidence"] >= 0.95]
        rep["reep_confidence_0.95_up"] = {"checked": int(len(hi)), "agree_share": round(float(hi["agree"].mean()), 4) if len(hi) else None}
        report["providers"][prov] = rep
        bad = g[~g["agree"]].assign(provider=prov)
        rows.append(bad[["provider", "person_id", "name", "tm_id", "ours", "exts", "method", "confidence"]])
    # the conflicts we hold back: what Reep says about each
    rv = LAKE / "identity" / "review.parquet"
    if rv.exists():
        r = pd.read_parquet(rv)
        report["held_back"] = {"rows": int(len(r)), "columns": list(r.columns)[:12]}
    OUT.mkdir(exist_ok=True)
    dis = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if len(dis):
        dis["exts"] = dis["exts"].map(lambda e: " ".join(e))
    dis.to_csv(OUT / "identity_vs_reep_disagreements.csv", index=False)
    (OUT / "identity_vs_reep.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=1, ensure_ascii=False))
    print(f"{len(dis):,} disagreements listed")


if __name__ == "__main__":
    main()
