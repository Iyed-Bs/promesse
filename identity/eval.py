"""Identity v3: agreement with identity v2, run after every linkage (python eval.py, identity venv).

For each of v2's link types: how many v2 links v3 keeps in one person, and how many it contradicts (v3 puts the
record with a different record of the other family). Then v3's links per family pair. This is a consistency check,
not the proof: the proof is the hand-labelled gate (gate.py, precision >= 99.5 %).
"""
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
from collections import Counter
from pathlib import Path

import pandas as pd

F = Path(DATA_ROOT)
cl = pd.read_parquet(F / "lake/identity/clusters.parquet").set_index("unique_id")["group"]
v2 = pd.read_parquet(F / "identity_v2.parquet")


def check(a: str, b: str, fa: str, fb: str) -> None:
    x = v2.dropna(subset=[a, b])
    ga = (fa + ":" + x[a].astype("Int64").astype(str)).map(cl)
    gb = (fb + ":" + x[b].astype("Int64").astype(str)).map(cl)
    known = ga.notna() & gb.notna()
    same = known & (ga == gb)
    has_b = cl[cl.index.str.startswith(fb + ":")].reset_index().groupby("group")["unique_id"].first()
    contra = known & ~same & ga.map(has_b).notna()
    print(f"v2 {fa}-{fb}: {len(x):,} links | same v3 person {same.sum():,} ({same.sum() / max(known.sum(), 1):.1%}) | "
          f"v3 says another {fb}: {contra.sum():,}")


check("ea_id", "tm_id", "ea", "tm")
check("fl_id", "ea_id", "konami", "ea")
check("fl_id", "tm_id", "konami", "tm")
fams = pd.DataFrame({"g": cl.values, "f": cl.index.str.split(":").str[0]}).groupby("g")["f"].apply(lambda s: sorted(set(s)))
pairs = Counter((s[i], s[j]) for s in fams for i in range(len(s)) for j in range(i + 1, len(s)))
print("v3 links by family pair:", ", ".join(f"{a}-{b} {n:,}" for (a, b), n in pairs.most_common()))
