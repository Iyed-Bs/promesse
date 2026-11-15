"""Identity v3, stable person ids: minted once, never reassigned.

Each run of link.py regroups the records; this step decides which person id every group carries:
  - a group whose records already hold one id keeps it;
  - a group holding several ids (a merge) keeps the oldest; the others are retired and logged;
  - an id found in several groups (a split) stays with the group holding most of its records (ties: the group with
    the record registered first); the other groups mint new ids, logged;
  - a group with no id mints the next one, in a fixed order (by its smallest record uid), so reruns are repeatable.

Writes lake/identity/: registry.parquet (uid -> person_id, first registered), persons.parquet (one row per person:
the id in each family, a display name, the birth date), id_log.jsonl (every mint, merge and split, dated).

    python ids.py               (identity venv; after link.py)
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
from datetime import date
from pathlib import Path

import pandas as pd

D = Path((DATA_ROOT + "/lake/identity"))
FAMILIES = ["ea", "tm", "konami", "matchdata", "statsbomb", "wyscout"]
PRIORITY = {"tm": 0, "ea": 1, "wyscout": 2, "matchdata": 3, "statsbomb": 4, "konami": 5}   # whose name and date to show


def pid_num(p: str) -> int:
    return int(p[1:])


def main() -> None:
    cl = pd.read_parquet(D / "clusters.parquet")
    today = date.today().isoformat()
    reg_path = D / "registry.parquet"
    reg = pd.read_parquet(reg_path) if reg_path.exists() else pd.DataFrame(columns=["uid", "person_id", "first_seen"])
    old = dict(zip(reg["uid"], reg["person_id"]))
    seen = dict(zip(reg["uid"], reg["first_seen"]))
    log = []

    cl["old"] = cl["unique_id"].map(old)
    groups = cl.groupby("group")
    # Which group may keep each existing id: most of its records, then the earliest-registered record.
    claim = (cl.dropna(subset=["old"]).assign(seen=lambda x: x["unique_id"].map(seen))
             .groupby(["old", "group"]).agg(n=("unique_id", "size"), first=("seen", "min")).reset_index()
             .sort_values(["old", "n", "first"], ascending=[True, False, True]))
    keeper = claim.drop_duplicates("old").set_index("old")["group"].to_dict()

    assign: dict[str, str] = {}
    fresh = []
    for g, rows in groups:
        mine = sorted({p for p in rows["old"].dropna() if keeper.get(p) == g}, key=pid_num)
        if mine:
            assign[g] = mine[0]
            for retired in mine[1:]:
                log.append({"date": today, "event": "merge", "kept": mine[0], "retired": retired})
        else:
            fresh.append((rows["unique_id"].min(), g))
            for p in set(rows["old"].dropna()):
                log.append({"date": today, "event": "split", "from": p, "group_first_uid": rows["unique_id"].min()})
    nxt = max([pid_num(p) for p in old.values()], default=0) + 1
    for _, g in sorted(fresh):
        assign[g] = f"P{nxt:07d}"
        nxt += 1
    minted = len(fresh)

    cl["person_id"] = cl["group"].map(assign)
    out = cl[["unique_id", "person_id"]].rename(columns={"unique_id": "uid"})
    out["first_seen"] = out["uid"].map(seen).fillna(today)
    out.to_parquet(reg_path)

    rec = pd.read_parquet(D / "records.parquet", columns=["uid", "family", "source_id", "name", "dob"])
    rec = rec.merge(out[["uid", "person_id"]], on="uid")
    wide = rec.pivot_table(index="person_id", columns="family", values="source_id", aggfunc="first")
    wide = wide.reindex(columns=FAMILIES).add_suffix("_id")
    def common_dob(s: pd.Series):
        """The birth date most of the person's sources agree on; on a tie, the highest-priority source's. (Audit of
        when sources disagree, it's one source's typo, most often EA's, so the majority is the safer date.)"""
        s = s.dropna()
        if s.empty:
            return None
        counts = s.map(s.value_counts())
        return s[counts == counts.max()].iloc[0]

    shown = (rec.assign(pr=rec["family"].map(PRIORITY)).sort_values("pr", kind="stable").groupby("person_id")
             .agg(name=("name", "first"), dob=("dob", common_dob)))
    persons = shown.join(wide).reset_index()
    persons["n_sources"] = persons[[f + "_id" for f in FAMILIES]].notna().sum(axis=1)
    persons.to_parquet(D / "persons.parquet")
    with open(D / "id_log.jsonl", "a", encoding="utf-8") as f:
        for e in log:
            f.write(json.dumps(e) + "\n")
        f.write(json.dumps({"date": today, "event": "run", "persons": len(persons), "minted": minted,
                            "merges": sum(e["event"] == "merge" for e in log),
                            "splits": sum(e["event"] == "split" for e in log)}) + "\n")
    print(f"persons {len(persons):,} | minted {minted:,} | merges {sum(e['event'] == 'merge' for e in log)} | "
          f"splits {sum(e['event'] == 'split' for e in log)} | in 2+ sources {int((persons.n_sources > 1).sum()):,}")


if __name__ == "__main__":
    main()
