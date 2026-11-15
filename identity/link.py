"""Identity v3, steps 2-4: score every plausible pair of records across families, cluster them into persons, keep the
doubtful pairs for review.

  records.parquet (records.py)  ->  Splink (Fellegi-Sunter, weights fitted by EM, DuckDB)  ->  pairs.parquet
                                ->  constrained clustering                                ->  clusters.parquet
                                ->  the uncertain band                                    ->  review.parquet

Comparisons (each a ladder of levels; EM learns how much each level says "same person" against "chance"):
  name     exact (either name or alias) > very close > two shared tokens > close > surname inside the other > one token
  birth    same exact date > windows overlap > within a year
  clubs    two shared club-seasons > one > two clubs in common > one
  nation, height (2 cm / 5 cm), foot, position group
Blocking (which pairs get compared at all): same estimated birth year and surname start; same full name; same surname,
nation and initial; same exact birth date; a shared club-season with the same surname initial.

Clustering keeps one record per family per person: pairs are taken strongest first and two groups merge only if no
family would appear twice (a person has one EA id, one Transfermarkt id...). Accepted at match probability >= ACCEPT;
pairs between REVIEW and ACCEPT that weren't merged go to the review queue with their evidence.

    python link.py               (identity venv)
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
from promesse_config import DATA_ROOT  # the one config file
from pathlib import Path

import duckdb
import pandas as pd
from splink import Linker, SettingsCreator, block_on
from splink.backends.duckdb import DuckDBAPI

D = Path((DATA_ROOT + "/lake/identity"))
ACCEPT, REVIEW = 0.95, 0.50


def L(sql: str, label: str, null: bool = False) -> dict:
    d = {"sql_condition": sql, "label_for_charts": label}
    if null:
        d["is_null_level"] = True
    return d


NAME = {"output_column_name": "name", "comparison_levels": [
    L("name_n_l = '' or name_n_r = ''", "null", True),
    # An alias counts as exact only when it has two words or more: a one-word alias (a shirt name such as RIQUELME,
    # a single Brazilian name) is just a surname, and the gate found it linking two different Riquelmes.
    L("name_n_l = name_n_r or (alt_n_r like '% %' and name_n_l = alt_n_r) or (alt_n_l like '% %' and alt_n_l = name_n_r)"
      " or (alt_n_l like '% %' and alt_n_l = alt_n_r)", "exact or alias"),
    L("jaro_winkler_similarity(name_n_l, name_n_r) >= 0.95", "JW >= 0.95"),
    L("len(list_intersect(name_tokens_l, name_tokens_r)) >= 2", "two tokens shared"),
    L("jaro_winkler_similarity(name_n_l, name_n_r) >= 0.88 or jaro_winkler_similarity(last_tok_l, last_tok_r) >= 0.93",
      "close"),
    L("list_contains(name_tokens_r, last_tok_l) or list_contains(name_tokens_l, last_tok_r)"
      " or (alt_n_r <> '' and name_n_l = alt_n_r) or (alt_n_l <> '' and alt_n_l = name_n_r) or (alt_n_l <> '' and alt_n_l = alt_n_r)",
      "surname in the other, or a one-word alias"),
    L("len(list_intersect(name_tokens_l, name_tokens_r)) = 1", "one token shared"),
    L("ELSE", "different")]}

BIRTH = {"output_column_name": "birth", "comparison_levels": [
    L("dob_lo_l is null or dob_lo_r is null", "null", True),
    L("dob_lo_l = dob_hi_l and dob_lo_r = dob_hi_r and dob_lo_l = dob_lo_r", "same date"),
    # (a "two narrow windows overlap" level sat here; once MatchData's profiles gave 98.5 % of its records an
    # exact date, two narrow windows almost never met, EM couldn't train the level and Splink fell back on defaults)
    L("dob_lo_l <= dob_hi_r and dob_lo_r <= dob_hi_l", "windows overlap"),
    L("abs(birth_year_est_l - birth_year_est_r) <= 1", "within a year"),
    L("ELSE", "different")]}

CLUBS = {"output_column_name": "clubs", "comparison_levels": [
    L("len(clubs_l) = 0 or len(clubs_r) = 0", "null", True),
    L("len(list_intersect(club_seasons_l, club_seasons_r)) >= 2", "two club-seasons"),
    L("len(list_intersect(club_seasons_l, club_seasons_r)) = 1", "one club-season"),
    L("len(list_intersect(clubs_l, clubs_r)) >= 2", "two clubs"),
    L("len(list_intersect(clubs_l, clubs_r)) = 1", "one club"),
    L("ELSE", "none in common")]}


def simple(col: str, levels: list[tuple[str, str]]) -> dict:
    return {"output_column_name": col, "comparison_levels": [
        L(f"{col}_l is null or {col}_r is null or cast({col}_l as varchar) = '' or cast({col}_r as varchar) = ''",
          "null", True), *[L(s, lab) for s, lab in levels], L("ELSE", "different")]}


NATION = simple("nation", [("nation_l = nation_r", "same")])
HEIGHT = simple("height", [("abs(height_l - height_r) <= 2", "2 cm"), ("abs(height_l - height_r) <= 5", "5 cm")])
FOOT = simple("foot", [("foot_l = foot_r", "same")])
POS = simple("pos_group", [("pos_group_l = pos_group_r", "same")])
# Earlier, validated links (identity v2: EA, Transfermarkt, privately collected game ratings, with its ratings-consistency test; the
# EA-MatchData and MatchData youth-Transfermarkt tables). Each linked set shares a key, so this is one more witness, weighed by
# EM like the others; it matters most for Konami records, which carry no birth date or nation.
PRIOR = {"output_column_name": "prior", "comparison_levels": [
    L("len(prior_keys_l) = 0 or len(prior_keys_r) = 0", "null", True),
    L("len(list_intersect(prior_keys_l, prior_keys_r)) >= 1", "linked before"),
    L("ELSE", "not linked before")]}

BLOCKS = [
    block_on("birth_year_est", "substr(last_tok, 1, 3)"),
    block_on("name_n"),
    block_on("last_tok", "nation", "substr(name_n, 1, 1)"),
    block_on("dob_lo", "dob_hi"),
    block_on("club_seasons", "substr(last_tok, 1, 1)", arrays_to_explode=["club_seasons"]),
    block_on("prior_keys", arrays_to_explode=["prior_keys"]),
]


def prior_keys(uids: pd.Series) -> pd.Series:
    """uid -> the keys of every earlier link set it belongs to ("v2:<row>", "fm:<row>", "fy:<row>")."""
    F = Path(DATA_ROOT)
    keys: dict[str, list[str]] = {}
    def add(fam: str, ids, tag: str) -> None:
        for i, v in zip(ids.index, ids):
            if pd.notna(v):
                keys.setdefault(f"{fam}:{int(v)}", []).append(f"{tag}:{i}")
    v2 = pd.read_parquet(F / "identity_v2.parquet")
    v2 = v2[v2[["ea_id", "tm_id", "fl_id"]].notna().sum(axis=1) >= 2]
    add("ea", v2["ea_id"], "v2"); add("tm", v2["tm_id"], "v2"); add("konami", v2["fl_id"], "v2")
    fm = pd.read_parquet(F / "matchdata_links.parquet").reset_index(drop=True)
    add("ea", fm["ea_id"], "fm"); add("matchdata", pd.to_numeric(fm["matchdata_id"], errors="coerce"), "fm")
    fy = pd.read_parquet(F / "lake/identity/matchdata_youth_tm.parquet").reset_index(drop=True)
    add("matchdata", pd.to_numeric(fy["matchdata_id"], errors="coerce"), "fy"); add("tm", fy["tm_id"], "fy")
    return uids.map(lambda u: keys.get(u, []))


def load() -> pd.DataFrame:
    r = pd.read_parquet(D / "records.parquet")
    for c in ("dob", "dob_lo", "dob_hi"):
        r[c] = pd.to_datetime(r[c], errors="coerce")
    r["birth_year_est"] = r["birth_year_est"].astype("float")
    r["height"] = r["height"].astype("float")
    for c in ("name_tokens", "club_seasons", "clubs"):
        r[c] = r[c].map(lambda x: list(x) if x is not None else [])
    r["prior_keys"] = prior_keys(r["uid"])
    return r.rename(columns={"uid": "unique_id"})


def first_names_clash(pairs: pd.DataFrame) -> pd.Series:
    """True where the two names agree only on the surname (gamma_name 2-3) and their first names clearly differ: both
    names have two words or more; first names that are neither prefixes of each other (Oli, Oliver) nor an initial of
    the other (S., Sven) nor close (Jaro-Winkler 0.85). One-word names (Neymar, Fernando) never clash."""
    import codecs
    import re
    import unicodedata

    from rapidfuzz.distance import JaroWinkler

    def toks(s) -> list[str]:
        s = str(s or "")
        if "\\u" in s:                                            # Wyscout's names come with literal escapes (Joël)
            try:
                s = codecs.decode(s, "unicode_escape")
            except Exception:
                pass
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
        return [t for t in re.split(r"[^a-z]+", s) if t]

    def clash(a, b) -> bool:
        ta, tb = toks(a), toks(b)
        if len(ta) < 2 or len(tb) < 2:
            return False
        fa, fb = ta[0], tb[0]
        if len(fa) == 1 or len(fb) == 1:
            return fa[0] != fb[0]
        if fa.startswith(fb) or fb.startswith(fa):
            return False
        return JaroWinkler.similarity(fa, fb) < 0.85

    weak = pairs["gamma_name"] <= 3
    return pd.Series([w and clash(a, b) for w, a, b in zip(weak, pairs["name_l"], pairs["name_r"])], index=pairs.index)


def cluster(pairs: pd.DataFrame, fam: dict[str, str]) -> dict[str, str]:
    """Strongest pairs first; merge two groups only if no family would appear twice. Returns uid -> group root."""
    parent: dict[str, str] = {}
    fams: dict[str, set] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs[["unique_id_l", "unique_id_r"]].itertuples(index=False):
        ra, rb = find(a), find(b)
        if ra == rb:
            continue
        fa, fb = fams.get(ra, {fam[a]}), fams.get(rb, {fam[b]})
        if fa & fb:                                   # the same family twice: refuse, the pair goes to review
            continue
        parent[rb] = ra
        fams[ra] = fa | fb
    return {u: find(u) for u in list(parent)}


def main() -> None:
    recs = load()
    fam = dict(zip(recs["unique_id"], recs["family"]))
    db = DuckDBAPI()
    tables = [db.register(g.drop(columns=["family"]).reset_index(drop=True), dataset_display_name=f)
              for f, g in recs.groupby("family")]
    settings = SettingsCreator(link_type="link_only", unique_id_column_name="unique_id",
                               comparisons=[NAME, BIRTH, CLUBS, NATION, HEIGHT, FOOT, POS, PRIOR],
                               blocking_rules_to_generate_predictions=BLOCKS,
                               retain_intermediate_calculation_columns=False,
                               additional_columns_to_retain=["name", "dob", "nation", "club_seasons"])
    linker = Linker(tables, settings)
    linker.training.estimate_probability_two_random_records_match(
        [block_on("name_n", "dob_lo", "dob_hi")], recall=0.6)
    linker.training.estimate_u_using_random_sampling(max_pairs=5e6)
    linker.training.estimate_parameters_using_expectation_maximisation(block_on("dob_lo", "dob_hi"))
    linker.training.estimate_parameters_using_expectation_maximisation(block_on("name_n"))
    linker.misc.save_model_to_json(str(D / "model.json"), overwrite=True)

    pred = linker.inference.predict(threshold_match_probability=0.05).as_pandas_dataframe()
    # Strongest first, ties broken by the uids, so the same inputs always give the same groups (stable ids, D2).
    pred = pred.sort_values(["match_probability", "unique_id_l", "unique_id_r"], ascending=[False, True, True],
                            kind="mergesort").reset_index(drop=True)
    pred.to_parquet(D / "pairs.parquet")
    print(f"scored pairs (p >= 0.05): {len(pred):,}; >= {ACCEPT}: {(pred.match_probability >= ACCEPT).sum():,}; "
          f"{REVIEW}-{ACCEPT}: {pred.match_probability.between(REVIEW, ACCEPT).sum():,}", flush=True)

    # Names must agree at least on the surname (gamma_name >= 2), whatever the other evidence or an earlier link says:
    # the gate found an old link joining two players who shared only a first name and a birth date.
    named = pred["gamma_name"] >= 2
    print(f"held back for a weak name: {int(((pred.match_probability >= ACCEPT) & ~named).sum()):,} pairs", flush=True)
    # First names (found by the Reep audit: Sven and Lars Bender came out swapped): a pair that agrees only on
    # the surname while the first names clearly differ is clustered last, after every other accepted pair, so a brother
    # with the exact name claims the record first and the clash goes to review. Checked before shipping
    # (names_first_check.py): 37 records in 14 groups move, all of them brothers separated (the Benders, the Flaños,
    # the Shitovs, the Mouaddibs...), no one-name player (Neymar, Fernando) affected.
    acc = pred[(pred.match_probability >= ACCEPT) & named]
    clash = first_names_clash(acc)
    print(f"first names clash: {int(clash.sum()):,} accepted pairs clustered last", flush=True)
    roots = cluster(pd.concat([acc[~clash], acc[clash]]), fam)
    cl = pd.DataFrame({"unique_id": recs["unique_id"]})
    cl["group"] = cl["unique_id"].map(roots).fillna(cl["unique_id"])
    cl["family"] = cl["unique_id"].map(fam)
    cl.to_parquet(D / "clusters.parquet")
    g = cl.groupby("group")["family"].nunique()
    print(f"persons: {cl['group'].nunique():,} from {len(cl):,} records; multi-source persons {int((g > 1).sum()):,}; "
          f"by size {g.value_counts().sort_index().to_dict()}", flush=True)

    # Review: every pair from REVIEW up that didn't end in one person (the uncertain band, the weak names held back,
    # and strong pairs refused because their family was already taken in the group).
    band = pred[pred.match_probability >= REVIEW].copy()
    band["same_group"] = band["unique_id_l"].map(cl.set_index("unique_id")["group"]).values == \
        band["unique_id_r"].map(cl.set_index("unique_id")["group"]).values
    band[~band["same_group"]].to_parquet(D / "review.parquet")
    print(f"review queue: {int((~band['same_group']).sum()):,} pairs", flush=True)


if __name__ == "__main__":
    main()
