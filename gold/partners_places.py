"""Promesse T3c, design 1: partners read from places, not totals.

The first test (gold/partners.py) compared a player's match totals beside a partner against without him, and failed:
totals blur where and when a player gets the ball. Here the same with-and-without comparison reads places, from Impect's
open events (Bundesliga 2023/24, 306 matches; research only: credit Impect, never redistributed).

1. Starts. An outfield start with 60+ minutes (Impect's play duration). His line comes from his starting position (back
   line, midfield, attacking midfield, forwards); his partners are his neighbours in it, ordered by Impect's position
   side (left to right), among starters with 60+ minutes.
2. Places, per start, in his team's frame (depth from -52.5 m, own goal, to +52.5 m; width = distance from the long axis):
     rec_x, rec_width   the average depth and width of his open-play receptions (no set-piece phase)
     btl                his share of receptions Impect tags between the lines (AVAILABILITY_BTL)
     half_space         his share in the two half-space lanes
     box                his share in the opponent's box
     def_x, def_width   the average depth and width of his defensive actions: his interceptions, blocks, clearances,
                        loose-ball regains and ground duels (a duel only when his team is out of possession: Impect
                        writes one for each side), plus every opponent action that names him as presser or duel opponent
   A start enters the reception places with 10+ receptions, the defensive ones with 5+ actions.
   The baseline rung, the first test's kind of measure on the same starts: receptions, box receptions and defensive
   actions, each per 90.
3. Adjusted as in the first test: home and away and the opponent's strength (his season xG difference per match, from
   Impect's shot xG) come out, one slope per line and measure; then centred on his own team-line mean.
4. Pair effects (F beside P against F without P) and role patterns, as in gold/partners.py, measure by measure: a start
   missing a place (too few receptions) sits out of that measure only.

Gates:
  G1 per measure: pairs with 10+ starts each side; each side split odd and even by date; Spearman-Brown >= 0.5, computed
     with 30+ pairs (fewer: not testable, which is not a pass).
  G2 role patterns replicate: 15+ players in each random half, half means correlate >= 0.5, computed with 10+ testable
     patterns. Roles: player_roles 2023-2024 through Reep, only links that pass the identity audit (our record's birth
     date and name, and Impect's own birth date).
  G3 balance, reported. Also reported, not a gate: each measure's ICC (the bet: places are steadier than totals).
Decisions fixed before the run: a measure that passes G1 may show its shrunk pair effects on the desk, marked
Bundesliga 2023/24. If none passes, nothing is tuned on this season; a re-run with other thresholds is exploratory and
never counts as a pass.

    python gold/partners_places.py [--rebuild]   (Promesse venv) -> lake/impect/starts.parquet, people.parquet;
        lake/gold/partner_places_effects.parquet, partner_places_patterns.parquet, partners_places_report.json
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from partners import MIN_HALF, MIN_ROLE_SIDE, MIN_SIDE, MIN_SPLIT, SEED, smd  # noqa: E402  (the first test's thresholds)

DATA = Path(DATA_ROOT)
IMPECT = DATA / "open" / "impect" / "data"
LAKE = DATA / "lake" / "impect"
GOLD = DATA / "lake" / "gold"
SEASON = "2023-2024"                                    # player_roles' label for Impect's one season
MIN_SECONDS, MIN_REC, MIN_DEF, MIN_PAIRS, MIN_PATTERNS = 3600, 10, 5, 30, 10
XG_KPI = 82                                             # SHOT_XG in kpi_definitions.json

# the measures (only before a fresh season is opened; this one is spent once it runs)
PLACES = ["rec_x", "rec_width", "btl", "half_space", "box", "def_x", "def_width"]
TOTALS = ["receptions", "box_receptions", "def_actions"]
MEASURES = PLACES + TOTALS
# which count a place needs before its average means anything
NEEDS = {**{m: ("n_rec", MIN_REC) for m in ("rec_x", "rec_width", "btl", "half_space", "box")},
         **{m: ("n_def", MIN_DEF) for m in ("def_x", "def_width")}}
LINE = {"CENTRAL_DEFENDER": "back line", "LEFT_WINGBACK_DEFENDER": "back line", "RIGHT_WINGBACK_DEFENDER": "back line",
        "DEFENSE_MIDFIELD": "midfield", "CENTRAL_MIDFIELD": "midfield",
        "ATTACKING_MIDFIELD": "attacking midfield", "LEFT_WINGER": "attacking midfield", "RIGHT_WINGER": "attacking midfield",
        "CENTER_FORWARD": "forwards"}
SIDE = {"LEFT": 0, "CENTRE_LEFT": 1, "CENTRE": 2, "CENTRE_RIGHT": 3, "RIGHT": 4}
DEF_TYPES = {"INTERCEPTION", "BLOCK", "CLEARANCE", "LOOSE_BALL_REGAIN", "GROUND_DUEL"}
HALF_SPACES = {"LEFT_HALF_SPACE", "RIGHT_HALF_SPACE"}


def _read(kind: str, mid: str):
    return json.loads((IMPECT / kind / f"{kind}_{mid}.json").read_text(encoding="utf-8"))


def _match(mid: str) -> tuple[list[dict], dict]:
    """one match -> a row per outfield start with 60+ minutes (places and totals), and each squad's shot xG"""
    lu, pk, ev = _read("lineups", mid), _read("player_kpis", mid), _read("events", mid)
    secs, xg, team_of = {}, {}, {}
    for side in ("squadHome", "squadAway"):
        for p in pk[side]["players"]:
            secs[p["id"]] = p.get("playDuration") or 0.0
            xg[pk[side]["id"]] = xg.get(pk[side]["id"], 0.0) + sum(k["value"] or 0 for k in p.get("kpis", []) if k["kpiId"] == XG_KPI)
        team_of.update({p["id"]: lu[side]["id"] for p in lu[side]["players"]})
    # each squad's frame per period, from its own passes: adjCoordinates = raw x flip (x and y turn together)
    votes: dict[tuple, list] = {}
    for e in ev:
        s = e.get("start") or {}
        raw, adj = s.get("coordinates") or {}, s.get("adjCoordinates") or {}
        if e["actionType"] == "PASS" and raw.get("x") and adj.get("x") and abs(raw["x"]) > 1:
            votes.setdefault((e["periodId"], e["squadId"]), []).append(np.sign(raw["x"] * adj["x"]))
    flip = {k: float(np.sign(np.median(v)) or 1.0) for k, v in votes.items()}
    rec: dict[int, list] = {}       # player -> (depth, width, between the lines, half-space, box) per reception
    dfn: dict[int, dict] = {}       # player -> {event id: (depth, width)}, one entry per event even if named twice
    for e in ev:
        s = e.get("start") or {}
        raw = s.get("coordinates") or {}
        if raw.get("x") is None or raw.get("y") is None:
            continue
        p, sq, per = (e.get("player") or {}).get("id"), e["squadId"], e["periodId"]

        def at(team):  # this event's place in that team's frame
            f = flip.get((per, team))
            return None if f is None else (raw["x"] * f, abs(raw["y"]))
        if e["actionType"] == "RECEPTION" and p and e.get("phase") != "SET_PIECE" and not e.get("inferredSetPiece"):
            if (xy := at(sq)) is not None:
                rec.setdefault(p, []).append((*xy, e.get("action") == "AVAILABILITY_BTL", s.get("lane") in HALF_SPACES,
                                              s.get("pitchPosition") == "OPPONENT_BOX"))
        if p and e["actionType"] in DEF_TYPES and not (e["actionType"] == "GROUND_DUEL" and sq == e.get("currentAttackingSquadId")):
            if (xy := at(sq)) is not None:
                dfn.setdefault(p, {})[e["id"]] = xy
        for q in ((e.get("duel") or {}).get("playerId"), e.get("pressingPlayerId")):
            if q and team_of.get(q) not in (None, sq) and (xy := at(team_of[q])) is not None:
                dfn.setdefault(q, {})[e["id"]] = xy
    rows, home_id = [], lu["squadHome"]["id"]
    for side, other in (("squadHome", "squadAway"), ("squadAway", "squadHome")):
        for sp in lu[side]["startingPositions"]:
            pid, pos = sp["playerId"], sp["position"]
            if pos not in LINE or secs.get(pid, 0) < MIN_SECONDS:
                continue
            mins = secs[pid] / 60
            r = np.array(rec.get(pid, []), dtype=float).reshape(-1, 5)
            d = np.array(list(dfn.get(pid, {}).values()), dtype=float).reshape(-1, 2)
            row = {"match_id": mid, "date": lu["dateTime"][:10], "team_id": lu[side]["id"], "opp_id": lu[other]["id"],
                   "home": float(lu[side]["id"] == home_id), "formation": lu[side].get("startingFormation"), "player_id": pid, "position": pos,
                   "side": SIDE.get(sp.get("positionSide"), 2), "line": LINE[pos], "minutes": mins,
                   "n_rec": len(r), "n_def": len(d), "receptions": len(r) * 90 / mins,
                   "box_receptions": float(r[:, 4].sum()) * 90 / mins, "def_actions": len(d) * 90 / mins}
            if len(r):
                row.update(zip(("rec_x", "rec_width", "btl", "half_space", "box"), r.mean(axis=0).tolist()))
            if len(d):
                row.update(zip(("def_x", "def_width"), d.mean(axis=0).tolist()))
            rows.append(row)
    return rows, {"match_id": mid, **{str(k): v for k, v in xg.items()}}


def extract(rebuild: bool = False) -> pd.DataFrame:
    """every match once (cached in lake/impect/starts.parquet), plus the opponent's season xG difference per match"""
    out = LAKE / "starts.parquet"
    if out.exists() and not rebuild:
        return pd.read_parquet(out)
    mids = sorted(p.stem.split("_")[1] for p in (IMPECT / "events").glob("events_*.json"))
    rows, xgs = [], []
    with ProcessPoolExecutor(max_workers=4) as pool:      # four workers: the PC stays usable
        for r, x in pool.map(_match, mids, chunksize=4):
            rows += r
            xgs.append(x)
    df = pd.DataFrame(rows)
    # opponent strength: his season xG for minus against, per match (Impect's shot xG summed over the squad)
    xg = pd.DataFrame([{"match_id": x["match_id"], "team_id": int(t), "xg_for": v, "xg_against": next(w for u, w in x.items() if u not in ("match_id", t))}
                       for x in xgs for t, v in x.items() if t != "match_id"])
    strength = (xg["xg_for"] - xg["xg_against"]).groupby(xg["team_id"]).mean()
    df["opp_strength"] = df["opp_id"].map(strength).fillna(0.0)
    LAKE.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return df


def people(ids: list[int]) -> pd.DataFrame:
    """Impect player -> our person through Reep (connect/identity.py), audited: our record's birth date and name agree
    (identity.audit) and Impect's own birth date agrees with Reep's. Writes lake/impect/people.parquet."""
    from connect import identity
    lk = identity.audit(identity.links("impect", [str(i) for i in ids]))
    imp = pd.DataFrame(json.loads(next((IMPECT / "players").glob("*.json")).read_text(encoding="utf-8")))
    imp = imp[["id", "commonname", "birthdate"]].rename(columns={"id": "player_id", "commonname": "name"})
    imp["external_id"] = imp["player_id"].astype(str)
    x = imp.merge(lk, on="external_id", how="left").merge(identity.people()[["reep_id", "date_of_birth"]], on="reep_id", how="left")
    x["impect_dob_agrees"] = pd.to_datetime(x["birthdate"], errors="coerce") == pd.to_datetime(x["date_of_birth"], errors="coerce")
    x["usable"] = x["agrees"].fillna(False).astype(bool) & x["impect_dob_agrees"] & x["matchdata_id"].notna()
    keep = ["player_id", "name", "birthdate", "reep_id", "tm_id", "matchdata_id", "confidence", "method", "agrees", "impect_dob_agrees", "usable"]
    x = x[keep]
    x.to_parquet(LAKE / "people.parquet", index=False)
    return x


def adjust(df: pd.DataFrame) -> pd.DataFrame:
    """Each measure: minus home and opponent effects (one slope per line and measure, pooled), then centred on his own
    team-line mean and scaled by his own start-to-start spread there. A start too thin for a place stays NaN there."""
    key = ["player_id", "team_id", "line"]
    for v in MEASURES:
        if v in NEEDS:
            n, lo = NEEDS[v]
            df.loc[df[n] < lo, v] = np.nan
        df[v + "_adj"] = np.nan
        for _, sub in df[df[v].notna()].groupby("line"):
            g = sub.groupby(key)
            c = sub[v] - g[v].transform("mean")
            X = np.column_stack([sub["home"] - g["home"].transform("mean"), sub["opp_strength"] - g["opp_strength"].transform("mean")])
            beta, *_ = np.linalg.lstsq(X, c.to_numpy(), rcond=None)
            df.loc[sub.index, v + "_adj"] = sub[v] - X @ beta
        grp = df.groupby(key)[v + "_adj"]
        df[v + "_c"] = df[v + "_adj"] - grp.transform("mean")
        df[v + "_sd"] = grp.transform("std")
    return df


def icc(df: pd.DataFrame, v: str, min_starts: int = 5) -> float | None:
    """the bet, read directly: the share of start-to-start variance that lies between players (one-way ICC, unequal n)"""
    key = ["player_id", "team_id", "line"]
    s = df[key + [v + "_adj"]].dropna()
    s = s[s.groupby(key)[v + "_adj"].transform("size") >= min_starts]
    g = s.groupby(key)[v + "_adj"]
    k, a = g.size(), g.ngroups
    if a < 3:
        return None
    N = int(k.sum())
    msb = float((k * (g.mean() - s[v + "_adj"].mean()) ** 2).sum()) / (a - 1)
    msw = float(((s[v + "_adj"] - g.transform("mean")) ** 2).sum()) / (N - a)
    k0 = (N - float((k ** 2).sum()) / N) / (a - 1)
    return round((msb - msw) / (msb + (k0 - 1) * msw), 3)


def neighbours(df: pd.DataFrame) -> pd.DataFrame:
    """(match, team, player) -> partner: his neighbours on either side in his line, by Impect's position side"""
    d = df.sort_values(["match_id", "team_id", "line", "side"])[["match_id", "team_id", "line", "player_id"]]
    g = d.groupby(["match_id", "team_id", "line"])
    out = [d.assign(partner_id=g["player_id"].shift(s)).dropna(subset=["partner_id"]) for s in (1, -1)]
    pairs = pd.concat(out, ignore_index=True)[["match_id", "team_id", "player_id", "partner_id"]]
    pairs["partner_id"] = pairs["partner_id"].astype(df["player_id"].dtype)
    return pairs


def _smd(a: np.ndarray, b: np.ndarray, sd: float) -> tuple[float, float]:
    """the first test's smd, guarded: a side with fewer than two starts says nothing"""
    return smd(a, b, sd) if len(a) >= 2 and len(b) >= 2 else (np.nan, np.nan)


def pair_effects(df: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    """For F and partner P (6+ starts beside, 6+ without, same team and line): per measure, F's adjusted mean beside P
    minus without, in units of F's own spread; odd and even halves (by date) for G1; empirical-Bayes shrunk."""
    key = ["player_id", "team_id", "line"]
    beside = pairs.merge(df[["match_id", "team_id", "player_id", "line"]], on=["match_id", "team_id", "player_id"])
    cnt = beside.groupby(key + ["partner_id"]).size().rename("n_with").reset_index()
    cnt = cnt[cnt.n_with >= MIN_SIDE].merge(df.groupby(key).size().rename("n_all").reset_index(), on=key)
    cnt = cnt[cnt.n_all - cnt.n_with >= MIN_SIDE]
    sub = df.set_index(key).sort_index()
    bset = beside.set_index(key + ["partner_id"])["match_id"].sort_index()
    rows = []
    for r in cnt.itertuples(index=False):
        k = (r.player_id, r.team_id, r.line)
        own = sub.loc[[k]].sort_values("date")
        w_all = own["match_id"].isin(set(bset.loc[[(*k, r.partner_id)]].to_numpy())).to_numpy()
        rec = {"player_id": r.player_id, "team_id": r.team_id, "line": r.line, "partner_id": r.partner_id,
               "n_with": int(w_all.sum()), "n_without": int((~w_all).sum()),
               "d_home": float(own["home"][w_all].mean() - own["home"][~w_all].mean()),
               "d_opp": float(own["opp_strength"][w_all].mean() - own["opp_strength"][~w_all].mean())}
        for v in MEASURES:
            ok = own[v + "_c"].notna().to_numpy()
            c, w, sd = own[v + "_c"].to_numpy()[ok], w_all[ok], own[v + "_sd"].iloc[0]
            nw, nwo = int(w.sum()), int((~w).sum())
            rec[v + "_n"], rec[v + "_sd"] = nw + nwo, sd     # his own spread: d x sd is the effect in the measure's unit
            if nw < MIN_SIDE or nwo < MIN_SIDE:
                continue
            rec[v], rec[v + "_se"] = _smd(c[w], c[~w], sd)
            if nw >= MIN_SPLIT and nwo >= MIN_SPLIT:
                odd = (np.arange(len(c)) % 2) == 0       # alternate starts by date, over the starts this measure has
                rec[v + "_odd"] = _smd(c[w & odd], c[~w & odd], sd)[0]
                rec[v + "_even"] = _smd(c[w & ~odd], c[~w & ~odd], sd)[0]
        rows.append(rec)
    out = pd.DataFrame(rows)
    for v in MEASURES:
        for col in (v, v + "_se", v + "_odd", v + "_even"):
            if col not in out:
                out[col] = np.nan
        d, se = out[v], out[v + "_se"]
        tau2 = max(0.0, float(np.nanvar(d) - np.nanmean(se ** 2))) if d.notna().sum() > 1 else 0.0
        out[v + "_shrunk"] = d * tau2 / (tau2 + se ** 2)
        out.attrs[v + "_tau"] = float(np.sqrt(tau2))
    return out


def role_patterns(df: pd.DataFrame, pairs: pd.DataFrame, roles: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """F's starts beside a partner of role A against beside role B, pooled over every F of one family and role; G2 by
    random halves of the focal players (as in gold/partners.py, measure by measure)."""
    pr = pairs.merge(roles.rename(columns={"player_id": "partner_id", "top_role": "partner_role", "family": "partner_family"}), on="partner_id")
    # one partner role per start: if his two neighbours differ, the start is left out
    one = pr.groupby(["match_id", "team_id", "player_id"])["partner_role"].agg(lambda s: s.iloc[0] if s.nunique() == 1 else None).dropna()
    x = df.merge(one.rename("partner_role").reset_index(), on=["match_id", "team_id", "player_id"]).merge(roles, on="player_id")
    rows = []
    for (pid, _, line), own in x.groupby(["player_id", "team_id", "line"]):
        vc = own["partner_role"].value_counts()
        ok = sorted(vc[vc >= MIN_ROLE_SIDE].index)
        for i in range(len(ok)):
            for j in range(i + 1, len(ok)):
                a, b = ok[i], ok[j]
                ia, ib = (own["partner_role"] == a).to_numpy(), (own["partner_role"] == b).to_numpy()
                rec = {"player_id": pid, "family": own["family"].iloc[0], "role": own["top_role"].iloc[0], "line": line,
                       "role_a": a, "role_b": b, "n_a": int(ia.sum()), "n_b": int(ib.sum())}
                for v in MEASURES:
                    c = own[v + "_c"].to_numpy()
                    ca, cb = c[ia][~np.isnan(c[ia])], c[ib][~np.isnan(c[ib])]
                    rec[v] = smd(cb, ca, own[v + "_sd"].iloc[0])[0] if len(ca) >= MIN_ROLE_SIDE and len(cb) >= MIN_ROLE_SIDE else np.nan
                rows.append(rec)
    per = pd.DataFrame(rows)
    if per.empty:
        return per, {"patterns_testable": 0, "testable": False, "pass": False}
    rng = np.random.default_rng(SEED)
    players = per["player_id"].unique()
    per["half"] = per["player_id"].map(dict(zip(players, rng.integers(0, 2, len(players)))))
    long = per.melt(id_vars=["player_id", "family", "role", "line", "role_a", "role_b", "n_a", "n_b", "half"], value_vars=MEASURES,
                    var_name="measure", value_name="d").dropna(subset=["d"])
    key = ["family", "role", "role_a", "role_b", "measure"]
    pooled = long.groupby(key)["d"].agg(n="count", mean="mean", sd="std").reset_index()
    pooled["se"] = pooled["sd"] / np.sqrt(pooled["n"])
    pooled["lo"], pooled["hi"] = pooled["mean"] - 1.96 * pooled["se"], pooled["mean"] + 1.96 * pooled["se"]
    halves = long.groupby(key + ["half"])["d"].agg(["count", "mean"]).unstack("half")
    halves.columns = [f"{a}_{b}" for a, b in halves.columns]
    halves = halves.reset_index()
    both = halves[(halves.get("count_0", 0) >= MIN_HALF) & (halves.get("count_1", 0) >= MIN_HALF)]
    g2 = {"focal_players": int(len(players)), "patterns": int(len(pooled)), "patterns_testable": int(len(both)),
          "most_players_in_a_pattern": int(pooled["n"].max()), "testable": bool(len(both) >= MIN_PATTERNS)}
    if g2["testable"]:
        g2["corr_halves"] = float(np.corrcoef(both["mean_0"], both["mean_1"])[0, 1])
        g2["same_sign"] = float((np.sign(both["mean_0"]) == np.sign(both["mean_1"])).mean())
    g2["pass"] = bool(g2.get("corr_halves", 0) >= 0.5)
    return pooled.merge(halves, on=key, how="left"), g2


def split_half(eff: pd.DataFrame, v: str) -> dict:
    """G1 for one measure: odd against even pair effects across pairs, Spearman-Brown, and a 95 % interval on it
    (Fisher z on r; pairs are counted as independent, which F->P and P->F are not, so the interval is if anything narrow)"""
    s = eff[[v + "_odd", v + "_even"]].dropna()
    rec = {"pairs": int(len(s)), "testable": bool(len(s) >= MIN_PAIRS)}
    if rec["testable"]:
        r = float(s.corr().iloc[0, 1])
        sb = (lambda x: 2 * x / (1 + x))
        z, se = np.arctanh(np.clip(r, -0.999, 0.999)), 1 / np.sqrt(len(s) - 3)
        lo, hi = np.tanh(z - 1.96 * se), np.tanh(z + 1.96 * se)
        rec.update(r=round(r, 3), spearman_brown=round(sb(r), 3) if r > -1 else None,
                   sb_interval=[round(sb(lo), 3) if lo > -1 else None, round(sb(hi), 3)])
    rec["pass"] = bool(rec["testable"] and rec["r"] > 0 and (rec["spearman_brown"] or 0) >= 0.5)
    return rec


def held(raw: pd.DataFrame, pairs: pd.DataFrame, cols: list[str]) -> dict:
    """Check (exploratory, written after the gates ran): the same G1 on his starts in his own most common value of
    `cols` only (his slot: position and side; or his team's system: the starting formation). If a pass is only the
    partner moving him to another slot or system, it fades here."""
    key = ["player_id", "team_id", "line"]
    tag = raw[cols].astype(str).agg("|".join, axis=1)
    modal = tag.groupby([raw[k] for k in key]).transform(lambda s: s.mode().iloc[0])
    sub = adjust(raw[tag == modal].copy())
    eff = pair_effects(sub, pairs)
    return {"starts_kept": round(float((tag == modal).mean()), 3),
            **{v: {k: x for k, x in split_half(eff, v).items() if k in ("pairs", "spearman_brown", "sb_interval", "pass")} for v in MEASURES}}


def main() -> None:
    raw = extract(rebuild="--rebuild" in sys.argv)
    print(f"starts {len(raw):,} | players {raw.player_id.nunique():,} | matches {raw.match_id.nunique():,}")
    ppl = people(sorted(raw["player_id"].unique().tolist()))
    print(f"Impect players {len(ppl):,} | in Reep {ppl.reep_id.notna().sum():,} | usable for roles {int(ppl.usable.sum()):,}")
    pairs = neighbours(raw)
    df = adjust(raw.copy())
    eff = pair_effects(df, pairs)
    g1 = {}
    for v in MEASURES:
        g1[v] = {"kind": "place" if v in PLACES else "total (baseline)", **split_half(eff, v),
                 "tau": round(eff.attrs.get(v + "_tau", np.nan), 3), "icc": icc(df, v)}
    # checks (exploratory, after the gates): G1 again with his slot, his team's system, or both held at their most common
    checks = {"same_slot": held(raw, pairs, ["position", "side"]), "same_system": held(raw, pairs, ["formation"]),
              "same_slot_and_system": held(raw, pairs, ["position", "side", "formation"])}
    # G2, through the audited Reep links to player_roles 2023-2024 (his row with the most minutes)
    r = pd.read_parquet(GOLD / "player_roles.parquet", columns=["fid", "season", "minutes", "family", "top_role"])
    r = r[r.season == SEASON].dropna(subset=["family", "top_role"]).sort_values("minutes").drop_duplicates("fid", keep="last")
    u = ppl[ppl.usable][["player_id", "matchdata_id"]].astype({"matchdata_id": str})
    roles = u.merge(r.astype({"fid": str}), left_on="matchdata_id", right_on="fid")[["player_id", "family", "top_role"]]
    pooled, g2 = role_patterns(df, pairs, roles)
    g2["players_with_a_role"] = int(len(roles))
    g3 = {"pairs": int(len(eff)), "mean_abs_home_diff": round(float(eff["d_home"].abs().mean()), 3),
          "mean_abs_opp_strength_diff": round(float(eff["d_opp"].abs().mean()), 3),
          "opp_strength_sd_between_matches": round(float(df["opp_strength"].std()), 3)}
    names = ppl.set_index("player_id")["name"]
    teams = {s["id"]: s["name"] for s in json.loads(next((IMPECT / "squads").glob("*.json")).read_text(encoding="utf-8"))}
    eff["name"], eff["partner"], eff["team"] = eff.player_id.map(names), eff.partner_id.map(names), eff.team_id.map(teams)
    report = {"built": pd.Timestamp.now().isoformat(timespec="seconds"), "data": "Impect open data, Bundesliga 2023/24 (research only)",
              "starts": int(len(df)), "players": int(df.player_id.nunique()), "matches": int(df.match_id.nunique()),
              "identity": {"impect_players": int(len(ppl)), "in_reep": int(ppl.reep_id.notna().sum()), "usable": int(ppl.usable.sum())},
              "neighbour_links": int(len(pairs)), "pairs": int(len(eff)),
              "G1_pair_reliability": g1, "G1_measures_passing": [v for v, x in g1.items() if x["pass"]],
              "G1_places_passing": [v for v, x in g1.items() if x["pass"] and v in PLACES],
              "G2_patterns": g2, "G3_balance": g3, "checks_exploratory": checks}
    # the largest shrunk effects of each passing measure, in its own unit (metres for depth and width), each with its 95 %
    # interval after shrinkage (posterior sd = tau x se / sqrt(tau^2 + se^2)) and its counts
    def example(r, v: str) -> dict:
        t2, se, sd = eff.attrs[v + "_tau"] ** 2, getattr(r, v + "_se"), getattr(r, v + "_sd")
        m, ps = getattr(r, v + "_shrunk"), np.sqrt(t2 * se ** 2 / (t2 + se ** 2))
        return {"player": r.name, "partner": r.partner, "team": r.team, "line": r.line, "n_with": r.n_with,
                "n_without": r.n_without, "d": round(getattr(r, v), 2), "shrunk": round(m, 2),
                "in_unit": round(m * sd, 2), "lo": round((m - 1.96 * ps) * sd, 2), "hi": round((m + 1.96 * ps) * sd, 2)}
    report["examples"] = {v: [example(r, v) for r in eff.dropna(subset=[v + "_shrunk"]).assign(a=lambda e: e[v + "_shrunk"].abs())
                              .sort_values("a", ascending=False).head(8).itertuples()]
                          for v in report["G1_measures_passing"]}
    keep = ["player_id", "name", "team_id", "team", "line", "partner_id", "partner", "n_with", "n_without", "d_home", "d_opp"]
    keep += [c for v in MEASURES for c in (v, v + "_se", v + "_shrunk", v + "_n", v + "_sd")]
    eff[keep].to_parquet(GOLD / "partner_places_effects.parquet", index=False)
    pooled.to_parquet(GOLD / "partner_places_patterns.parquet", index=False)
    (GOLD / "partners_places_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
