"""The data dial, measured on what we hold.

The engine's penalised logistic (T1's C), 2014-2020 -> T2, with one channel (a group of the engine's inputs) removed or
added alone, on everyone and on the richest public records. Paired player bootstrap for every difference.

    python models/data_dial.py   (Promesse venv) -> lake/models/data_dial.json
"""
import json

import numpy as np
from sklearn.metrics import roc_auc_score

import ladder as L

T = "y_reg3"
CHANNELS = {
    "profile": ["height", "left_foot", "birth_quarter"],
    "minutes": ["min_365", "min_730", "qmin_365", "qmin_730", "league_min_365", "europe_min_730", "apps_365",
                "age_first_app", "qmin_cum", "seasons_senior"],
    "competition level and role": ["last_club_level", "last_share", "last_level", "best_share", "best_level", "clubs_2y"],
    "career shape": ["growth_q", "share_trend", "level_step", "cohort_pct"],
    "youth international finals": ["yt_selected", "yt_squads", "yt_top_level"],
    "MatchData minutes": ["fm_min_365", "fm_youth_min_365"],
}
BASE = ["age", "pos_GK", "pos_DEF", "pos_MID", "pos_ATT"]


def boot(y, ids, a, b, n=1000, seed=7):
    """AUC(a) - AUC(b), resampling players."""
    rng = np.random.default_rng(seed)
    uniq = np.unique(ids)
    pos = {u: np.flatnonzero(ids == u) for u in uniq}
    g = []
    for _ in range(n):
        i = np.concatenate([pos[u] for u in rng.choice(uniq, len(uniq))])
        if y[i].min() != y[i].max():
            g.append(roc_auc_score(y[i], a[i]) - roc_auc_score(y[i], b[i]))
    return {"point": round(float(roc_auc_score(y, a) - roc_auc_score(y, b)), 4),
            "ci95": [round(float(np.percentile(g, 2.5)), 4), round(float(np.percentile(g, 97.5)), 4)]}


def main() -> None:
    d = L.frame(T)
    cols = L.features(d)
    grouped = sorted(c for g in CHANNELS.values() for c in g)
    assert set(BASE) | set(grouped) == set(cols), set(cols) ^ (set(BASE) | set(grouped))
    C = json.loads((L.OUT / "ladder_y_reg3.json").read_text(encoding="utf-8"))["settings_chosen_on_T1"]["C"]
    tr, te = L.split(d, L.T2)
    ytr = tr[T].to_numpy()
    fit = {}

    def pred(cs):
        k = tuple(cs)
        if k not in fit:
            fit[k] = L.Logit(list(cs), C).fit(tr, ytr).predict(te)
        return fit[k]

    rich = te.min_365.notna().to_numpy() & (te.min_365 > 0).to_numpy()
    out = {"model": "penalised logistic, C from T1, train 2014-2020, test 2021-2022; age and position in every variant",
           "gate": "a channel adds something only if its drop-one 95 % interval is above zero; else not separable from zero here"}
    y, ids = te[T].to_numpy(), te.player_id.to_numpy()
    full = pred(cols)
    for pop, m in (("everyone under 21", np.ones(len(te), bool)), ("richest records (senior minutes in the last year)", rich)):
        yy, ii, ff = y[m], ids[m], full[m]
        block = {"n": int(m.sum()), "n_players": int(len(np.unique(ii))), "base_rate": round(float(yy.mean()), 4),
                 "auc_full": round(float(roc_auc_score(yy, ff)), 4),
                 "auc_age_position_only": round(float(roc_auc_score(yy, pred(BASE)[m])), 4), "channels": {}, "strip": []}
        for name, g in CHANNELS.items():
            without = pred([c for c in cols if c not in g])[m]
            alone = pred(BASE + g)[m]
            drop = boot(yy, ii, ff, without)
            block["channels"][name] = {"inputs": g, "auc_without": round(float(roc_auc_score(yy, without)), 4),
                                       "drop_one": drop, "adds_something": bool(drop["ci95"][0] > 0),
                                       "add_one_auc": round(float(roc_auc_score(yy, alone)), 4),
                                       "add_one_vs_base": boot(yy, ii, alone, pred(BASE)[m])}
        # the cumulative strip, strongest channel first, back to age + position
        order = sorted(CHANNELS, key=lambda k: -block["channels"][k]["drop_one"]["point"])
        keep = list(cols)
        prev = ff
        for name in order:
            keep = [c for c in keep if c not in CHANNELS[name]]
            p = pred(keep)[m]
            block["strip"].append({"removed": name, "auc": round(float(roc_auc_score(yy, p)), 4), "step": boot(yy, ii, prev, p)})
            prev = p
        out[pop] = block
    (L.OUT / "data_dial.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    for pop in [k for k in out if isinstance(out[k], dict) and "channels" in out[k]]:
        b = out[pop]
        print(pop, b["n"], "full", b["auc_full"], "base", b["auc_age_position_only"])
        for k, v in b["channels"].items():
            print(f"  {k:30s} drop {v['drop_one']['point']:+.4f} {v['drop_one']['ci95']}  adds={v['adds_something']}  add-one {v['add_one_auc']}")
        for s in b["strip"]:
            print("   strip", s["removed"], s["auc"])


if __name__ == "__main__":
    main()
