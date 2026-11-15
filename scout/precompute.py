"""The Scout Desk v1: precompute every table the desk reads into one small DuckDB file.

A page needs no join at request time: people (panel A), careers (C, D), MatchData matches (F, G), the outlook the models
that passed their gates give (B, I), the boards (Discover), and the provenance of each table (L).

    python scout/precompute.py      (Promesse venv) -> <data root>/scout/scout.duckdb
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
GOLD = LAKE / "gold"
MODELS = LAKE / "models"
TM = DATA / "transfermarkt-datasets.duckdb"
OUT = DATA / "scout" / "scout.duckdb"
SEASON_NOW = 2025          # the last complete season (2025/26)
YOUTH = r"U1[6-9]|U2[0-3]|Youth|Premier League 2|Primavera|Juvenil"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".building.duckdb")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    con.execute(f"attach '{TM.as_posix()}' as tm (read_only)")
    p = lambda f: f"read_parquet('{f.as_posix()}')"
    fm_files = (LAKE / "matchdata" / "player_matches").as_posix() + "/**/*.parquet"

    # identity: Transfermarkt id -> the other sources
    con.execute(f"""create table ids as select try_cast(tm_id as bigint) tm_id, try_cast(ea_id as bigint) ea_id,
                    matchdata_id::varchar matchdata_id, n_sources from {p(LAKE / 'identity' / 'persons.parquet')} where tm_id is not null""")
    # A: who he is, with the dates of what we know
    con.execute(f"""
        create table people as
        with mv as (select player_id::bigint pid, arg_max(market_value_in_eur, date) mv, max(date)::date mv_date,
                           max(market_value_in_eur) mv_max from tm.player_valuations group by 1),
             ea as (select e.ea_id, arg_max(overall, date) ea_overall, arg_max(potential, date) ea_potential,
                           max(date)::date ea_date from {p(GOLD / 'ea_ratings.parquet')} e where date <= current_date group by 1),
             last_app as (select player_id pid, arg_max(club_id, date) club_id, max(date)::date last_app,
                                 sum(minutes) filter (where season = {SEASON_NOW}) min_now,
                                 sum(qmin) filter (where season = {SEASON_NOW}) qmin_now
                          from {p(GOLD / 'appearance_quality.parquet')} group by 1)
        select pl.player_id::bigint tm_id, pl.name, pl.date_of_birth::date dob, pl.position, pl.sub_position, pl.foot,
               pl.height_in_cm height, pl.contract_expiration_date::date contract, pl.country_of_citizenship nation,
               coalesce(c.name, pl.current_club_id::varchar) club, mv.mv, mv.mv_date, mv.mv_max,
               ea.ea_overall, ea.ea_potential, ea.ea_date, la.last_app, coalesce(la.min_now, 0) min_now,
               coalesce(la.qmin_now, 0) qmin_now, ids.matchdata_id, ids.n_sources
        from tm.players pl
        left join tm.clubs c on c.club_id::bigint = pl.current_club_id::bigint
        left join mv on mv.pid = pl.player_id::bigint
        left join ids on ids.tm_id = pl.player_id::bigint
        left join ea on ea.ea_id = ids.ea_id
        left join last_app la on la.pid = pl.player_id::bigint
        where pl.date_of_birth is not null and (la.last_app >= date '2023-07-01' or mv.mv_date >= date '2024-07-01')
    """)
    # C, D: career by season and club
    con.execute(f"""
        create table career as
        with pcs as (select * from {p(GOLD / 'player_club_seasons.parquet')}),
             tot as (select player_id, season, club_id, sum(minutes) as "minutes", sum(qmin) as qmin, count(*) as apps,
                            sum(minutes) filter (where ctype in ('international_cup', 'other')) europe_min
                     from {p(GOLD / 'appearance_quality.parquet')} group by 1, 2, 3)
        select t.player_id tm_id, t.season, t.club_id, coalesce(c.name, t.club_id::varchar) club,
               coalesce(comp.name, pcs.league) league, t.minutes, t.qmin, t.apps, coalesce(t.europe_min, 0) europe_min,
               pcs.league_min, round(pcs.share, 3) as share, round(pcs.team_level_rel) as "level"
        from tot t left join pcs on pcs.player_id = t.player_id and pcs.season = t.season and pcs.club_id = t.club_id
        left join tm.clubs c on c.club_id::bigint = t.club_id
        left join tm.competitions comp on comp.competition_id = pcs.league
        where t.player_id in (select tm_id from people)
    """)
    # F, G: MatchData matches of the people the identity links
    con.execute(f"""
        create table matches as
        select ids.tm_id, try_cast(left(m.date, 10) as date) date, m.league, m.home_team, m.away_team, m.team, m.role,
               m.position_id, try_cast(m.x as double) x, try_cast(m.y as double) y, m."Minutes played" as "minutes",
               m."matchdata rating" rating, m.Goals goals, m.Assists assists, regexp_matches(m.league, '{YOUTH}') youth
        from read_parquet('{fm_files}', union_by_name=true) m join ids on ids.matchdata_id = m.player_id::varchar
        where ids.tm_id in (select tm_id from people) and m."Minutes played" > 0
    """)
    # A, today: his club comes from the freshest dated evidence. The Transfermarkt datasets stop at their last update
    # (the October 2026 download ends in June 2026, before the summer window); MatchData's matches run to this week. A senior
    # club match in MatchData newer than his last Transfermarkt appearance wins (national-team matches left out).
    con.execute("""
        alter table people add column club_tm varchar;
        alter table people add column club_src varchar;
        alter table people add column club_date date;
        update people set club_tm = club, club_src = 'Transfermarkt', club_date = last_app;
        update people set club = f.team, club_date = f.d, club_src = 'MatchData'
        from (select m.tm_id, arg_max(m.team, m.date) team, max(m.date) d from matches m join people pe using (tm_id)
              where not m.youth and lower(m.team) <> lower(coalesce(pe.nation, '')) group by 1) f
        where f.tm_id = people.tm_id and f.d > coalesce(people.last_app, date '1900-01-01');
    """)
    # What others think of him (benchmarks, never the engines' inputs: models/inputs.py): EA and market value are in
    # people already; MatchData's match rating, averaged over his senior matches of the last 365 days
    con.execute("""
        alter table people add column fm_rating double;
        alter table people add column fm_rating_n integer;
        update people set fm_rating = r.avg_r, fm_rating_n = r.n
        from (select tm_id, round(avg(rating), 2) avg_r, count(*) n from matches
              where rating is not null and not youth and date >= (select max(date) from matches) - interval 365 day
              group by 1) r
        where r.tm_id = people.tm_id;
    """)
    # How rare he is: quality minutes up to his age (the seasons he started at that age or younger), ranked against every
    # player Transfermarkt has with senior minutes by the same age, 2012/13 on. Only ages he has completed count.
    con.execute(f"""
        create table rarity as
        with s as (select ps.player_id, ps.qmin,
                          floor(date_diff('day', pl.date_of_birth::date, make_date(ps.season::int, 7, 1)) / 365.25) a
                   from {p(GOLD / 'player_seasons.parquet')} ps join tm.players pl on pl.player_id::bigint = ps.player_id
                   where pl.date_of_birth is not null and ps.qmin > 0),
             reach as (select player_id::bigint pid,
                              floor(date_diff('day', date_of_birth::date, date '{SEASON_NOW}-07-01') / 365.25) amax
                       from tm.players where date_of_birth is not null),
             cum as (select x.player_id, ag.a, sum(x.qmin) q
                     from s x join (select range a from range(15, 24)) ag on x.a <= ag.a join reach on reach.pid = x.player_id
                     where ag.a <= reach.amax group by 1, 2),
             ranked as (select *, rank() over (partition by a order by q desc) rk, count(*) over (partition by a) n from cum),
             second as (select r.a, pl.name, round(r.q) q from ranked r join tm.players pl on pl.player_id::bigint = r.player_id
                        where r.rk = 2)
        select r.player_id tm_id, r.a::integer age, round(r.q) q, r.rk::integer rank, r.n::integer n,
               s2.name second_name, s2.q second_q
        from ranked r join people pe on pe.tm_id = r.player_id
        left join second s2 on s2.a = r.a and r.rk = 1
        where r.a = floor(date_diff('day', pe.dob, date '{SEASON_NOW}-07-01') / 365.25)
    """)
    # C: his terrace, one seat per match: senior matches from Transfermarkt (level of the match vs the big five),
    # youth matches from MatchData (2021 on). A season runs July to June.
    con.execute(f"""
        create table terrace as
        select player_id tm_id, season, date::date date,
               case ctype when 'domestic_league' then 'league' when 'domestic_cup' then 'cup' else 'europe' end kind,
               minutes, round(level_rel) as "level"
        from {p(GOLD / 'appearance_quality.parquet')} where player_id in (select tm_id from people) and minutes > 0
        union all
        select tm_id, case when month(date) >= 7 then year(date) else year(date) - 1 end season, date, 'youth' kind,
               minutes::integer, null
        from matches where youth
    """)
    # B, I: what the models that passed their gates say (models/score_current.py)
    if (MODELS / "current_outlook.parquet").exists():
        con.execute(f"create table outlook as select * from {p(MODELS / 'current_outlook.parquet')}")
        info = json.loads((MODELS / "current_outlook.json").read_text(encoding="utf-8"))
        ProEngine = MODELS / "current_outlook_v2c.parquet"
        if v2c.exists():      # the desk's call is ProEngine (models/score_v2c.py); bands stay as they were
            con.execute(f"update outlook set p_reg3 = v.p_reg3 from {p(v2c)} v where outlook.player_id = v.player_id")
            v2 = json.loads((MODELS / "current_outlook_v2c.json").read_text(encoding="utf-8"))
            info.update({"calls_status": v2["calls_status"], "calls_label": v2["calls_label"], "reg3_model": "ProEngine"})   # ProEngine, by its final name
    else:
        con.execute("create table outlook (player_id bigint, p_reg3 double, qmin3_p10 double, qmin3_p50 double, qmin3_p90 double)")
        info = {}
    # Discover: the boards
    con.execute(f"""
        create table boards as
        with age_now as (select tm_id, date_diff('day', dob, date '{SEASON_NOW}-07-01') / 365.25 age from people),
             youth as (select tm_id, sum(minutes) ym from matches where youth and date >= date '{SEASON_NOW}-07-01' group by 1),
             senior as (select tm_id, sum(league_min) lm from career where season = {SEASON_NOW} group by 1)
        select 'above_age' board, a.tm_id, s.lm score from age_now a join senior s using (tm_id)
          where a.age < 19.5 and s.lm >= 900
        union all
        select 'debut_watch', a.tm_id, y.ym from age_now a join youth y using (tm_id) left join senior s using (tm_id)
          where a.age < 20 and y.ym >= 900 and coalesce(s.lm, 0) = 0
        union all
        select 'under_radar', o.player_id, o.p_reg3 from outlook o join people pe on pe.tm_id = o.player_id
          where o.p_reg3 >= 0.5 and coalesce(pe.mv, 0) <= 1500000
          and {'false' if info.get('calls_status') != 'earned' else 'true'}   -- a call behind the market is not a market-beating board
    """)
    # how fresh each source is, written on every build and shown on every player page
    one = lambda sql: con.execute(sql).fetchone()[0]
    as_of = {"Transfermarkt appearances": str(one("select max(date) from tm.appearances")),
             "Transfermarkt valuations": str(one("select max(date) from tm.player_valuations")),
             "MatchData matches": str(one("select max(date) from matches")),
             "EA ratings": str(one(f"select max(date)::date from {p(GOLD / 'ea_ratings.parquet')} where date <= current_date")),
             "club from MatchData (newer than Transfermarkt)": int(one("select count(*) from people where club_src = 'MatchData'"))}
    prov = {
        "built": str(date.today()),
        "as_of": as_of,
        "sources": {"Transfermarkt datasets": "players, clubs, valuations, appearances (2012-2026)",
                    "MatchData": "matches, ratings, lineup positions (2021 on)",
                    "EA": "FIFA 15 to FC 26, each rating dated by when it was known",
                    "Identity": "one person across Transfermarkt, EA, PES, MatchData, StatsBomb, Wyscout"},
        "models": {"inputs": "the engines read what happened only; EA, PES, market value and MatchData ratings are benchmarks",
                   "team strength": "Elo+ on Transfermarkt games (a team-strength rating that beat plain Elo in its test)",
                   "quality minutes": "minutes x match level vs the big five (qmin v1)",
                   "outlook": info},
    }
    con.execute("create table provenance as select ? as doc", [json.dumps(prov)])
    counts = {t: con.execute(f"select count(*) from {t}").fetchone()[0]
              for t in ("people", "career", "terrace", "rarity", "matches", "outlook", "boards")}
    con.close()
    tmp.replace(OUT)
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
