"""What Promesse holds, honestly sized: every source counted from the files themselves, with its seasons, its state and
the terms it came under; then what only a club holds. Read by the desk's Connect page (/api/connect).

    python scout/inventory.py      (Promesse venv) -> scout/inventory.json
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
from datetime import date
from pathlib import Path

import duckdb

DATA = Path(DATA_ROOT)
LAKE = DATA / "lake"
OPEN = DATA / "open"
HERE = Path(__file__).resolve().parent
con = duckdb.connect()


def q(sql: str):
    try:
        return con.sql(sql).fetchone()
    except Exception as e:  # a source we can't count is shown as such, never guessed
        return (f"not counted ({type(e).__name__})",) * 8


def p(path: Path) -> str:
    return path.as_posix()


PM = p(LAKE / "matchdata" / "player_matches") + "/**/*.parquet"
pm = q(f"SELECT count(*), count(DISTINCT match_id), count(DISTINCT player_id) FROM read_parquet('{PM}', hive_partitioning=true, union_by_name=true)")
shots = q(f"SELECT count(*), count(DISTINCT match_id) FROM '{p(LAKE / 'matchdata' / 'shots.parquet')}'")
inj = q(f"SELECT count(*), count(DISTINCT player_id) FROM '{p(LAKE / 'matchdata' / 'injury_spells.parquet')}'")
sb = q(f"SELECT count(*) FROM '{p(LAKE / 'statsbomb' / 'matches.parquet')}'")
ea = q(f"SELECT count(*), count(DISTINCT ea_id) FROM '{p(LAKE / 'gold' / 'ea_ratings.parquet')}'")
persons = q(f"SELECT count(*), count(tm_id), count(matchdata_id), count(ea_id), count(konami_id), count(wyscout_id), count(statsbomb_id) FROM '{p(LAKE / 'identity' / 'persons.parquet')}'")
backfill = sum(1 for _ in (DATA / "raw" / "matchdata_matches_backfill").rglob("*/*/*.json.gz")) if (DATA / "raw" / "matchdata_matches_backfill").exists() else 0
impect_n = len(list((OPEN / "impect" / "data" / "events").glob("events_*.json")))
sc_n = sum(1 for x in (OPEN / "skillcorner-opendata" / "data" / "matches").iterdir() if x.is_dir())
dfl_n = len(list((OPEN / "dfl-idsse").glob("DFL_03_02_events_raw_*.xml")))
reep = json.loads((OPEN / "reep" / "data" / "meta.json").read_text(encoding="utf-8"))
tm = q(f"SELECT (SELECT count(*) FROM tm.players), (SELECT count(*) FROM tm.appearances), (SELECT count(*) FROM tm.player_valuations) FROM (SELECT 1)") if not con.sql(f"ATTACH '{p(DATA / 'transfermarkt-datasets.duckdb')}' AS tm (READ_ONLY)") else None

n = lambda x: f"{x:,}" if isinstance(x, int) else str(x)   # noqa: E731
HAVE = [
    {"source": "MatchData match details", "what": "lineups with each starter's slot, 60+ stats per player per match", "size": f"{n(pm[1])} matches · {n(pm[0])} player-matches · {n(pm[2])} players",
     "seasons": "2021/22 to 2026/27 (in season)", "state": "in", "kind": "matches", "licence": "scraped, private research", "feeds": ["engine", "roles", "partners", "system fit", "stands"]},
    {"source": "MatchData, older seasons", "what": "the same, from 2013/14 (lineups) and 2016/17 (player stats)", "size": f"{n(backfill)} match files so far",
     "seasons": "2013/14 to 2020/21", "state": "collecting", "kind": "matches", "licence": "scraped, private research", "feeds": ["engine (after its audit)"]},
    {"source": "MatchData shot maps", "what": "every shot: place, xG, xGOT, body part, situation", "size": f"{n(shots[0])} shots · {n(shots[1])} matches",
     "seasons": "2021/22 on", "state": "in", "kind": "events", "licence": "scraped, private research", "feeds": ["roles", "team style"]},
    {"source": "MatchData injuries", "what": "spells out, from profiles", "size": f"{n(inj[0])} spells · {n(inj[1])} players", "seasons": "2021 on",
     "state": "in", "kind": "availability", "licence": "scraped, private research", "feeds": ["availability (benchmark only)"]},
    {"source": "Transfermarkt datasets", "what": "careers, appearances, transfers, market values", "size": (f"{n(tm[0])} players · {n(tm[1])} appearances · {n(tm[2])} valuations" if tm else "counted in the lake"),
     "seasons": "2012/13 to 2025/26, snapshot of 2026", "state": "in", "kind": "careers", "licence": "CC0 dataset (dcaribou), private use", "feeds": ["targets", "careers", "moves"]},
    {"source": "EA FIFA / FC ratings", "what": "ratings and potential, a benchmark never an input", "size": f"{n(ea[0])} rows · {n(ea[1])} players", "seasons": "FIFA 15 to FC 27",
     "state": "in", "kind": "benchmark", "licence": "scraped, private research", "feeds": ["benchmarks"]},
    {"source": "StatsBomb open data", "what": "events with locations, 360 freeze frames", "size": f"{n(sb[0])} matches", "seasons": "selected competitions, to Women's Euro 2025",
     "state": "in", "kind": "events", "licence": "StatsBomb open data terms (credit)", "feeds": ["method checks"]},
    {"source": "Impect open data", "what": "events with locations, packing KPIs, lineups", "size": f"{n(impect_n)} matches", "seasons": "Bundesliga 2023/24",
     "state": "in", "kind": "events", "licence": "Impect: research only, credit, no redistribution", "feeds": ["partners v2 (next)", "connect proof"]},
    {"source": "SkillCorner open data", "what": "broadcast tracking, off-ball runs, physical aggregates", "size": f"{n(sc_n)} matches", "seasons": "A-League 2024/25",
     "state": "in", "kind": "tracking", "licence": "MIT", "feeds": ["connect proof", "tracking method"]},
    {"source": "DFL / Sportec (IDSSE)", "what": "official events and positional data", "size": f"{n(dfl_n)} matches", "seasons": "Bundesliga, 2. Bundesliga",
     "state": "in", "kind": "tracking", "licence": "CC BY 4.0", "feeds": ["connect proof"]},
    {"source": "World Cup 2022 tracking", "what": "broadcast tracking, rosters and metadata (PFF FC, now Gradient Sports; a partial mirror)", "size": "48 of 64 matches tracked · events for 13",
     "seasons": "2022", "state": "in", "kind": "tracking", "licence": "mirror with no licence stated: private research only", "feeds": ["tracking method"]},
    {"source": "Metrica sample", "what": "synchronised events and tracking (anonymised)", "size": "3 matches", "seasons": "sample",
     "state": "in", "kind": "tracking", "licence": "Metrica sample terms", "feeds": ["connect proof"]},
    {"source": "SoccerMon", "what": "GPS and wellness of a women's top-flight squad", "size": "two seasons, Toppserien", "seasons": "2020, 2021",
     "state": "in", "kind": "physical", "licence": "CC BY 4.0", "feeds": ["load method (no overlap with our players)"]},
    {"source": "FIFA Training Centre youth reports", "what": "U-17 World Cup 2025: distance in five speed zones, sprints, offers to receive, line breaks", "size": "104 matches found",
     "seasons": "2025", "state": "found", "kind": "physical", "licence": "all rights reserved: private research only", "feeds": ["youth physical (next)"]},
    {"source": "Reep register", "what": "one id per person, with their id at 30+ providers", "size": f"{n(reep['counts']['people'])} people", "seasons": f"v0 {reep['data_version']}",
     "state": "in", "kind": "identity", "licence": "CC0", "feeds": ["identity", "connect"]},
]
# what only a club holds; what each would sharpen (the wording)
CLUB_ONLY = [
    {"source": "Full event feed", "who": "Hudl StatsBomb, Opta, Wyscout, Impect", "adds": "every action with its place: carries past the press, receptions between the lines, pressure on the ball",
     "sharpens": ["roles", "partners", "archetypes v2"], "adapter": "kloppy (written, proven on Impect and DFL samples)"},
    {"source": "Tracking", "who": "league provider, SkillCorner, Second Spectrum, TRACAB", "adds": "off-ball runs, spacing between partners, pressing distances, in-match rotations",
     "sharpens": ["partners", "archetypes v2", "system fit"], "adapter": "kloppy (written, proven on SkillCorner, Metrica, DFL)"},
    {"source": "GPS and physical", "who": "the club's vests", "adds": "load, high-speed running, sprints, what a body can repeat",
     "sharpens": ["availability", "projections"], "adapter": "CSV mapping (written; a club fills its columns once)"},
    {"source": "Medical status", "who": "the club's medical system", "adds": "when a player was really available (status only, never a diagnosis)",
     "sharpens": ["projections", "the engine's target"], "adapter": "CSV (written; refuses diagnoses)"},
    {"source": "Scouting reports", "who": "the club's scouts", "adds": "what a scout saw that no feed holds: character, decisions, the eye test",
     "sharpens": ["the call, beside the numbers"], "adapter": "CSV (written)"},
    {"source": "Academy data", "who": "the club's academy", "adds": "U15 to U19 minutes, growth and maturation, the matches no provider covers",
     "sharpens": ["the lower stand: youth projections"], "adapter": "events or CSV, same contract"},
]
out = {"built": date.today().isoformat(), "have": HAVE, "club_only": CLUB_ONLY,
       "identity": {"persons": persons[0], "with_tm": persons[1], "with_matchdata": persons[2], "with_ea": persons[3], "with_konami": persons[4]}}
(HERE / "inventory.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
print(json.dumps(out["have"][:2], ensure_ascii=False)[:600]); print(out["identity"])
