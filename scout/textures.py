"""The Scout Desk's ground: board-marked concrete, as a seamless tile for daylight (15:00) and floodlights (20:45).

Formwork planks 140 px tall leave faint tone steps, a seam between planks and the grain of the wood; tie-rod holes sit
in a regular grid; pores and fine grain finish it. Seamless both ways (the tile is a whole number of planks, every
wave has a whole number of periods across it). Deterministic: the same seed draws the same concrete.

    python scout/textures.py      (Promesse venv) -> scout/web/img/concrete-day.webp, concrete-night.webp
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

W, H, PLANK = 640, 560, 140
OUT = Path(__file__).resolve().parent / "web" / "img"


def oklch_to_srgb(L: float, C: float, h: float) -> np.ndarray:
    a, b = C * np.cos(np.radians(h)), C * np.sin(np.radians(h))
    l_, m_, s_ = L + 0.3963377774 * a + 0.2158037573 * b, L - 0.1055613458 * a - 0.0638541728 * b, L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    rgb = np.array([4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
                    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
                    -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s])
    rgb = np.clip(rgb, 0, 1)
    return np.where(rgb <= 0.0031308, 12.92 * rgb, 1.055 * rgb ** (1 / 2.4) - 0.055) * 255


def concrete(base: np.ndarray, amp: float, seed: int = 7) -> Image.Image:
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:H, 0:W].astype(float)
    d = np.zeros((H, W))
    plank = (y // PLANK).astype(int)
    d += np.array([0.9, -0.6, 0.3, -1.0])[plank] * amp                   # each plank pours a shade apart
    for _ in range(6):                                                    # wood grain: long horizontal streaks
        fx, fy = rng.integers(1, 4), rng.integers(8, 30)
        d += 0.35 * amp * np.sin(2 * np.pi * (fx * x / W + fy * (y % PLANK) / PLANK + rng.random())) * \
            np.sin(2 * np.pi * (rng.integers(1, 3) * x / W + rng.random()))
    seam = (y % PLANK)
    d[seam == 0] -= 3.2 * amp                                             # the seam between two planks
    d[seam == 1] += 0.8 * amp
    for py in range(PLANK // 2, H, PLANK * 2):                            # tie-rod holes, on every other plank
        for px in (W // 4, 3 * W // 4):
            r = np.hypot(x - px, y - py)
            d -= 5.5 * amp * np.clip(1 - r / 5.0, 0, 1)
            d += 1.2 * amp * np.clip(1 - np.abs(r - 6.0) / 1.2, 0, 1) * (y > py)
    pores = rng.random((H, W)) < 0.0016                                   # air pockets
    d[pores] -= 3.0 * amp
    d += rng.normal(0, 0.55 * amp, (H, W))                                # fine grain
    img = np.clip(base[None, None, :] + d[..., None], 0, 255).astype(np.uint8)
    return Image.fromarray(img, "RGB")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    concrete(oklch_to_srgb(0.925, 0.006, 80), amp=2.6).save(OUT / "concrete-day.webp", lossless=True, method=6)
    concrete(oklch_to_srgb(0.185, 0.006, 75), amp=1.7, seed=11).save(OUT / "concrete-night.webp", lossless=True, method=6)
    print({p.name: p.stat().st_size for p in OUT.glob("concrete-*.webp")})


if __name__ == "__main__":
    main()
