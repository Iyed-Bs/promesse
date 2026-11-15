"""Compares the stills of two folders (still_compare.mjs): for each picture, the share of pixels that differ by more than
8 of 255 in any channel. Under 0.5 % counts as noise (the canvas is lit and animated). Run with the Promesse venv:
    python -X utf8 still_diff.py <before dir> <after dir>"""
import sys
from pathlib import Path
from PIL import Image, ImageChops

a, b = Path(sys.argv[1]), Path(sys.argv[2])
bad = 0
for f in sorted(a.glob("*.png")):
    g = b / f.name
    if not g.exists():
        print(f.name, "MISSING in after"); bad += 1; continue
    ia, ib = Image.open(f).convert("RGB"), Image.open(g).convert("RGB")
    if ia.size != ib.size:
        print(f.name, "SIZE differs", ia.size, ib.size); bad += 1; continue
    d = ImageChops.difference(ia, ib).convert("L").point(lambda v: 255 if v > 8 else 0)
    share = sum(1 for v in d.getdata() if v) / (ia.size[0] * ia.size[1]) * 100
    print(f"{f.name}: {share:.3f} % of pixels differ", "(noise)" if share < 0.5 else "(DIFFERENT)")
    bad += share >= 0.5
print("RESULT:", "no difference beyond noise" if not bad else f"{bad} picture(s) differ")
