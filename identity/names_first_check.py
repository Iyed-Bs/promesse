"""Check for link.py's "names first" clustering: which persons change if the strong-name pairs are clustered
before the surname-only ones, side by side, so each change can be judged before the rule ships.

Found through the Reep audit (connect/audit_identity.py): Sven and Lars Bender, twins, came out swapped between our
EA/Transfermarkt/Wyscout records. Pair weights alone can't separate brothers (same birth date, overlapping clubs, an
older link carried as a witness), so a pair whose names agree only on the surname waits until every exact-name pair
has been placed.

    python names_first_check.py     (identity venv) -> lake/identity/names_first_changes.txt
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
from pathlib import Path

import pandas as pd

from link import ACCEPT, cluster, first_names_clash

D = Path((DATA_ROOT + "/lake/identity"))


def groups(roots: dict[str, str], uids) -> dict[str, frozenset]:
    """uid -> the frozenset of its group"""
    by: dict[str, set] = {}
    for u in uids:
        by.setdefault(roots.get(u, u), set()).add(u)
    return {u: frozenset(s) for s in by.values() for u in s}


def main() -> None:
    p = pd.read_parquet(D / "pairs.parquet")
    r = pd.read_parquet(D / "records.parquet", columns=["uid", "family", "name", "dob"])
    fam, nm, dob = dict(zip(r.uid, r.family)), dict(zip(r.uid, r.name)), dict(zip(r.uid, r.dob))
    acc = p[(p.match_probability >= ACCEPT) & (p.gamma_name >= 2)]
    clash = first_names_clash(acc)
    print(f"accepted pairs {len(acc):,}; first names clash on {int(clash.sum()):,}")
    old, new = groups(cluster(acc, fam), r.uid), groups(cluster(pd.concat([acc[~clash], acc[clash]]), fam), r.uid)
    moved = [u for u in r.uid if old[u] != new[u]]
    lab = lambda u: f"{u.split(':')[0][:2]}:{nm.get(u)}"  # noqa: E731
    lines, seen = [], set()
    for u in moved:
        if old[u] in seen:
            continue
        seen.add(old[u])
        lines.append(f"BEFORE  {' | '.join(sorted(lab(x) for x in old[u]))}   [{str(dob.get(u))[:10]}]")
        for g in {new[x] for x in old[u]}:
            lines.append(f"  AFTER {' | '.join(sorted(lab(x) for x in g))}")
    (D / "names_first_changes.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"records that move: {len(moved)}; groups before: {len(seen)}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
