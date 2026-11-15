"""Phase 0 of Promesse: the registries every feature is built on, and the two clocks of every source.

    python registry.py          build lake/registry/*.parquet and report.md, print the gate

- competitions: one canonical competition per real one (country, tier, age band, kind). Every MatchData league id is
  mapped by hand below, and every name variant MatchData uses (playoffs, split groups, group stages, Regionalliga
  divisions) is parsed into competition + stage + division.
- seasons: each (competition, season) with its first and last match date.
- teams: every team id seen in the facts, with its level (first team / reserve / U23 / U21 / U19 / U18 / U17,
  national youth) and, for reserves and youth sides, the first team they belong to (Ajax, Jong Ajax and Ajax U19 are
  three teams of one club).
- clocks: for each source, the column that says when a fact happened and the rule that says when it became known.
  Features are joined on the known clock.

Gate: every MatchData league id mapped, no orphan team. A new league id from a new crawl
fails the gate until it is added to COMPETITIONS, so nothing enters the features unregistered.
Coaches have no source in the lake yet; that registry waits for one.
"""
from __future__ import annotations

import datetime as dt
import json
import re

import duckdb
import pandas as pd

from common import DATA, LAKE

OUT = LAKE / "registry"
PM = f"read_parquet('{(LAKE / 'matchdata' / 'player_matches').as_posix()}/**/*.parquet', hive_partitioning=true, union_by_name=true)"
YPM = f"'{(DATA / 'matchdata_youth_match_players.parquet').as_posix()}'"
YCAR = f"'{(DATA / 'matchdata_youth_careers.parquet').as_posix()}'"
ELO = f"'{(LAKE / 'strength' / 'elo_matches.parquet').as_posix()}'"

# league_id: (comp_key, name, country, tier, age band, kind). Tier = level in the national pyramid (None for youth and
# international competitions, which the strength model places from results instead).
COMPETITIONS = {
    47: ("ENG-1", "Premier League", "ENG", 1, "senior", "league"),
    48: ("ENG-2", "Championship", "ENG", 2, "senior", "league"),
    87: ("ESP-1", "LaLiga", "ESP", 1, "senior", "league"),
    140: ("ESP-2", "LaLiga2", "ESP", 2, "senior", "league"),
    55: ("ITA-1", "Serie A", "ITA", 1, "senior", "league"),
    86: ("ITA-2", "Serie B", "ITA", 2, "senior", "league"),
    53: ("FRA-1", "Ligue 1", "FRA", 1, "senior", "league"),
    110: ("FRA-2", "Ligue 2", "FRA", 2, "senior", "league"),
    54: ("GER-1", "Bundesliga", "GER", 1, "senior", "league"),
    146: ("GER-2", "2. Bundesliga", "GER", 2, "senior", "league"),
    512: ("GER-4", "Regionalliga", "GER", 4, "senior", "league"),        # five regional divisions under one id
    57: ("NED-1", "Eredivisie", "NED", 1, "senior", "league"),
    40: ("BEL-1", "Belgian Pro League", "BEL", 1, "senior", "league"),  # MatchData also calls it First Division A
    61: ("POR-1", "Liga Portugal", "POR", 1, "senior", "league"),
    59: ("NOR-1", "Eliteserien", "NOR", 1, "senior", "league"),
    67: ("SWE-1", "Allsvenskan", "SWE", 1, "senior", "league"),
    46: ("DEN-1", "Superligaen", "DEN", 1, "senior", "league"),
    64: ("SCO-1", "Premiership", "SCO", 1, "senior", "league"),
    69: ("SUI-1", "Super League", "SUI", 1, "senior", "league"),
    38: ("AUT-1", "Bundesliga", "AUT", 1, "senior", "league"),
    9084: ("ENG-PL2", "Premier League 2", "ENG", None, "U21", "youth league"),   # U23 until 2021-22, U21 since
    10068: ("ENG-U18", "Premier League U18", "ENG", None, "U18", "youth league"),
    9741: ("UEFA-UYL", "UEFA Youth League", "EUR", None, "U19", "youth club continental"),
    11022: ("CONMEBOL-LIB-U20", "Copa Libertadores U20", "SAM", None, "U20", "youth club continental"),
    288: ("UEFA-U21", "UEFA European Under-21 Championship", "EUR", None, "U21", "national youth"),
    287: ("UEFA-U19", "UEFA European Under-19 Championship", "EUR", None, "U19", "national youth"),
    301: ("UEFA-U17", "UEFA European Under-17 Championship", "EUR", None, "U17", "national youth"),
    296: ("FIFA-U20", "FIFA U-20 World Cup", "WORLD", None, "U20", "national youth"),
    306: ("FIFA-U17", "FIFA U-17 World Cup", "WORLD", None, "U17", "national youth"),
    9848: ("CONMEBOL-U20", "CONMEBOL U-20 Championship", "SAM", None, "U20", "national youth"),
    # second and third tiers (B teams play in several of them)
    111: ("NED-2", "Eerste Divisie", "NED", 2, "senior", "league"),
    9195: ("NED-3", "Tweede Divisie", "NED", 3, "senior", "league"),
    208: ("GER-3", "3. Liga", "GER", 3, "senior", "league"),
    8970: ("FRA-3", "Ligue 3", "FRA", 3, "senior", "league"),
    185: ("POR-2", "Liga Portugal 2", "POR", 2, "senior", "league"),
    9112: ("POR-3", "Liga 3", "POR", 3, "senior", "league"),
    168: ("SWE-2", "Superettan", "SWE", 2, "senior", "league"),
    203: ("NOR-2", "OBOS-ligaen", "NOR", 2, "senior", "league"),
    85: ("DEN-2", "1. Division", "DEN", 2, "senior", "league"),
    147: ("ITA-3", "Serie C", "ITA", 3, "senior", "league"),
    8968: ("ESP-3", "Primera Federación", "ESP", 3, "senior", "league"),
    9138: ("ESP-4", "Segunda Federación", "ESP", 4, "senior", "league"),
    # national cups: results link the lower tiers to the top flights
    132: ("ENG-FAC", "FA Cup", "ENG", None, "senior", "cup"),
    133: ("ENG-LC", "EFL Cup", "ENG", None, "senior", "cup"),
    134: ("FRA-CDF", "Coupe de France", "FRA", None, "senior", "cup"),
    137: ("SCO-SC", "Scottish Cup", "SCO", None, "senior", "cup"),
    138: ("ESP-CDR", "Copa del Rey", "ESP", None, "senior", "cup"),
    141: ("ITA-CI", "Coppa Italia", "ITA", None, "senior", "cup"),
    171: ("SWE-SC", "Svenska Cupen", "SWE", None, "senior", "cup"),
    186: ("POR-TP", "Taça de Portugal", "POR", None, "senior", "cup"),
    209: ("GER-DFB", "DFB Pokal", "GER", None, "senior", "cup"),
    242: ("DEN-DBU", "DBU Pokalen", "DEN", None, "senior", "cup"),
    # European club competitions and their qualifying rounds
    42: ("UEFA-UCL", "UEFA Champions League", "EUR", None, "senior", "club continental"),
    73: ("UEFA-UEL", "UEFA Europa League", "EUR", None, "senior", "club continental"),
    10216: ("UEFA-UECL", "UEFA Conference League", "EUR", None, "senior", "club continental"),
    10611: ("UEFA-UCL-Q", "UEFA Champions League qualification", "EUR", None, "senior", "club continental"),
    10613: ("UEFA-UEL-Q", "UEFA Europa League qualification", "EUR", None, "senior", "club continental"),
    10615: ("UEFA-UECL-Q", "UEFA Conference League qualification", "EUR", None, "senior", "club continental"),
    # youth and reserve competitions
    10448: ("POR-U23", "Liga Revelação", "POR", None, "U23", "youth league"),
    10437: ("UEFA-U21-Q", "UEFA European Under-21 Championship qualification", "EUR", None, "U21", "national youth"),
    344: ("U21-FRIENDLIES", "U21 international friendlies", "WORLD", None, "U21", "national youth"),
    9841: ("AFC-U20", "AFC U20 Asian Cup", "ASIA", None, "U20", "national youth"),
    9571: ("AFC-U23", "AFC U23 Asian Cup", "ASIA", None, "U23", "national youth"),
    9656: ("CONCACAF-U20", "CONCACAF U-20 Championship", "NCA", None, "U20", "national youth"),
    10621: ("CONCACAF-U20-Q", "CONCACAF U-20 Championship qualification", "NCA", None, "U20", "national youth"),
    11032: ("FIFA-U20-ICC", "FIFA U-20 Intercontinental Cup", "WORLD", None, "U20", "youth club continental"),
}

DIVISIONS = {"Northeast": "Nordost", "North": "Nord", "West": "West", "Southwest": "Südwest", "Bayern": "Bayern"}

# How each source's two clocks are read. happened = when the fact took place; known = when a scout could have known
# it. Where the true publication time is unknown the rule is conservative (later, never earlier).
CLOCKS = [
    ("matchdata player-match", PM, "date", "match date + 1 day (stats published after the match)"),
    ("matchdata youth player-match", YPM, "date", "match date + 1 day"),
    ("matchdata youth careers", YCAR, "start", "spell known from its start; its totals (apps, goals) only at its end, or the crawl date while active"),
    ("results (Elo input)", ELO, "date", "match date (the result is public at full time)"),
    ("matchdata shots", f"'{(LAKE / 'matchdata' / 'shots.parquet').as_posix()}'", "date", "match date + 1 day"),
    ("matchdata timed events", f"'{(LAKE / 'matchdata' / 'match_events.parquet').as_posix()}'", "date",
     "match date (goals, substitutions and cards are public at full time)"),
    ("an open encyclopedia as-of", f"'{(LAKE / 'text' / 'encyclopedia_asof.parquet').as_posix()}' WHERE exists", "timestamp", "revision timestamp (the text as it stood then); rows where no article existed yet carry no clock"),
    ("analysis corpus", f"'{(LAKE / 'quality' / 'corpus_knowledge_time.parquet').as_posix()}'", None, "published date, else sitemap last-modified (integrity gate)"),
    ("FIFA ratings history", f"'{(DATA / 'fifa_all_updates.parquet').as_posix()}'", "fifa_update_date", "the update's release date"),
    ("EA FC 26 / 27 ratings", None, None, "the date we pulled the file: used for current snapshots only, never for the time machines"),
    ("privately collected game ratings 26", None, None, "the date we pulled the file: current snapshots only"),
    ("ClubElo snapshots", None, None, "the snapshot date in the file name"),
    ("StatsBomb open data", None, "match_date", "match date + 1 day (clubs had the commercial feed then; the open release came years later)"),
    ("SoccerMon", None, "date", "same day (team-internal load and wellness)"),
    ("DFL tracking", None, None, "match date (team-internal)"),
]

_STRIP = re.compile(r"\b(fc|cf|sc|ac|afc|sv|vfb|vfl|tsg|fk|sk|bk|if|ff|ssc|as|us|rc|cd|ud|sd|rcd|1\.)\b", re.I)


def norm_id(col: str) -> str:
    return f"regexp_replace(CAST({col} AS VARCHAR), '\\.0$', '')"


def stage_of(raw: str) -> tuple[str, str, str | None]:
    """A MatchData competition label -> (clean name, stage, division)."""
    name = re.sub(r"[�\xa0]", " ", raw).strip()
    division = next((de for en, de in DIVISIONS.items() if re.search(rf"\bRegionalliga {en}\b", name)), None)
    if re.search(r"Qualif", name, re.I):
        stage = "qualification"
    elif re.search(r"Grp\. ?([A-Z])", name):
        stage = "group " + re.search(r"Grp\. ?([A-Z])", name).group(1)
    elif re.search(r"semi", name, re.I):
        stage = "semi-final"
    elif re.search(r"quarter", name, re.I):
        stage = "quarter-final"
    elif re.search(r"Final Stage", name):
        stage = "knockout"
    elif re.search(r"\bFinal\b", name):
        stage = "final"
    elif re.search(r"Championship (Group|Playoff)", name):
        stage = "championship group"
    elif re.search(r"Relegation (Group|Playoff)", name):
        stage = "relegation group" if "Group" in name else "relegation playoff"
    elif re.search(r"ECL ?Playoff", name):
        stage = "conference league playoff"
    elif re.search(r"Promotion Playoff|World Cup U20 Playoff", name):
        stage = "promotion playoff" if "Promotion" in name else "qualification playoff"
    elif re.search(r"Playoff", name):
        stage = "playoff"
    else:
        stage = "regular season"
    return name, stage, division


def level_from_name(team: str) -> str | None:
    t = str(team)
    m = re.search(r"\bU-?(\d{2})\b|\bSub-?(\d{2})\b|\bUnder[- ]?(\d{2})\b", t, re.I)
    if m:
        return "U" + next(g for g in m.groups() if g)
    if re.search(r"^Jong\b|\b(II|B|2)$|\bReserves?\b|\bRes\.$", t):
        return "reserve"
    if re.search(r"\b(Youth|Juvenil|Primavera|Academy|Jugend)\b", t, re.I):
        return "U19"
    return None


def base_name(team: str) -> str:
    t = re.sub(r"^Jong\s+", "", str(team))
    t = re.sub(r"\s+(U-?\d{2}|Sub-?\d{2}|Under[- ]?\d{2}|II|B|2|Reserves?|Res\.|Youth|Juvenil|Primavera|Academy)$", "", t, flags=re.I)
    return re.sub(r"\s+", " ", _STRIP.sub(" ", t.lower())).strip()


def build(c: duckdb.DuckDBPyConnection) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    gate: dict = {"built": dt.datetime.now().isoformat(timespec="seconds")}

    # competitions and their name variants
    labels = c.execute(f"""
        SELECT CAST(league_id AS BIGINT) AS league_id, league AS label, count(*) AS n FROM {PM} GROUP BY 1, 2
        UNION ALL SELECT CAST(league_id AS BIGINT), league, count(*) FROM {YPM} GROUP BY 1, 2
        UNION ALL SELECT TRY_CAST(league_id AS BIGINT), competition, count(*) FROM {ELO} GROUP BY 1, 2""").fetchdf()
    labels = labels.groupby(["league_id", "label"], as_index=False).n.sum()
    unmapped = sorted(set(labels.league_id.dropna().astype(int)) - set(COMPETITIONS))
    comps = pd.DataFrame([dict(league_id=k, comp_key=v[0], name=v[1], country=v[2], tier=v[3], age_band=v[4], kind=v[5])
                          for k, v in COMPETITIONS.items()])
    parsed = labels.label.map(stage_of)
    labels["name_clean"], labels["stage"], labels["division"] = zip(*parsed)
    labels = labels.merge(comps[["league_id", "comp_key"]], on="league_id", how="left")
    comps.to_parquet(OUT / "competitions.parquet", index=False)
    labels.to_parquet(OUT / "competition_names.parquet", index=False)
    gate["league ids seen"] = int(labels.league_id.nunique())
    gate["league ids unmapped"] = unmapped
    gate["name variants"] = int(len(labels))

    # seasons: first and last match of each (competition, season)
    seasons = c.execute(f"""
        SELECT CAST(league_id AS BIGINT) AS league_id, season, min(TRY_CAST(substr(date, 1, 10) AS DATE)) AS first_match,
               max(TRY_CAST(substr(date, 1, 10) AS DATE)) AS last_match, count(DISTINCT match_id) AS matches
        FROM (SELECT league_id, season, date, match_id FROM {PM} UNION ALL SELECT league_id, season, date, match_id FROM {YPM})
        GROUP BY 1, 2""").fetchdf().merge(comps[["league_id", "comp_key"]], on="league_id", how="left")
    seasons["season_key"] = seasons.season.astype(str).str.replace(r"^(\d{4})/(\d{2})(\d{2})$", r"\1-\3", regex=True)
    seasons.to_parquet(OUT / "seasons.parquet", index=False)
    gate["competition seasons"] = int(len(seasons))

    # teams: every id in the facts, the competitions it plays in, its level
    plays = c.execute(f"""
        WITH t AS (
            SELECT {norm_id('team_id')} AS team_id, team, CAST(league_id AS BIGINT) AS league_id, count(DISTINCT match_id) AS n FROM {PM} GROUP BY 1, 2, 3
            UNION ALL SELECT {norm_id('team_id')}, team, CAST(league_id AS BIGINT), count(DISTINCT match_id) FROM {YPM} GROUP BY 1, 2, 3
            UNION ALL SELECT {norm_id('home_id')}, home, TRY_CAST(league_id AS BIGINT), count(*) FROM {ELO} GROUP BY 1, 2, 3
            UNION ALL SELECT {norm_id('away_id')}, away, TRY_CAST(league_id AS BIGINT), count(*) FROM {ELO} GROUP BY 1, 2, 3)
        SELECT team_id, team, league_id, sum(n) AS n FROM t WHERE team_id IS NOT NULL GROUP BY 1, 2, 3""").fetchdf()
    career_teams = c.execute(f"SELECT {norm_id('team_id')} AS team_id, any_value(team) AS team, count(*) AS spells FROM {YCAR} WHERE team_id IS NOT NULL GROUP BY 1").fetchdf()
    band = {k: v[4] for k, v in COMPETITIONS.items()}
    kind = {k: v[5] for k, v in COMPETITIONS.items()}
    plays["band"] = plays.league_id.map(band)
    plays["national"] = plays.league_id.map(kind).eq("national youth")
    names = (plays.sort_values("n", ascending=False).groupby("team_id").team.first()
             .combine_first(career_teams.set_index("team_id").team))
    rows = []
    for tid, team in names.items():
        p = plays[plays.team_id == tid]
        bands = set(p.band.dropna())
        by_name = level_from_name(team)
        if len(p) and p.national.all():
            level, how = f"national {sorted(bands)[0]}", "competition"
        elif bands == {"senior"}:
            level, how = (by_name if by_name == "reserve" else "first team"), "competition"
        elif bands and "senior" not in bands:
            level, how = (by_name or sorted(bands)[0]), "competition"
        elif bands:
            level, how = "mixed", "competition"
        else:
            level, how = (by_name or "first team"), "name only"
        conflict = bool(by_name and by_name.startswith("U") and bands == {"senior"})
        rows.append(dict(team_id=tid, team=team, level=level, level_from=how, competitions=", ".join(sorted(p.league_id.map(lambda x: COMPETITIONS.get(int(x), ("?",))[0]).unique())) if len(p) else "",
                         matches=int(p.n.sum()), conflict=conflict, club_key=base_name(team)))
    teams = pd.DataFrame(rows)
    firsts = teams[teams.level == "first team"].drop_duplicates("club_key").set_index("club_key").team_id
    teams["parent_team_id"] = teams.apply(lambda r: firsts.get(r.club_key) if r.level != "first team" and not r.level.startswith("national") else None, axis=1)
    teams.to_parquet(OUT / "teams.parquet", index=False)
    in_facts = teams[teams.matches > 0]
    orphans = in_facts[in_facts.team.isna() | in_facts.level.isna()]
    gate["teams"] = int(len(teams))
    gate["teams in match facts"] = int(len(in_facts))
    gate["teams by level"] = teams.level.value_counts().to_dict()
    gate["orphan teams"] = int(len(orphans))
    gate["level conflicts (youth name, senior league)"] = teams[teams.conflict].team.tolist()[:20]
    gate["mixed (senior and youth competitions under one id)"] = teams[teams.level == "mixed"].team.tolist()[:20]
    gate["reserves and youth sides linked to their first team"] = f"{teams.parent_team_id.notna().sum()} of {(~teams.level.isin(['first team']) & ~teams.level.str.startswith('national')).sum()}"

    # the two clocks
    clocks = []
    for source, table, col, rule in CLOCKS:
        r = dict(source=source, happened=col or "", known_rule=rule, rows=None, happened_parseable=None)
        if table and col:
            n, ok = c.execute(f"SELECT count(*), count(TRY_CAST(substr(CAST({col} AS VARCHAR), 1, 10) AS DATE)) FROM {table}").fetchone()
            r.update(rows=int(n), happened_parseable=round(ok / n, 4) if n else None)
        elif table:
            r["rows"] = int(c.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        clocks.append(r)
    pd.DataFrame(clocks).to_parquet(OUT / "clocks.parquet", index=False)
    gate["clocks"] = {r["source"]: r["happened_parseable"] for r in clocks if r["happened_parseable"] is not None}

    gate["passed"] = not unmapped and gate["orphan teams"] == 0
    (OUT / "gate.json").write_text(json.dumps(gate, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    report(gate, comps, labels, teams, pd.DataFrame(clocks))
    return gate


def report(gate, comps, labels, teams, clocks):
    L = [f"# Registries (Phase 0), built {gate['built']}", "",
         f"**Gate: {'PASSED' if gate['passed'] else 'FAILED'}**: {gate['league ids seen']} league ids seen, "
         f"unmapped {gate['league ids unmapped'] or 'none'}; {gate['orphan teams']} orphan teams.", "",
         "## Competitions", "", "| Key | Name | Country | Tier | Age | Kind | MatchData id | Name variants |", "|---|---|---|---|---|---|---|---|"]
    nv = labels.groupby("league_id").label.nunique()
    for r in comps.itertuples():
        L.append(f"| {r.comp_key} | {r.name} | {r.country} | {r.tier if pd.notna(r.tier) else ''} | {r.age_band} | {r.kind} | {r.league_id} | {nv.get(r.league_id, 0)} |")
    L += ["", "## Stages parsed from the name variants", "", "| Stage | Variants |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in labels.stage.value_counts().items()]
    L += ["", "## Teams", "", f"{gate['teams']} teams, {gate['teams in match facts']} of them in match facts. Linked to a first team: "
          f"{gate['reserves and youth sides linked to their first team']}.", "", "| Level | Teams |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in gate["teams by level"].items()]
    if gate["level conflicts (youth name, senior league)"]:
        L += ["", "Youth name but senior league (to check): " + ", ".join(gate["level conflicts (youth name, senior league)"])]
    if gate["mixed (senior and youth competitions under one id)"]:
        L += ["", "One id in senior and youth competitions (to check): " + ", ".join(gate["mixed (senior and youth competitions under one id)"])]
    L += ["", "## The two clocks", "", "| Source | Happened | Parseable | Known |", "|---|---|---|---|"]
    for r in clocks.itertuples():
        L.append(f"| {r.source} | {r.happened} | {'' if pd.isna(r.happened_parseable) else f'{r.happened_parseable:.2%}'} | {r.known_rule} |")
    L += ["", "Coaches: no source in the lake yet; the coach registry waits for one."]
    (OUT / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    g = build(duckdb.connect())
    print(json.dumps({k: v for k, v in g.items() if k not in ("clocks",)}, indent=1, ensure_ascii=False, default=str))
    print("clocks:", g["clocks"])
