"""Promesse data integrity: nothing rotten, nothing silently missing, no player judged on evidence he doesn't have.

Run (Patcher venv, from this folder):  python integrity.py
Writes lake/quality/report.md (the audit, readable), lake/quality/quarantine.parquet (rows that failed a hard rule,
with the rule) and lake/quality/sufficiency.parquet (evidence per player). Nothing is deleted: quarantined rows are
excluded from gold tables by key, and the reason is kept.

Three kinds of rules:
- HARD (quarantine): impossible or contradictory values. The row never reaches a model.
- SOFT (flag): suspicious but possible. The row stays, flagged; models can down-weight it; the report counts them.
- READINESS (gate): a source that isn't complete or fresh enough is not used yet, whatever its rows look like.
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
import datetime as dt
import json
from pathlib import Path

import duckdb
import pandas as pd

from common import LAKE

D = Path(DATA_ROOT)
OUT = LAKE / "quality"
PM = f"read_parquet('{(LAKE / 'matchdata' / 'player_matches').as_posix()}/**/*.parquet', hive_partitioning=true, union_by_name=true)"
TODAY = dt.date.today()

# Stat columns MatchData reports per player-match (presence of any = the row has stats).
STATS = ['"Touches"', '"Accurate passes"', '"Total shots"', '"Defensive actions"', '"Duels won"', '"Recoveries"']


def q(c, sql):
    return c.execute(sql).df()


def matchdata_checks(c) -> tuple[list[dict], pd.DataFrame]:
    """Player-match rows: hard rules (quarantine) and soft flags."""
    findings, quarantine = [], []
    n = c.execute(f"SELECT count(*) FROM {PM}").fetchone()[0]

    def rule(name, kind, where, why):
        df = q(c, f"SELECT match_id, player_id, league, date FROM {PM} WHERE {where}")
        findings.append({"source": "matchdata player-match", "rule": name, "kind": kind, "rows": len(df), "of": n, "why": why})
        if kind == "HARD" and len(df):
            df["rule"] = name
            quarantine.append(df)

    rule("minutes out of range", "HARD", '"Minutes played" < 0 OR "Minutes played" > 130',
         "a match lasts at most 120 minutes plus stoppage")
    rule("date in the future", "HARD", f"TRY_CAST(substr(date, 1, 10) AS DATE) > DATE '{TODAY}'", "a match cannot be played after today")
    rule("accurate > attempted passes", "HARD", '"Accurate passes" > "Accurate passes (of)"', "a contradiction inside the row")
    rule("shots on target > shots", "HARD", '"Shots on target" > "Total shots"', "a contradiction inside the row")
    rule("rating outside 0-10", "HARD", '"matchdata rating" < 0 OR "matchdata rating" > 10', "the scale is 0-10")
    rule("stats with no minutes", "SOFT", '"Minutes played" IS NULL AND (' + " OR ".join(f"{s} IS NOT NULL" for s in STATS) + ")",
         "stats recorded but minutes missing: usable for rates only with the minutes from the lineup")
    rule("all stats zero with minutes", "SOFT", '"Minutes played" >= 30 AND ' + " AND ".join(f"coalesce({s}, -1) = 0" for s in STATS),
         "30+ minutes and not one touch: likely a zero written where nothing was measured")

    dups = q(c, f"SELECT match_id, player_id, count(*) n FROM {PM} GROUP BY 1, 2 HAVING count(*) > 1")
    findings.append({"source": "matchdata player-match", "rule": "duplicate player in a match", "kind": "HARD",
                     "rows": int(dups.n.sum() - len(dups)) if len(dups) else 0, "of": n,
                     "why": "the same player twice in one match; extra copies are dropped, one kept"})

    teams = q(c, f"SELECT match_id, count(DISTINCT team_id) t FROM {PM} GROUP BY 1 HAVING count(DISTINCT team_id) <> 2")
    findings.append({"source": "matchdata player-match", "rule": "match without exactly two teams", "kind": "SOFT",
                     "rows": len(teams), "of": c.execute(f"SELECT count(DISTINCT match_id) FROM {PM}").fetchone()[0],
                     "why": "one side missing (partial lineups): the match counts for minutes, not for team context"})

    # A player's age must move with the calendar. A jump means two people share an id, or a wrong birth date.
    ages = q(c, f"""
        WITH a AS (SELECT player_id, TRY_CAST(substr(date, 1, 10) AS DATE) d, TRY_CAST(age AS DOUBLE) age FROM {PM} WHERE TRY_CAST(age AS DOUBLE) IS NOT NULL)
        SELECT player_id, max(age - date_diff('day', DATE '2000-01-01', d) / 365.25) - min(age - date_diff('day', DATE '2000-01-01', d) / 365.25) spread
        FROM a GROUP BY 1 HAVING spread > 1.6""")
    findings.append({"source": "matchdata player-match", "rule": "age inconsistent with dates", "kind": "SOFT",
                     "rows": len(ages), "of": c.execute(f"SELECT count(DISTINCT player_id) FROM {PM}").fetchone()[0],
                     "why": "players whose age drifts more than a year against the calendar: identity or birth date to check"})

    names = q(c, f"SELECT player_id, count(DISTINCT name) k FROM {PM} GROUP BY 1 HAVING count(DISTINCT name) > 2")
    findings.append({"source": "matchdata player-match", "rule": "three or more names on one id", "kind": "SOFT",
                     "rows": len(names), "of": c.execute(f"SELECT count(DISTINCT player_id) FROM {PM}").fetchone()[0],
                     "why": "spellings vary; three or more may mean merged people"})

    labels = q(c, f"SELECT league_id, count(DISTINCT league) k, string_agg(DISTINCT league, ' | ') AS label_list FROM {PM} GROUP BY 1 HAVING k > 1")
    # resolved once every (id, name) pair has a competition in the registry (Phase 0, registry.py)
    reg = LAKE / "registry" / "competition_names.parquet"
    unmapped = None
    if reg.exists():
        unmapped = c.execute(f"""SELECT count(*) FROM (SELECT DISTINCT CAST(league_id AS BIGINT) AS league_id, league FROM {PM}) p
            LEFT JOIN read_parquet('{reg.as_posix()}') r ON r.league_id = p.league_id AND r.label = p.league
            WHERE r.comp_key IS NULL""").fetchone()[0]
    findings.append({"source": "matchdata player-match", "rule": "one competition, several names",
                     "kind": "RESOLVED" if unmapped == 0 else "READINESS",
                     "rows": len(labels), "of": c.execute(f"SELECT count(DISTINCT league_id) FROM {PM}").fetchone()[0],
                     "why": "every name maps to one competition, with its stage, in the registry (Phase 0)" if unmapped == 0
                     else f"{unmapped if unmapped is not None else 'all'} competition names not yet in the registry (Phase 0)"})
    old = c.execute(f"SELECT count(*) FROM {PM} WHERE TRY_CAST(substr(date, 1, 10) AS DATE) < DATE '2019-07-01'").fetchone()[0]
    findings.append({"source": "matchdata player-match", "rule": "rows older than the crawl window", "kind": "SOFT", "rows": old, "of": n,
                     "why": "the crawl targets 2020/21 onward; older rows (e.g. a 2015 date) are re-dated or dropped by the registry"})
    qdf = pd.concat(quarantine, ignore_index=True) if quarantine else pd.DataFrame(columns=["match_id", "player_id", "league", "date", "rule"])
    return findings, qdf


def coverage(c) -> pd.DataFrame:
    """Share of player-matches with stats, per competition: the tier a model may use them at."""
    has = " OR ".join(f"{s} IS NOT NULL" for s in STATS)
    return q(c, f"""SELECT league, count(DISTINCT match_id) AS matches, count(*) AS n_rows,
                    round(avg(CASE WHEN {has} THEN 1 ELSE 0 END), 3) stats_share,
                    min(TRY_CAST(substr(date, 1, 10) AS DATE)) AS first_date, max(TRY_CAST(substr(date, 1, 10) AS DATE)) AS last_date
                    FROM {PM} GROUP BY 1 ORDER BY matches DESC""")


def sufficiency(c) -> pd.DataFrame:
    """Evidence per player: how much there is to judge him on. Tiers drive bands, weights and abstention."""
    has = " OR ".join(f"{s} IS NOT NULL" for s in STATS)
    df = q(c, f"""SELECT player_id, any_value(name) AS player_name, max(TRY_CAST(age AS DOUBLE)) AS age_last, count(*) AS matches,
                  sum(coalesce("Minutes played", 0)) AS minutes,
                  sum(CASE WHEN {has} THEN coalesce("Minutes played", 0) ELSE 0 END) AS minutes_with_stats,
                  count(DISTINCT league) AS competitions, count(DISTINCT season) AS seasons, max(TRY_CAST(substr(date, 1, 10) AS DATE)) AS last_seen
                  FROM {PM} GROUP BY 1""")
    # Tiers (frozen with the targets): what the models are allowed to say about the player.
    df["tier"] = pd.cut(df.minutes_with_stats, [-1, 0, 450, 1800, 10**7],
                        labels=["presence only", "thin", "fair", "solid"]).astype(str)
    df.loc[(df.minutes_with_stats == 0) & (df.minutes > 0), "tier"] = "minutes only"
    return df


def identity_checks(c) -> list[dict]:
    f = []
    yt = D / "lake" / "identity" / "matchdata_youth_tm.parquet"
    if yt.exists():
        n = c.execute(f"SELECT count(*) FROM '{yt.as_posix()}'").fetchone()[0]
        many = c.execute(f"SELECT count(*) FROM (SELECT tm_id FROM '{yt.as_posix()}' GROUP BY 1 HAVING count(DISTINCT matchdata_id) > 1)").fetchone()[0]
        weak = c.execute(f"SELECT count(*) FROM '{yt.as_posix()}' WHERE score < 90").fetchone()[0]
        f.append({"source": "identity matchdata→TM", "rule": "one TM player claimed by two MatchData ids", "kind": "HARD", "rows": many, "of": n,
                  "why": "a merge error: both links are held back until reviewed"})
        f.append({"source": "identity matchdata→TM", "rule": "name match below 90", "kind": "SOFT", "rows": weak, "of": n,
                  "why": "same birth date, weaker name match: kept, flagged for the review queue"})
    v2 = D / "identity_v2.parquet"
    if v2.exists():
        n = c.execute(f"SELECT count(*) FROM '{v2.as_posix()}'").fetchone()[0]
        for col in ("tm_id", "fl_id"):
            k = c.execute(f"SELECT count(*) FROM (SELECT {col} FROM '{v2.as_posix()}' WHERE {col} IS NOT NULL GROUP BY 1 HAVING count(DISTINCT ea_id) > 1)").fetchone()[0]
            f.append({"source": "identity EA/TM/FL", "rule": f"one {col} on two EA players", "kind": "HARD", "rows": k, "of": n,
                      "why": "a merge error: held back until reviewed"})
    return f


def source_readiness(c) -> list[dict]:
    """Is each source complete and fresh enough to be used at all?"""
    f = []
    careers = D / "matchdata_youth_careers.parquet"
    players = c.execute(f"SELECT count(DISTINCT player_id) FROM '{careers.as_posix()}'").fetchone()[0] if careers.exists() else 0
    done = players >= 0.95 * 9055       # the rest are ids MatchData no longer knows (it answers null)
    f.append({"source": "MatchData youth careers", "rule": "flattened table complete", "kind": "RESOLVED" if done else "READINESS",
              "rows": players, "of": 9055,
              "why": "crawl finished and flattened; the missing ids are unknown to MatchData" if done
              else "not ready: flattened when the crawl finishes; until then no model reads it"})
    tm = duckdb.connect(str(D / "transfermarkt-datasets.duckdb"), read_only=True)
    last = tm.execute("SELECT max(date) FROM player_valuations").fetchone()[0]
    f.append({"source": "Transfermarkt datasets", "rule": "freshness", "kind": "READINESS", "rows": 0, "of": 0,
              "why": f"last valuation {last}: values after that date come from the 2026 window crawl, never mixed silently"})
    # Knowledge time of an article: its publication date, else the sitemap's last-modified date. Last-modified can only
    # be later than publication, never earlier, so the fallback may make a claim count late but can never leak.
    corpus = D / "analysis_corpus.parquet"
    kt = q(c, f"""SELECT url, site, md5(text) AS text_hash,
                  CASE WHEN published IS NOT NULL AND published <> '' THEN TRY_CAST(substr(published, 1, 10) AS DATE)
                       WHEN lastmod IS NOT NULL AND lastmod <> '' THEN TRY_CAST(substr(lastmod, 1, 10) AS DATE) END AS knowledge_date,
                  CASE WHEN published IS NOT NULL AND published <> '' THEN 'published'
                       WHEN lastmod IS NOT NULL AND lastmod <> '' THEN 'last modified' ELSE 'none' END AS basis
                  FROM '{corpus.as_posix()}'""")
    kt["duplicate"] = kt.duplicated("text_hash", keep="first")
    kt.to_parquet(OUT / "corpus_knowledge_time.parquet")
    n = len(kt)
    f.append({"source": "analysis corpus", "rule": "dated by the sitemap's last-modified date", "kind": "SOFT",
              "rows": int((kt.basis == "last modified").sum()), "of": n,
              "why": "no publication date on the page; the last-modified date is used, which can only be later: a claim may count late, never early"})
    f.append({"source": "analysis corpus", "rule": "no date at all", "kind": "HARD", "rows": int(kt.knowledge_date.isna().sum()), "of": n,
              "why": "a claim that cannot be placed in time is excluded (it could leak the future)"})
    f.append({"source": "analysis corpus", "rule": "duplicate texts", "kind": "HARD", "rows": int(kt.duplicate.sum()), "of": n,
              "why": "the same article twice would count one writer's claim twice; the first copy is kept"})
    wiki = D / "lake" / "text" / "encyclopedia_asof.parquet"
    late_day = c.execute(f"SELECT count(*) FROM '{wiki.as_posix()}' WHERE exists AND CAST(timestamp AS DATE) > CAST(as_of AS DATE)").fetchone()[0]
    same_day = c.execute(f"""SELECT count(*) FROM '{wiki.as_posix()}' WHERE exists AND CAST(timestamp AS TIMESTAMP) > CAST(as_of AS TIMESTAMP)
                         AND CAST(timestamp AS DATE) = CAST(as_of AS DATE)""").fetchone()[0]
    total = c.execute(f"SELECT count(*) FROM '{wiki.as_posix()}'").fetchone()[0]
    f.append({"source": "an open encyclopedia as-of", "rule": "revision on a later day than its as-of date", "kind": "HARD", "rows": int(late_day),
              "of": total, "why": "a snapshot written after the date it stands for would leak the outcome"})
    f.append({"source": "an open encyclopedia as-of", "rule": "revision later on the same day", "kind": "SOFT", "rows": int(same_day), "of": total,
              "why": "same calendar day as the as-of date (at most 23 h): features use day precision, so it stays"})
    elo = D / "lake" / "strength" / "elo_matches.parquet"
    thin = c.execute(f"""SELECT count(*) FROM (SELECT t, count(*) g FROM (SELECT home_id t FROM '{elo.as_posix()}' UNION ALL
                       SELECT away_id FROM '{elo.as_posix()}') GROUP BY 1 HAVING g < 10)""").fetchone()[0]
    f.append({"source": "strength (Elo)", "rule": "team with fewer than 10 results", "kind": "SOFT", "rows": int(thin),
              "of": c.execute(f"SELECT count(*) FROM '{(D / 'lake' / 'strength' / 'team_ratings.parquet').as_posix()}'").fetchone()[0],
              "why": "its rating is mostly the prior: used with its uncertainty, never as a precise number"})
    return f


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    c = duckdb.connect()
    c.execute("SET memory_limit='4GB'")
    findings, quarantine = matchdata_checks(c)
    findings += identity_checks(c) + source_readiness(c)
    cov, suff = coverage(c), sufficiency(c)
    quarantine.to_parquet(OUT / "quarantine.parquet")
    suff.to_parquet(OUT / "sufficiency.parquet")
    cov.to_parquet(OUT / "coverage.parquet")
    tiers = suff.tier.value_counts().reindex(["solid", "fair", "thin", "minutes only", "presence only"]).fillna(0).astype(int)
    lines = [f"# Data integrity report ({TODAY})", "",
             "HARD = quarantined, never reaches a model. SOFT = kept and flagged. READINESS = source held back until ready.", "",
             "| Source | Rule | Kind | Rows | Of | What happens |", "|---|---|---|---|---|---|"]
    lines += [f"| {f['source']} | {f['rule']} | {f['kind']} | {f['rows']:,} | {f['of']:,} | {f['why']} |" for f in findings]
    lines += ["", "## Evidence per player (MatchData)", "", "| Tier | Players | Rule |", "|---|---|---|",
              f"| solid (1,800+ minutes with stats) | {tiers['solid']:,} | full projection, normal bands |",
              f"| fair (450-1,800) | {tiers['fair']:,} | projection with widened bands |",
              f"| thin (< 450) | {tiers['thin']:,} | bands widened further; the file says the evidence is thin |",
              f"| minutes only (lineups, no stats) | {tiers['minutes only']:,} | pathway and minutes only; no craft profile |",
              f"| presence only (named, no minutes) | {tiers['presence only']:,} | no projection: abstain |",
              "", "## Stat coverage by competition (top 30)", "", "| Competition | Matches | Stats share | From | To |", "|---|---|---|---|---|"]
    lines += [f"| {r.league} | {r.matches:,} | {r.stats_share:.0%} | {r.first_date} | {r.last_date} |" for r in cov.head(30).itertuples()]
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT / "findings.json").write_text(json.dumps(findings, indent=1, default=str), encoding="utf-8")
    print("\n".join(lines[:len(findings) + 6]))
    print("tiers:", tiers.to_dict(), "| quarantined rows:", len(quarantine))


if __name__ == "__main__":
    main()
