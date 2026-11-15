"""What Promesse's engines may read.

The engines learn from what happened: minutes, the level of every match, age, position, moves. They never read what
others think of a player: EA and PES ratings, market value (and fees), MatchData's match rating. Those are the benchmarks,
scored on the same unseen seasons as the engines, so "Promesse read the player better than the industry" is never
circular. A model that adds them back is reported as an ablation only: what their opinions carry beyond our evidence.

M3's fused rating is anchored on EA's scale (m3_fusion.py), so it counts as a rater until it is re-anchored on ours.
"""
RATERS = ("mv_last", "mv_days", "mv_max", "mv_1y", "mv_growth",      # the market
          "ea_overall", "ea_potential", "ea_gap",                     # EA
          "pes_mean",                                                 # Konami
          "fm_rating_365")                                            # MatchData's match rating


# Inputs withdrawn because the way they are recorded depends on the future (models/audit_moves_asof.py).
# The moves (gold/moves.py) come from the open datasets' transfers table, which holds a player's transfer history
# only if he was active in its competitions when it was collected: 99 % of the 2023 snapshot's future regulars have
# a transfer on record against 23 % of the others, and 31 % against 8 % for 2014's. "No move on record" then means
# "not around later": the outcome itself. Dated before the snapshot, still not point in time.
LEAKY = ("mv_moves_2y", "mv_loans_done", "mv_days_since", "mv_last_step")
# Unverified, out until a point-in-time source replaces them: the youth national-team stints come from
# MatchData career pages crawled in 2026, which may list a player's youth caps more completely once he is known, and no
# archived copy exists to check (they added 0.005 AUC on T2: models/ablate_profile.py). Replaced by the youth finals'
# squads, fixed at the time (gold/youth_tournaments.py, yt_*).
UNVERIFIED = ("yi_apps", "yi_top_level", "yi_selected", "senior_cap")
# Profile fields whose value is kept but whose absence is silenced (models/audit_profile_asof.py): the
# open datasets fill in height and foot once a player is known. The 2023 snapshot's players who first became regulars
# in 2025/26 had a height on record in January 2025 as often as those who never made it (53.5 % against 55.4 %);
# today 99 % against 90.5 %. "Missing" was worth 0.021 AUC on T2: the outcome, recorded late. Filled with the median
# (height) or the common case (right foot), and no missing flag.
SILENT = {"height": "median", "left_foot": 0.0}


def is_rater(col: str) -> bool:
    return col.removesuffix("_na") in RATERS or col.startswith("m3_")


def is_leaky(col: str) -> bool:
    return col.removesuffix("_na") in LEAKY + UNVERIFIED


def silence(d):
    """Fill the SILENT profile fields so that their absence carries nothing (no flag, no NaN for a tree to split on)."""
    for c, how in SILENT.items():
        if c in d.columns:
            d[c] = d[c].fillna(d[c].median() if how == "median" else how)
    return d
