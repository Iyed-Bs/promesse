"""Identity v3, the gate: 300 accepted links drawn at random, 100 in each confidence band, with both records' evidence
side by side, to be labelled by hand. Precision is weighted by how many accepted links each band holds; the ids go
downstream only at >= 99.5 %.

    python gate.py draw          -> lake/identity/gate.csv (label column empty; fixed seed, so the draw is repeatable)
    python gate.py score         -> precision per band and overall, from the labels (same / different / unsure)
    python gate.py audit         -> _research/football/the project notes: 30 of the labelled pairs for the maintainer to check on
                                    the desk (every pair labelled different or unsure, then a random draw of the rest)
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import sys
from pathlib import Path

import pandas as pd

D = Path((DATA_ROOT + "/lake/identity"))
BANDS = [(0.95, 0.99), (0.99, 0.999), (0.999, 1.01)]
PER_BAND = 100


def evidence(r: pd.Series) -> str:
    dob = str(r["dob_lo"])[:10] if str(r["dob_lo"])[:10] == str(r["dob_hi"])[:10] else \
        f"{str(r['dob_lo'])[:7]}..{str(r['dob_hi'])[:7]}"
    cs = list(r["club_seasons"])[-3:]
    return f"{r['name']} / {r['alt_name'] or ''} | {dob} | {r['nation'] or '?'} | {r['height'] if pd.notna(r['height']) else '?'} cm | " \
           f"{r['foot'] or '?'} | {r['pos_group'] or '?'} | {', '.join(cs)}"


def draw() -> None:
    pairs = pd.read_parquet(D / "pairs.parquet", columns=["unique_id_l", "unique_id_r", "match_probability"])
    reg = pd.read_parquet(D / "registry.parquet").set_index("uid")["person_id"]
    acc = pairs[(pairs.match_probability >= BANDS[0][0]) &
                (pairs.unique_id_l.map(reg).values == pairs.unique_id_r.map(reg).values)].copy()
    rec = pd.read_parquet(D / "records.parquet").set_index("uid")
    rows = []
    for lo, hi in BANDS:
        band = acc[(acc.match_probability >= lo) & (acc.match_probability < hi)]
        for r in band.sample(min(PER_BAND, len(band)), random_state=7).itertuples(index=False):
            rows.append({"band": f"{lo}-{min(hi, 1)}", "band_size": len(band), "p": round(r.match_probability, 5),
                         "uid_l": r.unique_id_l, "uid_r": r.unique_id_r, "person_id": reg[r.unique_id_l],
                         "left": evidence(rec.loc[r.unique_id_l]), "right": evidence(rec.loc[r.unique_id_r]),
                         "label": "", "note": ""})
    out = pd.DataFrame(rows)
    out.insert(0, "k", range(1, len(out) + 1))
    out.to_csv(D / "gate.csv", index=False, encoding="utf-8")
    print(f"gate.csv: {len(out)} pairs; accepted links per band: "
          + ", ".join(f"{b} {n:,}" for b, n in out.groupby("band")["band_size"].first().items()))


def score() -> None:
    g = pd.read_csv(D / "gate.csv", encoding="utf-8").fillna({"label": ""})
    done = g[g.label.isin(["same", "different"])]
    tot_w = prec_w = 0.0
    for b, x in done.groupby("band"):
        prec = (x.label == "same").mean()
        w = x.band_size.iloc[0]
        tot_w += w
        prec_w += w * prec
        print(f"band {b}: {len(x)} labelled, precision {prec:.1%} ({(x.label == 'different').sum()} wrong)")
    if tot_w:
        print(f"overall (weighted by band size): {prec_w / tot_w:.2%} | unsure {int((g.label == 'unsure').sum())} | "
              f"unlabelled {int((g.label == '').sum())} | gate {'PASSED' if prec_w / tot_w >= 0.995 else 'not passed'}")


FAM = {"ea": "EA", "tm": "Transfermarkt", "konami": "privately collected game ratings / PES", "matchdata": "MatchData", "statsbomb": "StatsBomb",
       "wyscout": "Wyscout"}


def clean(e: str) -> str:
    """Missing values read as ?, an empty alias disappears."""
    import re
    return re.sub(r"\bnan\b", "?", e.replace(" / nan |", " |"))


def audit() -> None:
    g = pd.read_csv(D / "gate.csv", encoding="utf-8")
    reg = pd.read_parquet(D / "registry.parquet").set_index("uid")["person_id"]
    g["now"] = ["linked" if reg.get(a) == reg.get(b) else "no longer linked (rules fixed after the gate)"
                for a, b in zip(g.uid_l, g.uid_r)]
    flagged = g[g.label != "same"]
    rest = g[g.label == "same"].sample(30 - len(flagged), random_state=11)
    pick = pd.concat([flagged, rest]).sort_values("k")
    lines = ["# Identity v3: check my labels (30 pairs, about 15 minutes)", "",
             "Each pair is two records that identity v3 now treats as one person. I labelled all 300 of the gate; these "
             "30 are for you to check: the ones I marked different or unsure, then a random draw of the ones I marked "
             "same. Tick the box when you agree with my label; otherwise write your answer in the brackets "
             "(`[same]`, `[different]` or `[?]`) or leave a comment. Your football memory is the check here.", "",
             "Each record reads: name / alias · birth date (or the window its ages allow) · nation · height · foot · "
             "position · its last club-seasons.", ""]
    for r in pick.itertuples():
        fl, fr = r.uid_l.split(":")[0], r.uid_r.split(":")[0]
        lines += [f"- [ ] **{r.k}** · {FAM[fl]} and {FAM[fr]} · match probability {r.p:.3f} · my label: **{r.label}**"
                  + (f" ({r.note})" if isinstance(r.note, str) and r.note else "") + f" · now: {r.now}",
                  f"      {FAM[fl]}: {clean(r.left)}", f"      {FAM[fr]}: {clean(r.right)}"]
    out = Path("")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{out}: {len(pick)} pairs ({len(flagged)} flagged)")


if __name__ == "__main__":
    {"draw": draw, "score": score, "audit": audit}[sys.argv[1]]()
