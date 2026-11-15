"""Identity v3, step 1: one table of people records from every source -> lake/identity/records.parquet.

One row per person per id space ("family"). Inside a family the id already means one person, so the family's rows
for that id are folded together first:
  ea        FIFA 15-23 (every update), FC 24, FC 26/27: one EA id across editions
  konami    privately collected game ratings 26 and the cached gamerating_b pages (PES 2011-2021): the same Konami id
  tm        Transfermarkt (players, appearances, transfers)
  matchdata    seniors' match rows, youth match rows, the youth profiles (exact birth dates) and careers
  statsbomb lineups of the open data
  wyscout   the public 2017/18 player list
an open encyclopedia isn't a family: its pages are already keyed by EA id, so they ride on the EA record.

Every row carries what the linkage compares (identity/link.py):
  name, alt_name, name_tokens        normalised (accents folded, lower case), tokens of every name the source uses
  dob, dob_lo, dob_hi                an exact birth date (dob = dob_lo = dob_hi) or a window from age-at-date
  nation, height, foot, pos_group
  club_seasons ("club|year", year = season start) and clubs (every club ever), clubs normalised by club_key()

    python records.py            (identity venv: <local path>)
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import json
import re
from pathlib import Path

import duckdb
import pandas as pd
from unidecode import unidecode

D = Path(DATA_ROOT)
OUT = D / "lake" / "identity" / "records.parquet"

# --- normalisers --------------------------------------------------------------------------------------------------

def norm_name(s) -> str:
    """'Raúl García Escudero' -> 'raul garcia escudero'. Accents folded, punctuation to spaces."""
    if not isinstance(s, str):
        return ""
    s = unidecode(s).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", s)).strip()


# Club words that carry no identity ("FC Barcelona" = "Barcelona"); numbers go too ("1. FC Köln", "Schalke 04").
CLUB_STOP = {"fc", "cf", "ac", "sc", "afc", "cd", "ud", "sd", "rc", "rcd", "as", "ss", "ssc", "us", "fk", "sk", "bk",
             "if", "ik", "sv", "vfb", "vfl", "tsg", "club", "de", "futbol", "football", "calcio", "the", "real_",
             "sporting_", "cp", "sad", "ca", "ec", "se", "aa", "jk", "nk", "hnk", "gnk", "pfc", "kv", "krc", "kaa",
             "rsc", "stade", "olympique", "ogc", "losc", "u19", "u21", "u23", "u18", "u17", "ii", "b", "reserves", "res"}
CLUB_ALIAS = {"psg": "paris saint germain", "paris sg": "paris saint germain", "man utd": "manchester united",
              "man united": "manchester united", "man city": "manchester city", "spurs": "tottenham hotspur",
              "inter": "internazionale", "inter milan": "internazionale", "milan": "milan", "barca": "barcelona",
              "atletico madrid": "atletico madrid", "atl madrid": "atletico madrid", "bayern munchen": "bayern munich",
              "fc bayern munchen": "bayern munich", "wolves": "wolverhampton wanderers"}


def club_key(s) -> str:
    """'FC Bayern München' -> 'bayern munich'; reserve and youth sides fold into the club (a youth season there
    still says the same person was at that club)."""
    n = norm_name(s)
    if not n:
        return ""
    if n in CLUB_ALIAS:
        return CLUB_ALIAS[n]
    toks = [t for t in n.split() if t not in CLUB_STOP and not t.isdigit()]
    k = " ".join(toks) or n
    return CLUB_ALIAS.get(k, k)


NATION_ALIAS = {"korea republic": "south korea", "republic of korea": "south korea", "korea south": "south korea",
                "cote d ivoire": "ivory coast", "cote divoire": "ivory coast", "usa": "united states",
                "united states of america": "united states", "turkiye": "turkey", "czechia": "czech republic",
                "ir iran": "iran", "republic of ireland": "ireland", "china pr": "china", "bosnia herzegovina":
                "bosnia and herzegovina", "bosnia": "bosnia and herzegovina", "dr congo": "congo dr",
                "democratic republic of congo": "congo dr", "congo democratic republic": "congo dr",
                "cape verde islands": "cape verde", "cabo verde": "cape verde", "macedonia": "north macedonia",
                "fyr macedonia": "north macedonia", "kyrgyz republic": "kyrgyzstan", "holland": "netherlands",
                "the gambia": "gambia", "guinea bissau": "guinea bissau", "curacao": "curacao",
                "chinese taipei": "taiwan", "korea dpr": "north korea", "russian federation": "russia"}


def nation(s) -> str:
    n = norm_name(s)
    return NATION_ALIAS.get(n, n)


def pos_group(s) -> str | None:
    """Every source's position words or codes -> GK / DF / MF / FW."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    t = str(s).split(",")[0].strip().upper()
    if t in ("0", "GK", "G", "GOALKEEPER") or "GOALKEEPER" in t:
        return "GK"
    if t in ("1",) or t in ("CB", "LB", "RB", "LWB", "RWB", "DF", "D", "DEFENDER", "DEFENCE", "SW") or "BACK" in t \
            or "DEFEND" in t:
        return "DF"
    if t in ("2",) or t in ("CM", "CDM", "CAM", "DM", "AM", "LM", "RM", "DMF", "CMF", "AMF", "LMF", "RMF", "MF", "M",
                            "MIDFIELDER", "MIDFIELD") or "MIDFIELD" in t:
        return "MF"
    if t in ("3",) or t in ("ST", "CF", "LW", "RW", "SS", "LWF", "RWF", "FW", "F", "FORWARD", "ATTACK", "STRIKER") \
            or "WING" in t or "FORWARD" in t or "STRIKER" in t:
        return "FW"
    return None


def foot(s) -> str | None:
    n = norm_name(s)
    return {"left": "left", "right": "right", "both": "both", "l": "left", "r": "right"}.get(n)


def season_start(s) -> int | None:
    """'2019/2020', '2019-2020', '19/20', '2019' -> 2019 (calendar-year seasons keep their year)."""
    if s is None:
        return None
    m = re.match(r"\s*(\d{2,4})", str(s))
    if not m:
        return None
    y = int(m.group(1))
    return y + 2000 if y < 100 else y


# --- one builder per family; each returns raw rows, normalised at the end ----------------------------------------
# Raw columns: family, source_id, name, alt_name, dob, dob_lo, dob_hi, nation, height, foot, pos, clubs_seasons
# (a list of [club, season_start] pairs).

con = duckdb.connect()


def ea() -> pd.DataFrame:
    """FIFA 15-23 + FC 24 + FC 26/27, folded per EA id. Season start = 2000 + version - 1 (FIFA 20 = 2019/20)."""
    fifa = D / "fifa_all_updates.parquet"
    fc24 = D / "kaggle/stefanoleone992__ea-sports-fc-24-complete-player-dataset/male_players.csv"
    cols = {r[0] for r in con.execute(f"describe select * from '{fifa}'").fetchall()}
    foot_col = "preferred_foot" if "preferred_foot" in cols else "null"
    hist = f"""
        select player_id::bigint as id, long_name, short_name, try_cast(dob as date) as dob, try_cast(height_cm as int) as height,
               nationality_name as nat, {foot_col}::varchar as ft, player_positions as pos, club_name as club,
               2000 + fifa_version::int - 1 as season
        from '{fifa}'
        union all
        select player_id::bigint, long_name, short_name, try_cast(dob as date), try_cast(height_cm as int), nationality_name,
               preferred_foot::varchar, player_positions, club_name, 2023
        from read_csv_auto('{fc24}') where fifa_version = 24
        union all
        select ea_id::bigint, trim(coalesce(first_name,'') || ' ' || coalesce(last_name,'')), common_name,
               try_cast(dob as date), try_cast(height as int), nationality, foot::varchar, position, team,
               2000 + try_cast(regexp_extract(edition::varchar, '([0-9]+)', 1) as int) - 1
        from read_parquet(['{D / "ea_fc26.parquet"}', '{D / "ea_fc27.parquet"}'], union_by_name=true)
    """
    df = con.execute(f"""
        with h as ({hist})
        select 'ea' as family, id::varchar as source_id, arg_max(long_name, season) as name, arg_max(short_name, season) as alt_name,
               mode(dob) as dob, mode(height) as height, mode(nat) as nat, mode(ft) as ft, mode(pos) as pos,
               list(distinct [club, season::varchar]) filter (where club is not null) as cs
        from h group by id
    """).df()
    df["dob_lo"] = df["dob_hi"] = df["dob"]
    return df


def tm() -> pd.DataFrame:
    """Transfermarkt: exact birth dates; club-seasons from appearances (season from the match date) and transfers
    (the club he joined, from that season on: youth clubs and loans that appearances miss)."""
    tmdb = D / "transfermarkt-datasets.duckdb"
    con.execute(f"attach '{tmdb}' as tmdb (read_only)")
    df = con.execute("""
        with a as (
            select ap.player_id, c.name as club,
                   case when month(ap.date::date) >= 7 then year(ap.date::date) else year(ap.date::date) - 1 end as season
            from tmdb.appearances ap join tmdb.clubs c on c.club_id = ap.player_club_id
            union
            select player_id, to_club_name, try_cast('20' || left(transfer_season, 2) as int)
            from tmdb.transfers where to_club_name is not null
        ), c as (
            select player_id, list(distinct [club, season::varchar]) as cs from a where season is not null group by player_id
        )
        select 'tm' as family, p.player_id::varchar as source_id, p.name, null as alt_name, try_cast(p.date_of_birth as date) as dob,
               try_cast(p.height_in_cm as int) as height, p.country_of_citizenship as nat, p.foot as ft, p.position as pos, c.cs
        from tmdb.players p left join c using (player_id)
    """).df()
    df["dob_lo"] = df["dob_hi"] = df["dob"]
    return df


def _gamerating_b_identity(path: Path) -> dict | None:
    """Name, nation, team, height, age and foot from a cached gamerating_b player page (its parsed table keeps only the
    ratings). The header reads: NAME, POS, NAME, [Playing Style], NATION, ·, TEAM, OVR, n, Height, h, ..., Age, a."""
    import html as h
    s = path.read_text(encoding="utf-8")
    m = re.search(r"<h1[^>]*>(.*?)</h1>", s, re.S)
    t = h.unescape(re.sub(r"<[^>]+>", "\n", re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S)))
    lines = [x.strip() for x in t.splitlines() if x.strip()]
    try:
        i = lines.index("OVR")
    except ValueError:
        return None
    grab = lambda k: lines[lines.index(k, i) + 1] if k in lines[i:] else None  # noqa: E731
    name = h.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else lines[i - 5]
    return {"name": name, "team": lines[i - 1], "nat": lines[i - 3], "height": grab("Height"), "age": grab("Age"),
            "ft": grab("Stronger Foot"), "pos": lines[i - 5] if len(lines[i - 5]) <= 3 else None}


def konami() -> pd.DataFrame:
    """privately collected game ratings 26 (snapshot May 2026) and every cached gamerating_b page, folded per Konami id. Ages give birth-year
    windows: PES 20YY is read around September of season start S = YY - 1, so born in (S - age - 1, S - age]."""
    rows = []
    fl = pd.read_parquet(D / "fl/fl26_players.parquet", columns=["fl_id", "name", "shirt_name", "age", "height",
                                                                  "registered_position", "left_footed", "team"])
    for r in fl.itertuples():
        team = None if "Classics" in str(r.team) else str(r.team).strip()
        rows.append({"id": int(r.fl_id), "name": r.name, "alt": r.shirt_name, "S": 2025, "age": r.age, "snap_month": 5,
                     "height": r.height, "ft": "left" if r.left_footed else "right", "pos": r.registered_position,
                     "team": team, "nat": None})
    raw = D / "raw" / "gamerating_b"
    for ed_dir in sorted(p for p in raw.iterdir() if p.is_dir()):
        S = int(ed_dir.name[3:]) - 1
        for f in ed_dir.glob("*.html"):
            if not f.stem.isdigit() or not f.stat().st_size:
                continue
            rec = _gamerating_b_identity(f)
            if rec:
                rows.append({"id": int(f.stem), "name": rec["name"], "alt": None, "S": S, "age": rec["age"],
                             "snap_month": 9, "height": rec["height"], "ft": rec["ft"], "pos": rec["pos"],
                             "team": rec["team"], "nat": rec["nat"]})
    k = pd.DataFrame(rows)
    k["age"] = pd.to_numeric(k["age"], errors="coerce")
    k["height"] = pd.to_numeric(k["height"], errors="coerce")
    # Birth window per row, then intersected per id. Konami's ages run on their own reference dates (the gate review
    # found privately collected game ratings a year "old" for some players and a year "young" for others; PES 2018 counts Luca Rigoni,
    # born December 1984, as 33), so an age only says: born in calendar year Y - age - 1 or Y - age, where Y is the
    # year after the edition's season start (2026 for privately collected game ratings 26). Two whole years, honest rather than sharp.
    yr = (k["S"] + 1).astype("Int64")
    k["lo"] = pd.to_datetime((yr - k["age"] - 1).astype("Int64").astype(str) + "-01-01", errors="coerce")
    k["hi"] = pd.to_datetime((yr - k["age"]).astype("Int64").astype(str) + "-12-31", errors="coerce")
    # Konami reuses about 1 % of ids for a different player in another edition (FL "Nicolai Rapp" is "D. JANSSEN" in
    # PES 2018). A row joins its id's record only if its name agrees with the id's first name (a shared token, or a
    # close last name: "GIANETTI" / "Giannetti"); otherwise it becomes its own record, "<id>~<edition start>".
    from rapidfuzz import fuzz
    k["name_n"] = k["name"].map(norm_name)
    first = k.groupby("id")["name_n"].transform("first")

    def agrees(a: str, b: str) -> bool:
        ta, tb = set(a.split()), set(b.split())
        return bool(ta & tb) or (bool(ta) and bool(tb) and fuzz.ratio(a.split()[-1], b.split()[-1]) >= 80)

    split = [not agrees(a, b) for a, b in zip(k["name_n"], first)]
    k["id"] = [f"{i}~{s}" if sp else str(i) for i, s, sp in zip(k["id"], k["S"], split)]
    out = []
    for kid, g in k.groupby("id"):
        lo, hi = g["lo"].max(), g["hi"].min()
        if pd.notna(lo) and pd.notna(hi) and lo > hi:              # ages that disagree: keep the widest honest window
            lo, hi = g["lo"].min(), g["hi"].max()
        out.append({"family": "konami", "source_id": str(kid), "name": g["name"].iloc[0], "alt_name": g["alt"].dropna().iloc[0]
                    if g["alt"].notna().any() else None, "dob": None, "dob_lo": lo, "dob_hi": hi,
                    "height": g["height"].median(), "nat": g["nat"].dropna().mode().iloc[0] if g["nat"].notna().any() else None,
                    "ft": g["ft"].dropna().mode().iloc[0] if g["ft"].notna().any() else None,
                    "pos": g["pos"].dropna().mode().iloc[0] if g["pos"].notna().any() else None,
                    "cs": [[t, str(s)] for t, s in g[["team", "S"]].dropna().drop_duplicates().itertuples(index=False)]})
    return pd.DataFrame(out)


def matchdata() -> pd.DataFrame:
    """Seniors' and youth match rows give a name, a nation, club-seasons and an age at each match date, so a birth
    window: born in (date - (age + 1) years, date - age years]. The youth profiles add exact birth dates and the
    career sections add youth clubs year by year."""
    parts = str(D / "lake/matchdata/player_matches/*/*/*.parquet")
    youth_m = D / "matchdata_youth_match_players.parquet"
    ycols = {r[0] for r in con.execute(f"describe select * from '{youth_m}'").fetchall()}
    union_youth = ""
    if {"player_id", "name", "age", "date", "team", "season", "country"} <= ycols:
        union_youth = f"union all select player_id, name, age, date, team, season, country, usual_position_id from '{youth_m}'"
    df = con.execute(f"""
        with m as (
            select player_id, name, age, date, team, season, country, usual_position_id from '{parts}'
            {union_youth}
        ), d as (
            select *, try_cast(left(date::varchar, 10) as date) as dd from m where player_id is not null
        )
        select 'matchdata' as family, player_id::varchar as source_id, mode(name) as name, null as alt_name,
               max(dd - to_years(age::int + 1) + interval 1 day) filter (where age is not null) as dob_lo,
               min(dd - to_years(age::int)) filter (where age is not null) as dob_hi,
               mode(country) as nat, mode(usual_position_id)::varchar as pos,
               list(distinct [team, season::varchar]) filter (where team is not null) as cs
        from d group by player_id
    """).df()
    yp = pd.read_parquet(D / "matchdata_youth_players.parquet", columns=["player_id", "name", "birth_date", "position"])
    yp["player_id"] = yp["player_id"].astype(str)
    yp["birth_date"] = pd.to_datetime(yp["birth_date"], errors="coerce", utc=True).dt.tz_localize(None)
    df = df.merge(yp.rename(columns={"name": "yname", "position": "ypos"}), how="outer", left_on="source_id",
                  right_on="player_id")
    df["source_id"] = df["source_id"].fillna(df["player_id"])
    df["family"] = "matchdata"
    df["name"] = df["name"].fillna(df["yname"])
    df["pos"] = df["pos"].fillna(df["ypos"])
    df["dob"] = df["birth_date"]
    exact = df["dob"].notna()
    df.loc[exact, "dob_lo"] = df.loc[exact, "dob"]
    df.loc[exact, "dob_hi"] = df.loc[exact, "dob"]
    car = pd.read_parquet(D / "matchdata_youth_careers.parquet", columns=["player_id", "team", "start", "end"])
    car["s"] = pd.to_datetime(car["start"], errors="coerce", utc=True).dt.year
    car["e"] = pd.to_datetime(car["end"], errors="coerce", utc=True).dt.year.fillna(2026)
    extra: dict[str, list] = {}
    for r in car.dropna(subset=["s"]).itertuples():
        for y in range(int(r.s), int(min(r.e, r.s + 12)) + 1):
            extra.setdefault(str(r.player_id), []).append([r.team, str(y)])
    df["cs"] = [([list(x) for x in cs] if hasattr(cs, "__len__") and not isinstance(cs, str) else []) + extra.get(sid, [])
                for cs, sid in zip(df["cs"], df["source_id"])]
    df["height"] = None
    df["ft"] = None
    return df[["family", "source_id", "name", "alt_name", "dob", "dob_lo", "dob_hi", "height", "nat", "ft", "pos", "cs"]]


def statsbomb() -> pd.DataFrame:
    """Open-data lineups: full name and nickname, nation, club-seasons (national-team matches don't count as clubs)."""
    sb = D / "lake/statsbomb"
    df = con.execute(f"""
        with l as (
            select l.player_id, l.player, l.nickname, l.country, l.team, l.first_position,
                   m."season.season_name" as season, l.team = l.country as national
            from '{sb / "lineups.parquet"}' l join '{sb / "matches.parquet"}' m using (match_id)
        )
        select 'statsbomb' as family, player_id::varchar as source_id, mode(player) as name, mode(nickname) as alt_name,
               mode(country) as nat, mode(first_position) as pos,
               list(distinct [team, season]) filter (where not national) as cs
        from l group by player_id
    """).df()
    df["dob"] = df["dob_lo"] = df["dob_hi"] = None
    df["height"] = df["ft"] = None
    return df


def wyscout() -> pd.DataFrame:
    """The public 2017/18 list: exact birth dates, height, foot; the club is the one he played for that season."""
    w = json.load(open(D / "wyscout/players.json", encoding="utf-8"))
    teams_f = D / "wyscout/teams.json"
    teams = {t["wyId"]: t.get("officialName") or t.get("name") for t in json.load(open(teams_f, encoding="utf-8"))} \
        if teams_f.exists() else {}
    rows = []

    def unescape(s):
        """the public list writes accents as literal escapes ("Jo\\u00ebl"); read them as the letters they are"""
        if not isinstance(s, str) or "\\u" not in s:
            return s
        try:
            return s.encode("latin-1", "backslashreplace").decode("unicode_escape")
        except Exception:
            return s

    for p in w:
        full = " ".join(unescape(x) for x in (p.get("firstName"), p.get("middleName"), p.get("lastName")) if x)
        dob = pd.to_datetime(p.get("birthDate"), errors="coerce")
        club = teams.get(p.get("currentTeamId"))
        rows.append({"family": "wyscout", "source_id": str(p["wyId"]), "name": full, "alt_name": unescape(p.get("shortName")),
                     "dob": dob, "dob_lo": dob, "dob_hi": dob, "height": p.get("height") or None,
                     "nat": (p.get("passportArea") or p.get("birthArea") or {}).get("name"), "ft": p.get("foot"),
                     "pos": (p.get("role") or {}).get("name"), "cs": [[club, "2017"]] if club else []})
    return pd.DataFrame(rows)


# --- normalise and write ----------------------------------------------------------------------------------------

def finish(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["uid"] = df["family"] + ":" + df["source_id"].astype(str)
    df["name_n"] = df["name"].map(norm_name)
    df["alt_n"] = df["alt_name"].map(norm_name)
    df["name_tokens"] = [sorted(set(a.split()) | set(b.split())) for a, b in zip(df["name_n"], df["alt_n"])]
    df["last_tok"] = df["name_n"].str.split().str[-1].fillna("")
    for c in ("dob", "dob_lo", "dob_hi"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    # Ages that contradict each other give an empty window (lo after hi): keep both ends, widened by half a year.
    bad = df["dob_lo"] > df["dob_hi"]
    lo, hi = df.loc[bad, "dob_hi"], df.loc[bad, "dob_lo"]
    df.loc[bad, "dob_lo"] = lo - pd.Timedelta(days=183)
    df.loc[bad, "dob_hi"] = hi + pd.Timedelta(days=183)
    for c in ("dob", "dob_lo", "dob_hi"):
        df[c] = df[c].dt.date
    df["birth_year"] = pd.to_datetime(df["dob_lo"], errors="coerce").dt.year.where(
        pd.to_datetime(df["dob_lo"], errors="coerce").dt.year == pd.to_datetime(df["dob_hi"], errors="coerce").dt.year)
    mid = pd.to_datetime(df["dob_lo"], errors="coerce") + (pd.to_datetime(df["dob_hi"], errors="coerce")
                                                          - pd.to_datetime(df["dob_lo"], errors="coerce")) / 2
    df["birth_year_est"] = mid.dt.year.astype("Int64")             # for blocking when the window spans two years
    df["nation"] = df["nat"].map(nation)
    df["height"] = pd.to_numeric(df["height"], errors="coerce").round().astype("Int64")
    df["foot"] = df["ft"].map(foot)
    df["pos_group"] = df["pos"].map(pos_group)
    keys: dict = {}
    def ck(x):
        if x not in keys:
            keys[x] = club_key(x)
        return keys[x]
    cs_lists, club_lists = [], []
    for cs in df["cs"]:
        items = [list(x) for x in cs] if hasattr(cs, "__len__") and not isinstance(cs, str) else []   # lists or DuckDB arrays
        pairs = {(ck(x[0]), season_start(x[1])) for x in items if len(x) == 2 and x[0]}
        pairs = {(c, s) for c, s in pairs if c}
        cs_lists.append(sorted(f"{c}|{s}" for c, s in pairs if s))
        club_lists.append(sorted({c for c, _ in pairs}))
    df["club_seasons"], df["clubs"] = cs_lists, club_lists
    keep = ["uid", "family", "source_id", "name", "alt_name", "name_n", "alt_n", "name_tokens", "last_tok", "dob",
            "dob_lo", "dob_hi", "birth_year", "birth_year_est", "nation", "height", "foot", "pos_group",
            "club_seasons", "clubs"]
    return df[keep]


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    for build in (ea, tm, konami, matchdata, statsbomb, wyscout):
        f = finish(build())
        print(f"{build.__name__:10s} {len(f):7,d} people | exact dob {f['dob'].notna().mean():5.1%} | birth year "
              f"{f['birth_year_est'].notna().mean():5.1%} | nation {f['nation'].ne('').mean():5.1%} | "
              f"club-seasons {f['club_seasons'].map(len).gt(0).mean():5.1%}", flush=True)
        frames.append(f)
    allr = pd.concat(frames, ignore_index=True)
    allr.to_parquet(OUT)
    print(f"records: {len(allr):,} -> {OUT}")
