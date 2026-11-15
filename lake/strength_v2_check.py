"""Is strength v2's gain real? A paired bootstrap of the test-period Brier difference (blend minus the loop's Elo), by
match, and the same split by kind of competition. Uses the settings strength_v2.py chose on 2023/24.

    python strength_v2_check.py      (Patcher venv)
"""
import json

import numpy as np

import strength_v2 as s

df = s.load()
start = s.starting_levels(df)
cfg = json.loads((s.LAKE / "strength" / "v2_ladder.json").read_text(encoding="utf-8"))["settings"]
e1 = s.elo_plus(df, start=start, **cfg["elo+"])
g2 = s.goals_model(df, cfg["goals"]["lr"], start, cfg["goals"]["scale"])
blend = (e1 + g2) / 2
test = df.date >= s.TEST_FROM
y = df.res[test].values
d = (blend[test].values - y) ** 2 - (df.p_home[test].values - y) ** 2   # negative = v2 better on that match
rng = np.random.default_rng(7)
boots = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)])
lo, hi = np.percentile(boots, [2.5, 97.5])
print(f"test matches {len(d):,}: Brier difference {d.mean():+.5f} (95 % interval {lo:+.5f} to {hi:+.5f}); "
      f"v2 better in {100 * (boots < 0).mean():.1f} % of resamples")
youth = df.competition[test].str.contains(r"U1[7-9]|U2[0-3]|Youth|Under|Premier League 2|Reserve", regex=True, na=False).values
for name, m in (("youth and reserve competitions", youth), ("senior competitions", ~youth)):
    print(f"  {name:32s} {m.sum():6,d} matches: {d[m].mean():+.5f}")
