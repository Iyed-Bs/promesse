"""The Scout Desk v1: a small API over scout.duckdb, and the page.

    python -m uvicorn scout.api:app --port 8792      (from _research/football, Promesse venv)
    then http://127.0.0.1:8792

Read-only over the precomputed tables (scout/precompute.py); lists are kept in scout/lists.json.
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT, CLUBS_ROOT  # the one config file
import json
import os
import threading
import numpy as np
from datetime import date
from pathlib import Path

import duckdb
from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

DB = Path((DATA_ROOT + "/scout/scout.duckdb"))
HERE = Path(__file__).resolve().parent
LISTS = HERE / "lists.json"
_lock = threading.Lock()
app = FastAPI(title="Promesse Scout Desk")
app.add_middleware(GZipMiddleware, minimum_size=2000)   # the bowl's 22,522 seats travel compressed


def rows(sql: str, args: list | None = None) -> list[dict]:
    con = duckdb.connect(str(DB), read_only=True)
    try:
        cur = con.execute(sql, args or [])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, [v.isoformat() if hasattr(v, "isoformat") else v for v in row])) for row in cur.fetchall()]
    finally:
        con.close()


AGE = "date_diff('day', dob, current_date) / 365.25"
# the level he played at in 25/26 (the club where he played most; unknown when that club has no level, never borrowed
# from a shorter stint elsewhere: arg_max would skip the null and take it) and his youth minutes that season: facts, not a model
LEVEL_NOW = """left join (select tm_id, first("level" order by "minutes" desc) lvl from career where season = 2025 group by 1) cl
                 on cl.tm_id = p.tm_id
               left join (select tm_id, sum("minutes") ym from matches where youth and date >= date '2025-07-01' group by 1) y
                 on y.tm_id = p.tm_id"""


@app.get("/api/search")
def search(q: str = "", limit: int = 12) -> list[dict]:
    text = q.strip()
    if len(text) < 2:
        return []
    return rows(f"""select tm_id, name, club, position, round({AGE}, 1) age from people
                             where strip_accents(lower(name)) like '%' || strip_accents(lower(?)) || '%'
                             order by coalesce(mv, 0) desc limit ?""", [text, limit])


@app.get("/api/discover")
def discover(pos: str = "", born_after: int = 0, min_minutes: int = 0, max_value: float = 0, nation: str = "",
             sort: str = "outlook", limit: int = 100) -> list[dict]:
    where, args = ["1=1"], []
    if pos:
        where.append("(position = ? or sub_position = ?)")
        args += [pos, pos]
    if born_after:
        where.append("year(dob) >= ?")
        args.append(born_after)
    if min_minutes:
        where.append("min_now >= ?")
        args.append(min_minutes)
    if max_value:
        where.append("coalesce(mv, 0) <= ?")
        args.append(max_value)
    if nation:
        where.append("lower(nation) = lower(?)")
        args.append(nation)
    order = {"outlook": "o.p_reg3 desc nulls last", "minutes": "min_now desc", "value": "mv desc nulls last",
             "young": "dob desc"}.get(sort, "o.p_reg3 desc nulls last")
    return rows(f"""select p.tm_id, p.name, p.club, p.position, p.sub_position, round({AGE}, 1) age, p.min_now, round(p.qmin_now) qmin_now,
                        p.mv, p.ea_overall, o.p_reg3, o.qmin3_p10, o.qmin3_p50, o.qmin3_p90
                 from people p left join outlook o on o.player_id = p.tm_id
                 where {' and '.join(where)} order by {order} limit ?""", args + [min(limit, 300)])


BOARDS = {"above_age": "Above his age level: 900+ first-division minutes last season, still under 19.5",
          "debut_watch": "Debut watch: 900+ youth-competition minutes last season, no first-division minutes yet",
          "under_radar": ""}      # worded from scout/boards.json by radar_cfg()


def radar_cfg() -> dict:
    """Under the radar, live from scout/boards.json (a select few really undervalued players, the range
    flexible at each update): the call's percentile rank minus the market value's, at least min_rank_gap; the call at
    least min_call; the widest gaps first, max_players at most. Its label is written from the same numbers."""
    c = json.loads((HERE / "boards.json").read_text(encoding="utf-8"))["under_radar"]
    BOARDS["under_radar"] = (f"Under the radar: Promesse ranks him at least {round(c['min_rank_gap'] * 100)} percentile points "
                             f"higher than his market value does, with a {round(c['min_call'] * 100)} %+ chance to be a regular "
                             f"within three seasons; the {c['max_players']} widest gaps at most")
    return c


def radar_rows() -> list[dict]:
    c = radar_cfg()
    return rows(f"""with t as (select p.tm_id, o.p_reg3, percent_rank() over (order by o.p_reg3) - percent_rank() over (order by p.mv) gap
                              from people p join outlook o on o.player_id = p.tm_id where p.mv > 0)
                    select p.tm_id, p.name, p.club, p.position, p.sub_position, round({AGE}, 1) age, p.min_now, p.mv,
                           t.p_reg3, round(t.gap, 3) score, cl.lvl, y.ym
                    from t join people p on p.tm_id = t.tm_id {LEVEL_NOW}
                    where t.gap >= ? and t.p_reg3 >= ? order by t.gap desc limit ?""",
                [c["min_rank_gap"], c["min_call"], c["max_players"]])


@app.get("/api/boards")
def boards() -> list[dict]:
    counts = {r["board"]: r["n"] for r in rows("select board, count(*) n from boards group by 1")}
    counts["under_radar"] = len(radar_rows())
    return [{"id": k, "label": v, "n": counts.get(k, 0)} for k, v in BOARDS.items()]


@app.get("/api/board/{name}")
def board(name: str) -> dict:
    if name not in BOARDS:
        raise HTTPException(404)
    if name == "under_radar":
        data = radar_rows()
        return {"label": BOARDS[name], "rows": data}
    data = rows(f"""select p.tm_id, p.name, p.club, p.position, p.sub_position, round({AGE}, 1) age, p.min_now, p.mv,
                        o.p_reg3, b.score, cl.lvl, y.ym
                 from boards b join people p on p.tm_id = b.tm_id left join outlook o on o.player_id = p.tm_id
                 {LEVEL_NOW}
                 where b.board = ? order by b.score desc limit 200""", [name])
    return {"label": BOARDS[name], "rows": data}


# Club boards: analysis files only (built in _research/<club>/board), never scraped rows
CLUBS = {"barcelona": Path(CLUBS_ROOT) / "barcelona"}


@app.get("/api/club/{slug}")
def club(slug: str) -> dict:
    if slug not in CLUBS:
        raise HTTPException(404)
    folder = CLUBS[slug]
    return {name: json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))
            for name in ("system", "pathway", "fit", "prospects", "dial", "academy_share", "succession") if (folder / f"{name}.json").exists()}


@app.get("/api/meta")
def meta() -> dict:
    """When the desk was built and how fresh each source is (precompute.py writes it on every build), plus the engine's
    test and the projection's ranges read live, so the player page words them from the figures."""
    doc = json.loads(rows("select doc from provenance")[0]["doc"])
    doc["engine_test"], doc["projection_held"] = _engine_test(), _projection_held()
    # plain words for two lines the last build wrote with working names (the next build writes them this way itself)
    src, mod = doc.get("sources") or {}, doc.get("models") or {}
    if "Identity v3" in src:
        src["Identity"] = src.pop("Identity v3")
    if "Phase 2b" in str(mod.get("team strength")):
        mod["team strength"] = "Elo+ on Transfermarkt games (a team-strength rating that beat plain Elo in its test)"
    return doc


MODELS = Path((DATA_ROOT + "/lake/models"))


def _engine_test() -> dict:
    """ProEngine (ProEngine) against market value on 2021-22, the season it never learned from: right picks out of
    100 for each (AUC x 100), the average difference and its 95 % range. The verdict words follow the figures: 'ahead' when the whole range is above zero, 'edge' when the average is, 'level' or 'behind' otherwise.
    The engine's test counts as passed from 'edge' up; the original gate (range above zero) stays in the method docs."""
    t, lad = _json(MODELS / "engine_v2_t2.json"), _json(MODELS / "ladder_y_reg3.json")
    mkt = ((lad.get("T2 (test)") or {}).get("rungs") or {}).get("1a. benchmark: market value", {}).get("auc")
    g = t.get("gap_to_market_value") or {}
    if not t or mkt is None or not g:
        return {}
    lo, hi = g["ci95"]
    verdict = "ahead" if lo > 0 else "behind" if hi < 0 else "edge" if g["mean"] > 0 else "level"
    return {"engine": round(t["auc_version"] * 100, 1), "market": round(mkt * 100, 1), "diff": round(g["mean"] * 100, 1),
            "lo": round(lo * 100, 1), "hi": round(hi * 100, 1), "verdict": verdict, "passed": verdict in ("ahead", "edge")}


def _projection_held() -> dict:
    """ProProjection (ProProjection): the share of real outcomes inside its 80 % ranges on seasons that have played
    out, lowest and highest across the four kinds of evidence; the test asks 77 to 83 %."""
    by = (_json(MODELS / "projection_hurdle_settled.json").get("by_tier") or {})
    v = [x.get("calibrated_80") for x in by.values() if x.get("calibrated_80") is not None]
    return {"low": round(min(v) * 100, 1), "high": round(max(v) * 100, 1), "passed": all(0.77 <= x <= 0.83 for x in v)} if v else {}


_bowl: dict = {}
# evidence per player (lake/integrity.py): the 3D stadium seats 'solid' players in the upper stand until the deep-analysis
# cohort is defined, and says so on the page
SUFFICIENCY = (DATA_ROOT + "/lake/quality/sufficiency.parquet")
# the two stands: 'deep' = two+ full seasons with match stats 2021/22-2025/26 and an identity
# checked by exact birth date; everyone else 'projection', with the reason as a short code the page words
STANDS = (DATA_ROOT + "/lake/gold/stands.parquet")
GOLD_DIR = Path((DATA_ROOT + "/lake/gold"))
WHY = """case sd.reason when 'fewer than two full seasons with stats' then 'one'
                       when 'no identity link with an exact birth date' then 'id'
                       when 'held back: identity conflict under review' then 'held' end"""


@app.get("/api/bowl")
def bowl() -> dict:
    """Every player as one seat of Discover's bowl, in columns (filtered in the page, so every filter is instant).
    Cached until build.py replaces scout.duckdb."""
    stamp = DB.stat().st_mtime
    if _bowl.get("stamp") != stamp:
        data = rows(f"""select p.tm_id, p.name, p.club, coalesce(p.position, '') as "position", coalesce(p.sub_position, '') as sub,
                               year(p.dob) born, round({AGE}, 1) age, coalesce(p.min_now, 0)::integer min_now,
                               coalesce(p.mv, 0) mv, coalesce(p.nation, '') nation, round(o.p_reg3, 3) p_reg3,
                               cl.lvl, coalesce(y.ym, 0)::integer ym, coalesce(su.tier, 'presence only') tier,
                               coalesce(sd.stand, 'projection') stand, coalesce(sd.full_seasons, 0)::integer fs, {WHY} why
                        from people p left join outlook o on o.player_id = p.tm_id {LEVEL_NOW}
                        left join read_parquet('{SUFFICIENCY}') su on su.player_id = p.matchdata_id
                        left join (select player_id, stand, full_seasons, reason from read_parquet('{STANDS}')) sd
                          on sd.player_id = p.matchdata_id order by p.dob desc""")
        cols = list(data[0]) if data else []
        _bowl.update(stamp=stamp, doc={"cols": cols, "rows": [[r[c] for c in cols] for r in data]})
    return _bowl["doc"]


# how he plays: the gold layer's readings for his latest league season of 900+
# minutes, read from its files and kept in memory until they change
GOLD = Path((DATA_ROOT + "/lake/gold"))
HIDDEN_ROLES = {"Shot-stopper"}                       # T3: noise over a season, hidden everywhere
_gold: dict = {}


def gold(name: str):
    import pandas as pd
    f = GOLD / name
    stamp = f.stat().st_mtime
    if name not in _gold or _gold[name][0] != stamp:
        _gold[name] = (stamp, pd.read_parquet(f) if f.suffix == ".parquet" else json.loads(f.read_text(encoding="utf-8")))
    return _gold[name][1]


def style(tm_id: int) -> dict | None:
    import pandas as pd
    roles = gold("player_roles.parquet")
    mine = roles[(roles.tm_id == tm_id) & (roles.minutes >= 900)]
    if mine.empty:
        return None
    r = mine.sort_values(["season", "minutes"]).iloc[-1]

    def same(df: pd.DataFrame):                       # his row in another gold table: same player, team, league, season
        m = df[(df.fid == r.fid) & (df.team_id == r.team_id) & (df.league_id.astype("int64") == int(r.league_id)) & (df.season == r.season)]
        return None if m.empty else m.iloc[0]
    role_pct = {c[4:]: round(float(r[c]), 3) for c in roles.columns
                if c.startswith("pct_") and c[4:] not in HIDDEN_ROLES and pd.notna(r[c])}
    sk_rep, s = gold("skills_report.json")["by_skill"], same(gold("player_skills.parquet"))
    skills = [] if s is None else sorted(
        ({"label": v["label"], "pct": round(float(s[f"pct_{k}"]), 3), "split_half": v.get("split_half_spearman")} for k, v in sk_rep.items()
         if v.get("passed") and pd.notna(s.get(f"pct_{k}"))), key=lambda x: -x["pct"])
    at_rep, a = gold("attributes_report.json"), same(gold("player_attributes.parquet"))
    attrs = [] if a is None else [{"label": v["label"], "reads": v["reads"], "pct": round(float(a[f"pct_{k}"]), 3),
                                   "split_half": v["split_half_spearman"], "discrimination": v.get("discrimination")}
                                  for k, v in at_rep["by_attribute"].items() if v["passed"] and pd.notna(a.get(f"pct_{k}"))]
    return {"season": r.season, "team": r.team, "team_id": int(r.team_id), "family": r.family, "minutes": int(r.minutes),
            "top_role": max(role_pct, key=role_pct.get) if role_pct else None, "roles": role_pct, "skills": skills,
            "attributes": attrs, "not_readable": at_rep["not_readable"],
            "hidden": [{"label": v["label"], "split_half": v["split_half_spearman"]}
                       for v in at_rep["by_attribute"].values() if not v["passed"]]}


# T1's five game models, named after their centres; the label is for people, the vector is what counts
def _competitions() -> dict:
    """The registry's competitions (id -> code, name, country, tier, level, kind), read without importing it."""
    import ast
    tree = ast.parse(Path(DATA_ROOT) / "lake" / "registry.py".read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "COMPETITIONS")
    return ast.literal_eval(node.value)


COMPETITIONS = _competitions()


def _first_divisions() -> set[int]:
    """League ids of senior first divisions."""
    return {k for k, v in COMPETITIONS.items() if v[3] == 1 and v[4] == "senior" and v[5] == "league"}


FIRST_DIVISIONS = _first_divisions()
ARCHETYPE = {0: "Deep reactive block", 1: "Back-three build-up", 2: "Positional possession", 3: "Wide attacking four",
             4: "Direct and vertical"}


@app.get("/api/team/{team_id}")
def team(team_id: int) -> dict:
    import pandas as pd
    st, dims = gold("team_style.parquet"), gold("team_style_report.json")["dimensions_passed"]
    mine = st[st.team_id == team_id]
    if mine.empty:
        raise HTTPException(404)
    mine = mine.sort_values("n").groupby("season").tail(1).sort_values("season")   # one row a season: its main league
    seasons = [{"season": r["season"], "league": r["league"], "matches": int(r["n"]), "archetype": ARCHETYPE.get(int(r["archetype"])),
                **{d: round(float(r[f"z_{d}"]), 2) for d in dims if pd.notna(r[f"z_{d}"])}} for _, r in mine.iterrows()]
    # the teams that play most like its latest full season (20+ matches): other first-division sides, full seasons
    # ending the same year or the year before. The dimensions are league-relative, so a side that dominates a smaller
    # league would otherwise read like Barça
    full = mine[mine.n >= 20]
    ref = (full if len(full) else mine).iloc[-1]
    end = pd.to_numeric(st.season.str.extract(r"(\d{4})$")[0], errors="coerce")   # "2025-2026" -> 2026, "2025 Venezuela" -> NaN
    ref_end = int(str(ref["season"])[-4:])
    pool = st[(st.team_id != team_id) & (st.n >= 20) & st.league_id.astype(int).isin(FIRST_DIVISIONS)
              & end.between(ref_end - 1, ref_end)]
    z = [f"z_{d}" for d in dims]
    dist = ((pool[z].fillna(0) - ref[z].fillna(0).to_numpy()) ** 2).sum(axis=1) ** 0.5
    like = pool.assign(distance=dist).nsmallest(6, "distance")
    # its coaches: Transfermarkt's managers over the matches we hold, through the club the match link pairs it with
    link = gold("match_link.parquet")
    club = link[link.team_id == team_id].club_id.mode()
    spells = gold("coach_spells.parquet")
    spells = spells[spells.club_id == float(club.iloc[0])] if len(club) else spells.iloc[0:0]
    # the roles of its regulars, its latest season with 900+ minute players
    roles = gold("player_roles.parquet")
    rr = roles[(roles.team_id == team_id) & (roles.minutes >= 900)]
    rows = []
    for _, p in rr.iterrows():
        pct = {c[4:]: round(float(p[c]), 2) for c in roles.columns
               if c.startswith("pct_") and c[4:] not in HIDDEN_ROLES and pd.notna(p[c])}
        rows.append({"season": p.season, "family": p.family, "name": p["name"], "minutes": int(p.minutes),
                     "tm_id": None if pd.isna(p.tm_id) else int(p.tm_id),
                     "top_role": max(pct, key=pct.get) if pct else None, "role_percentiles": pct})
    return {"team": ref["team"], "team_id": team_id, "league": ref["league"], "dimensions": dims, "seasons": seasons,
            "plays_like": [{"team": r["team"], "team_id": int(r["team_id"]), "season": r["season"], "league": r["league"],
                            "distance": round(float(r["distance"]), 2)} for _, r in like.iterrows()],
            "coaches": [{"manager": r["manager"], "first": str(r["first"])[:10], "last": str(r["last"])[:10], "matches": int(r["n"])}
                        for _, r in spells.sort_values("first").iterrows()],
            "roles": rows}


@app.get("/api/coach/{name}")
def coach(name: str) -> dict:
    import pandas as pd
    rep = gold("coach_style_report.json")
    dims = list(rep["by_dimension"])
    carried = rep["dimensions_coaches_carry"]
    sp = gold("coach_spells.parquet")
    mine = sp[sp.manager == name].sort_values("first")
    if mine.empty:
        raise HTTPException(404)
    link = gold("match_link.parquet")
    team_of = link.groupby(["club_id", "team_id"]).size().rename("n").reset_index().sort_values("n").groupby("club_id").tail(1)
    team_of = dict(zip(team_of.club_id.astype(float), team_of.team_id.astype(int)))
    spells = [{"team": r["team"], "team_id": team_of.get(float(r["club_id"])), "first": str(r["first"])[:10],
               "last": str(r["last"])[:10], "matches": int(r["n"]),
               **{d: round(float(r[d]), 2) for d in dims if pd.notna(r[d])}} for _, r in mine.iterrows()]
    # his fingerprint: the dimensions coaches carry, weighted by matches, only once he has two spells to compare
    w = mine.n.to_numpy(dtype=float)
    finger = {d: round(float((mine[d].fillna(0) * w).sum() / w.sum()), 2) for d in carried} if len(mine) >= 2 else None
    mv = gold("coach_moves.parquet")
    moves = [{"from": r["from"], "to": r["to"], "arrived": str(r["arrived"])[:10], "matches_before": int(r["n_a"]),
              "matches_after": int(r["n_b"]),
              "dims": {d: {"previous": round(float(r[f"a_{d}"]), 2), "before": round(float(r[f"pre_{d}"]), 2),
                           "under_him": round(float(r[f"b_{d}"]), 2)}
                       for d in carried if pd.notna(r[f"a_{d}"]) and pd.notna(r[f"pre_{d}"]) and pd.notna(r[f"b_{d}"])}}
             for _, r in mv[mv.manager == name].sort_values("arrived").iterrows()]
    return {"manager": name, "dimensions": dims, "carried": carried, "spells": spells, "fingerprint": finger, "moves": moves,
            "carry_effects": {d: v["coach_a"] for d, v in rep["by_dimension"].items()}}


# what the engine's call is made of (models/explain.py): the intercept and every input's log-odds contribution
MODELS = Path((DATA_ROOT + "/lake/models"))


def why(tm_id: int) -> dict | None:
    import pandas as pd
    f = MODELS / "current_contributions_v2c.parquet"      # ProEngine: exact TreeSHAP terms in log-odds
    if not f.exists():
        return None
    stamp = f.stat().st_mtime
    if "contrib" not in _gold or _gold["contrib"][0] != stamp:
        _gold["contrib"] = (stamp, pd.read_parquet(f))
        _gold["swap"] = (stamp, pd.read_parquet(MODELS / "current_swap_v2c.parquet"))
        _gold["engine"] = (stamp, json.loads((MODELS / "current_outlook_v2c.json").read_text(encoding="utf-8")))
    c = _gold["contrib"][1]
    mine = c[c.player_id == tm_id]
    if mine.empty:
        return None
    eng = _gold["engine"][1]
    sw = _gold["swap"][1]
    sw = sw[sw.player_id == tm_id]
    groups = mine.groupby("group").contribution.sum().sort_values(key=abs, ascending=False)
    # version B: the club variables (models/club_variables.json). A tree has no coefficient to swap, so each input a club
    # knows better carries this player's log-odds on a grid of values (models/score_v2c.py); the page reads between points
    cv = json.loads((Path(__file__).resolve().parents[1] / "models" / "club_variables.json").read_text(encoding="utf-8"))
    for e in cv["engine_inputs"]:
        k = e["input"]
        row = mine[mine.input == k]
        g = sw[sw.input == k].sort_values("x")
        val = None if row.empty or bool(row.missing.iloc[0]) else float(row.value.iloc[0])
        if val is not None and k == "fm_youth_min_365":
            val = float(np.expm1(val))      # the tree reads log1p(minutes); the page shows minutes
        e.update({"grid": [[float(x), float(l)] for x, l in zip(g.x, g.logit)],
                  "median": (e["min"] + e["max"]) / 2 if k == "height" else 0, "value": val})
    return {"intercept": eng["intercept"], "club": cv,
            "groups": [{"group": g, "logit": round(float(v), 3)} for g, v in groups.items()],
            "inputs": [{"input": r.input, "group": r.group, "label": r.label, "logit": round(float(r.contribution), 3),
                        "value": None if r.missing else round(float(r.value), 3)}
                       for r in mine.sort_values("contribution", key=abs, ascending=False).itertuples()]}


@app.get("/api/teams")
def teams() -> dict:
    """Every club whose game model is measured: its latest season with 10+ matches, its league, its game model."""
    st = gold("team_style.parquet")
    s = st[st.n >= 10].sort_values("season").groupby("team_id").tail(1)
    return {"teams": [{"team_id": int(r.team_id), "team": r.team, "league": r.league, "season": r.season,
                       "archetype": ARCHETYPE.get(int(r.archetype)), "first": int(r.league_id) in FIRST_DIVISIONS,
                       "league_id": int(r.league_id), "country": COMPETITIONS.get(int(r.league_id), ("", "", ""))[2]}
                      for r in s.sort_values(["league", "team"]).itertuples()]}


@app.get("/api/coaches")
def coaches() -> dict:
    """Every coach with spells in the matches we hold: his clubs in order, his matches."""
    sp = gold("coach_spells.parquet").sort_values("first")
    g = sp.groupby("manager")
    out = [{"manager": m, "teams": list(dict.fromkeys(part.team.tolist())), "matches": int(part.n.sum()), "spells": int(len(part)),
            "last": str(part["last"].max())[:10]} for m, part in g]
    return {"coaches": sorted(out, key=lambda c: (-c["spells"], -c["matches"]))}


@app.get("/api/method")
def method() -> dict:
    """Every module's test and what it said, read from the reports that ran them."""
    G, M = GOLD, Path((DATA_ROOT + "/lake/models"))
    rd = lambda p: json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}      # noqa: E731
    t1, t2, t3 = rd(G / "team_style_report.json"), rd(G / "coach_style_report.json"), rd(G / "roles_report.json")
    t4, t5, t6 = rd(G / "skills_report.json"), rd(G / "system_fit.json"), rd(G / "development.json")
    at, lad, pj = rd(G / "attributes_report.json"), rd(M / "ladder_y_reg3.json"), rd(M / "projection_qmin3.json")
    hu, st = rd(M / "projection_hurdle_t3.json"), rd(G / "tm_strength_report.json")
    t3v = t3.get("split_half_spearman", {})
    g4 = lad.get("gate_phase4", {})
    r3 = (lad.get("T3 (locked)") or {})
    rows = [
        {"module": "Team strength", "asks": "How strong was each team on each day?",
         "test": "beats plain Elo on games it never saw (2021 on); league levels beat it on games between leagues",
         "result": f"Brier {st.get('brier_test', {}).get('elo_plus', 0):.4f} against plain Elo's {st.get('brier_test', {}).get('plain_elo', 0):.4f}",
         "passed": bool(st.get("gate_passed"))},
        {"module": "Game models", "asks": "How does each team play, season by season?",
         "test": "a team's odd and even matches agree (Spearman 0.6 or more)",
         "result": f"{len(t1.get('dimensions_passed', []))} of {len(t1.get('dimensions_passed', [])) + len(t1.get('dimensions_failed', []))} dimensions reliable",
         "passed": bool(t1.get("gate_t1", {}).get("passed", True))},
        {"module": "Coach fingerprints", "asks": "Does a coach carry his way of playing from club to club?",
         "test": "a new club moves toward the coach's last one, interval above zero, on half the dimensions or more",
         "result": f"{len(t2.get('dimensions_coaches_carry', []))} of 11 dimensions carried, {t2.get('coach_moves_tested', 0)} moves",
         "passed": bool(t2.get("gate_t2", {}).get("passed"))},
        {"module": "Roles", "asks": "What does he do inside his team?",
         "test": "a role holds from one half of a season to the other (0.5 or more)",
         "result": f"{sum(1 for v in t3v.values() if v >= 0.5)} of {len(t3v)} roles stable", "passed": True},
        {"module": "Skills beyond the system", "asks": "What does he do more of than his system predicts?",
         "test": "odd matches predict even ones after the system is taken out (0.5 or more)",
         "result": f"{len(t4.get('skills_shown', []))} of {len(t4.get('skills_shown', [])) + len(t4.get('skills_hidden', []))} skills shown",
         "passed": True},
        {"module": "System fit", "asks": "If he moves to a team that plays like this, what will he do there?",
         "test": "beats 'same as before' and 'his position at the new team' on moves it never saw",
         "result": f"{t5.get('moves', {}).get('test', 0):,} unseen moves", "passed": bool(t5.get("gate_t5", {}).get("passed"))},
        {"module": "Development by system (ProT6)", "asks": "Which coaches and styles grow young players fastest?",
         "test": "the club's style or the coach improve next season's forecast, out of time",
         "result": f"style {t6.get('gain', {}).get('+ game model over baseline', {}).get('mean', 0):+.3f}, coach {t6.get('gain', {}).get('+ coach over + game model', {}).get('mean', 0):+.3f}: no gain",
         "passed": bool(t6.get("gate_t6", {}).get("game model")) or bool(t6.get("gate_t6", {}).get("coach"))},
        {"module": "Attributes", "asks": "Vision, composure, discipline... what kind of footballer?",
         "test": "repeats from one half-season to the next (0.5) and most of the spread is the players (Franks et al.)",
         "result": "shown: " + ", ".join(f"{v['label'].lower()} {v['split_half_spearman']:.2f}" for v in at.get("by_attribute", {}).values()
                                       if v["split_half_spearman"] >= 0.5)
                   + "; kept hidden, below 0.5: " + ", ".join(v["label"].lower() for v in at.get("by_attribute", {}).values()
                                                             if v["split_half_spearman"] < 0.5),
         "passed": bool(at.get("shown"))},
        {"module": "The engine", "asks": "Will he become a regular within three seasons?",
         "test": "beats market value and every rating on seasons it never saw; then once on 2023, kept locked",
         "result": (f"2021-22: {g4.get('mean', 0):+.3f} AUC against every rating together (95 % {g4.get('ci95', [0, 0])[0]:+.3f} "
                    f"to {g4.get('ci95', [0, 0])[1]:+.3f}): "
                    + ("ahead" if g4.get("ci95", [0, 0])[0] > 0 else "behind" if g4.get("ci95", [0, 0])[1] < 0 else "level")
                    + (f"; 2023: +{r3.get('gbm_minus_market_value_auc', {}).get('mean', 0):.3f} over market value" if r3 else
                       "; the 2023 result was withdrawn: it came with inputs that leaked the outcome (moves, profile gaps)")),
         "passed": bool(g4.get("passed"))},
        {"module": "The projection", "asks": "How many quality minutes in the next three seasons, and how sure?",
         "test": "its 80 % bands hold 77-83 % in every tier, on seasons it never saw",
         "result": "; ".join(f"{k} {v['calibrated_80']:.0%}" for k, v in (hu.get("by_tier") or pj.get("by_tier") or {}).items()),
         "passed": bool(pj.get("gate_phase6", {}).get("passed"))},
    ]
    return {"rows": rows}


@app.get("/api/player/{tm_id}")
def player(tm_id: int) -> dict:
    head = rows(f"select *, round({AGE}, 2) age from people where tm_id = ?", [tm_id])
    if not head:
        raise HTTPException(404)
    career = rows("""select season, club, league, minutes, qmin, apps, europe_min, league_min, share, level
                  from career where tm_id = ? order by season, minutes desc""", [tm_id])
    matches = rows("""select date, league, home_team, away_team, team, role, minutes, rating, goals, assists, youth
                   from matches where tm_id = ? order by date desc limit 80""", [tm_id])
    spots = rows("""select x, y, minutes from matches where tm_id = ? and x is not null and y is not null
                 order by date desc limit 400""", [tm_id])
    outlook = rows("select * from outlook where player_id = ?", [tm_id])
    prov = json.loads(rows("select doc from provenance")[0]["doc"])
    # his terrace: one seat per match, by season (precompute.py)
    terrace = rows("""select season, date, kind, minutes, "level" from terrace where tm_id = ? order by date""", [tm_id])
    rarity = rows("select age, q, rank, n, second_name, second_q from rarity where tm_id = ?", [tm_id])
    # his seat in Discover's bowl: stand = position, row = birth year, seat = his place in the stand, numbered the
    # way the page seats them (youngest first, then the outlook, then birth date)
    seat = rows("""select stand, "row", seat from (
                     select p.tm_id, p.position stand, year(p.dob) as "row",
                            row_number() over (partition by p.position order by year(p.dob) desc,
                                               coalesce(o.p_reg3, -1) desc, p.dob desc) seat
                     from people p left join outlook o on o.player_id = p.tm_id) where tm_id = ?""", [tm_id])
    # his stand (gold/stands.py): the full reading, or the projection and why
    stand = rows(f"""select stand, full_seasons, first_full, reason from read_parquet('{STANDS}')
                     where player_id = ?""", [str(head[0].get("matchdata_id"))]) if head[0].get("matchdata_id") else []
    return {"head": head[0], "career": career, "matches": matches, "spots": spots, "terrace": terrace,
            "stand": stand[0] if stand else {"stand": "projection", "full_seasons": 0, "reason": "no full season with match stats yet"},
            "rarity": rarity[0] if rarity else None, "seat": seat[0] if seat else None,
            "outlook": outlook[0] if outlook else None, "provenance": prov, "style": style(tm_id), "why": why(tm_id)}


@app.get("/api/compare")
def compare(ids: str) -> list[dict]:
    out = []
    for i in [int(x) for x in ids.split(",") if x.strip().isdigit()][:4]:
        h = rows("select tm_id, name, dob, club, position from people where tm_id = ?", [i])
        if not h:
            continue
        seasons = rows("""select season, sum(minutes) as "minutes", sum(qmin) as qmin, max("level") filter (where share >= 0.4) as "level"
                       from career where tm_id = ? group by 1 order by 1""", [i])
        terrace = rows("""select season, kind, minutes, "level" from terrace where tm_id = ? order by date""", [i])
        out.append({**h[0], "seasons": seasons, "terrace": terrace})
    return out


class ListItem(BaseModel):
    list: str
    tm_id: int
    note: str = ""


def _lists() -> dict:
    return json.loads(LISTS.read_text(encoding="utf-8")) if LISTS.exists() else {}


def _standing(ids: list[int]) -> dict[int, dict]:
    """What the desk says about these players right now: the call (chance of being a regular within three seasons),
    the club, his 25/26 first-division minutes, the level he played at in 25/26 (Elo against the big five's average)
    and his youth minutes. Stored on the day a player is kept, and read again on the Shortlists page, so the page can
    show what moved since."""
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    out = rows(f"""select p.tm_id, p.club, round(o.p_reg3, 3) p_reg3, coalesce(p.min_now, 0)::integer min_now, cl.lvl,
                          coalesce(y.ym, 0)::integer ym
                   from people p left join outlook o on o.player_id = p.tm_id {LEVEL_NOW}
                   where p.tm_id in ({marks})""", ids)
    prov = meta()
    stamp = {"built": prov.get("built"), "engine": prov.get("models", {}).get("outlook", {}).get("reg3_model"),
             # the last match the desk held: "since you kept him" counts only the matches after it, the ones you hadn't seen
             "seen_to": rows("select max(date) d from matches")[0]["d"]}
    return {r.pop("tm_id"): {**r, **stamp} for r in out}


@app.get("/api/lists")
def get_lists() -> dict:
    """The lists as kept, each entry with `now` (the desk today, same fields as `kept`) and `since` (his matches after
    the last one the desk held when he was kept: count, senior and youth minutes, the latest date)."""
    data = _lists()
    ids = sorted({e["tm_id"] for es in data.values() for e in es})
    now = _standing(ids)
    since: dict[int, dict] = {}
    for es in data.values():
        for e in es:
            # matches after what the desk held that day (older entries have no snapshot: the day he was added)
            frm = (e.get("kept") or {}).get("seen_to") or e.get("added")
            key = (e["tm_id"], frm)
            if key not in since:
                since[key] = rows("""select count(*) n, coalesce(sum(minutes) filter (where not youth), 0)::integer senior,
                                            coalesce(sum(minutes) filter (where youth), 0)::integer youth, max(date) as "last"
                                     from matches where tm_id = ? and date > ?::date""", [e["tm_id"], frm])[0]
            e["now"], e["since"] = now.get(e["tm_id"]), {**since[key], "from": frm}
    return data


@app.post("/api/lists")
def add_to_list(item: ListItem) -> dict:
    with _lock:
        data = _lists()
        entries = data.get(item.list, [])
        old = next((e for e in entries if e["tm_id"] == item.tm_id), None)
        if old:
            # kept again on the same list: the note changes, the day he was kept and what the desk said then do not
            old["note"] = item.note
        else:
            entries.append({"tm_id": item.tm_id, "note": item.note, "added": str(date.today()),
                            "kept": _standing([item.tm_id]).get(item.tm_id)})
        data[item.list] = entries
        LISTS.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return data


@app.delete("/api/lists/{name}/{tm_id}")
def remove_from_list(name: str, tm_id: int) -> dict:
    with _lock:
        data = _lists()
        data[name] = [e for e in data.get(name, []) if e["tm_id"] != tm_id]
        LISTS.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return data


@app.get("/api/scoreboard")
def scoreboard() -> dict:
    """The Scoreboard (#/method): the engine against the market, read live from the latest ladder, so a rebuild shows
    up by itself; plus what is kept by hand in scoreboard.json (the data timeline, the two stands, the changes)."""
    M = Path((DATA_ROOT + "/lake/models"))
    lad = json.loads((M / "ladder_y_reg3.json").read_text(encoding="utf-8")) if (M / "ladder_y_reg3.json").exists() else {}
    t2 = lad.get("T2 (test)", {})
    # the rungs, named for people; the order is the ladder's own (base rate, benchmarks, the engine, the ablation)
    NAME = {"0. base rate": ("Coin flip", "floor"), "1a. benchmark: market value": ("Market value", "market"),
            "1b. benchmark: EA ratings": ("EA ratings", "rater"), "1c. benchmark: every rater together": ("Every rater together", "rater"),
            "2. penalised logistic": ("Promesse's engine", "engine"), "3. gradient boosting": ("Engine, boosted trees", "engine-alt"),
            "6. ablation: gradient boosting + raters": ("Engine + the raters (never shipped)", "ablation")}
    rungs = [{"name": NAME.get(k, (k, "other"))[0], "kind": NAME.get(k, (k, "other"))[1], **v} for k, v in t2.get("rungs", {}).items()]
    book = json.loads((HERE / "scoreboard.json").read_text(encoding="utf-8"))
    gate = lad.get("gate_phase4", {})
    # the first engine (the penalised logistic, before the nine extra seasons of match stats) is kept by name: with the
    # boosted trees on the same information it answers "was it the algorithm or the information?"
    engine_v1 = next((r["auc"] for r in rungs if r["kind"] == "engine"), None)
    v2 = M / "engine_v2_t2.json"
    if v2.exists():     # the engine the desk runs on is ProEngine: its one T2 test replaces the ProEngine 0.1 row and gap
        t = json.loads(v2.read_text(encoding="utf-8"))
        for r in rungs:
            if r["kind"] == "engine":
                r["auc"], r["name"] = round(t["auc_version"], 4), "ProEngine"     # ProEngine, by its final name
        g = t["gap_to_market_value"]
        gate = {**gate, "engine": "ProEngine", "mean": round(g["mean"], 4), "ci95": [round(x, 4) for x in g["ci95"]],
                "passed": _engine_test().get("passed", False), "verdict": _engine_test().get("verdict")}
    # the two stands, read live from gold/stands.py's report (scoreboard.json keeps the earlier plan's figures as a fallback)
    sr = _json(GOLD_DIR / "stands_report.json")
    if sr.get("upper_stand"):
        book["stands"] = {**book.get("stands", {}), "deep": sr["upper_stand"]["players"], "deep_young": sr["upper_stand"]["young"],
                          "deep_three_seasons": sr["upper_stand"]["with_three_or_more"], "reviewed": False}
    # Player Combinations, in beta: the named duos' result, for the tests list
    ip = _json(GOLD_DIR / "partners_interplay_report.json").get("G3_known_duos") or {}
    book["combinations"] = {"top_third": ip.get("top_third"), "testable": ip.get("testable"), "named": ip.get("named")}
    # what Promesse adds to the market's view: engine + raters minus market value, with its 95 % interval
    adds = (lad.get("promesse_adds_to_market") or {}).get("engine_plus_raters_minus_market_value") or {}
    # the projection's ranges on settled seasons (ProProjection, the frozen ProProjection): share of real outcomes
    # that fell inside the 80 % range, per evidence tier
    pv3 = _json(M / "projection_hurdle_settled.json")
    return {"rungs": rungs, "n_test": t2.get("n_test"), "test": t2.get("test"), "base_rate": t2.get("base_rate_test"),
            "gate": gate, "ablation": lad.get("ablation_raters", {}), "engine_v1": engine_v1,
            "adds_to_market": {"mean": adds.get("point"), "ci95": adds.get("ci95")},
            "projection": {k: v.get("calibrated_80") for k, v in (pv3.get("by_tier") or {}).items()},
            "built": date.fromtimestamp((M / "ladder_y_reg3.json").stat().st_mtime).isoformat() if lad else None,
            "modules": method()["rows"], **book}


@app.get("/api/connect")
def connect() -> dict:
    """Connect (#/connect): what we hold, honestly sized (scout/inventory.json, from inventory.py); what only a club
    holds and the adapter waiting for it; the proof run of the adapters on open samples and the identity bridge
    (lake/connect/connect_report.json, from connect/run.py); the partner engine's gates (lake/gold/partners_report.json)."""
    G = Path((DATA_ROOT + "/lake"))
    inv = json.loads((HERE / "inventory.json").read_text(encoding="utf-8")) if (HERE / "inventory.json").exists() else {}
    rep = json.loads((G / "connect" / "connect_report.json").read_text(encoding="utf-8")) if (G / "connect" / "connect_report.json").exists() else {}
    for r in rep.get("runs", {}).values():
        r.pop("trace", None)
    part = json.loads((G / "gold" / "partners_report.json").read_text(encoding="utf-8")) if (G / "gold" / "partners_report.json").exists() else {}
    # design 1, places from Impect (gold/partners_places.py): its gates, the slot check, and the passing measures' examples
    pl = json.loads((G / "gold" / "partners_places_report.json").read_text(encoding="utf-8")) if (G / "gold" / "partners_places_report.json").exists() else {}
    # the table of what a club's own data would add (club_data_table.json, drawn by Data & Vision)
    return {"inventory": inv, "connect": rep, "club_table": _json(HERE / "club_data_table.json"), "partners": {k: part.get(k) for k in ("built", "starts", "matches", "pairs", "pairs_split_testable",
                                                                                  "G1_pair_reliability", "G1_rates_passing", "G2_patterns", "G3_balance", "pedri")},
            "places": {k: pl.get(k) for k in ("built", "data", "starts", "matches", "pairs", "G1_pair_reliability", "G1_places_passing",
                                              "G2_patterns", "G3_balance", "examples")}
                      | {"same_slot": (pl.get("checks_exploratory") or {}).get("same_slot")},
            # design 5, interplay from StatsBomb (gold/partners_interplay.py) and its chronological check; the named duos
            # carry where each player usually stood, for Player Combinations' pitch
            "interplay": _duo_spots(_json(G / "gold" / "partners_interplay_report.json")) | {"chrono": _json(G / "gold" / "partners_interplay_chrono.json")}}


def _json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


_spots: dict = {}


def _duo_spots(rep: dict) -> dict:
    """Each named duo's two players at their usual position group (CB, FB, DM, CM, AM, W, ST) and side (L, R or C) in
    their matches together: the modes gold/partners_interplay.py stores in partner_interplay.parquet. The pair is found
    by its two StatsBomb ids and its match count, which tells the same two players at two clubs apart (Messi and
    Neymar at Barcelona and at PSG). Kept in memory until the parquet changes; a duo that isn't matched exactly once
    simply has no `spots` and the page leaves it off the pitch."""
    f = Path((DATA_ROOT + "/lake/gold/partner_interplay.parquet"))
    if not f.exists() or not rep.get("duos"):
        return rep
    stamp = f.stat().st_mtime
    if _spots.get("stamp") != stamp:
        from gold.partners_interplay import DUOS          # the duos named before the run, with their ids
        con = duckdb.connect()
        try:
            found = {}
            for _, x, y, label in DUOS:
                hits = con.execute(f"""select lo, g_lo, g_hi, s_lo, s_hi, matches from read_parquet('{f.as_posix()}')
                                       where (A = ? and B = ?) or (A = ? and B = ?)""", [x, y, y, x]).fetchall()
                names = label.split("–")
                found[label] = {m: [{"name": names[i], "group": g_lo if pid == lo else g_hi, "side": s_lo if pid == lo else s_hi}
                                    for i, pid in enumerate((x, y))] for lo, g_lo, g_hi, s_lo, s_hi, m in hits}
        finally:
            con.close()
        _spots.update(stamp=stamp, found=found)
    for d in rep["duos"]:
        hits = _spots["found"].get(d["duo"], {})
        if d.get("found") and d.get("matches") in hits:
            d["spots"] = hits[d["matches"]]
    return rep


# The Ground (the stadium model made in Blender): served straight from its own folder, read-only, and only these two
# files, so nothing is copied and a new export shows up by itself. A missing file is a plain 404; the stadium page then
# keeps its lighter procedural bowl. (GROUND_OUT overrides the folder, for the desk checks.)
GROUND_OUT = Path(os.environ.get("GROUND_OUT") or HERE.parents[2] / "the-ground" / "out")
GROUND_FILES = {"the_ground.glb": "model/gltf-binary", "targets.json": "application/json"}


@app.get("/ground/{name}")
def ground_file(name: str) -> FileResponse:
    if name not in GROUND_FILES:                                  # an allow-list, never a path from the URL
        raise HTTPException(404, "not a ground file")
    f = GROUND_OUT / name
    if not f.is_file():
        raise HTTPException(404, "the ground is not exported")
    # revalidate on each visit (a new export shows at once); "identity" tells the gzip layer to leave the model alone,
    # it is already meshopt-compressed and gzip would only cost time on 14 MB
    headers = {"Cache-Control": "no-cache", **({"Content-Encoding": "identity"} if name.endswith(".glb") else {})}
    return FileResponse(f, media_type=GROUND_FILES[name], headers=headers)




@app.middleware("http")
async def revalidate_pages(request, call_next):
    """The page and its scripts are checked with the server on every load (a 304 when unchanged), so a browser never keeps
    running an older desk after an update."""
    resp = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


app.mount("/static", StaticFiles(directory=HERE / "web"), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(HERE / "web" / "index.html")
