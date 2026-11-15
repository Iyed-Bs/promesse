"""Promesse: what the engine's call is made of ("show the values of the variables we decided determine
everything the player is and can become").

The engine is a penalised logistic regression on standardised inputs (models/ladder.py, Logit), so its call splits
exactly: in log-odds, the intercept (the average player of the training years) plus, for each input, its coefficient
times the player's standardised value (and, for an input with missing values, its coefficient times the missing flag).
Nothing here is an approximation of the model: it is the model, written out term by term.

Each input belongs to a group with a plain name; the desk shows the groups (Scout) and every input (Expert).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# input -> (group, what it is, in words)
INPUTS = {
    "age": ("Age and body", "age at the snapshot"),
    "birth_quarter": ("Age and body", "quarter of the year he was born in"),
    "height": ("Age and body", "height"),
    "left_foot": ("Age and body", "left-footed"),
    "pos_GK": ("Position", "goalkeeper"), "pos_DEF": ("Position", "defender"),
    "pos_MID": ("Position", "midfielder"), "pos_ATT": ("Position", "attacker"),
    "min_365": ("Minutes", "senior minutes, last 12 months"),
    "min_730": ("Minutes", "senior minutes, last 24 months"),
    "league_min_365": ("Minutes", "first-division league minutes, last 12 months"),
    "apps_365": ("Minutes", "senior appearances, last 12 months"),
    "fm_min_365": ("Minutes", "minutes in the detailed match data, last 12 months"),
    "fm_youth_min_365": ("Youth football", "youth-competition minutes, last 12 months"),
    "qmin_365": ("Quality of his football", "quality minutes (minutes x match level), last 12 months"),
    "qmin_730": ("Quality of his football", "quality minutes, last 24 months"),
    "europe_min_730": ("Quality of his football", "European minutes, last 24 months"),
    "last_club_level": ("Quality of his football", "level of his last club"),
    "last_level": ("Quality of his football", "level of his main club last season"),
    "best_level": ("Quality of his football", "best level where he held a place"),
    "level_step": ("Career shape", "step in level from the season before"),
    "last_share": ("His place in the team", "share of his team's minutes last season"),
    "best_share": ("His place in the team", "best share of his team's minutes so far"),
    "share_trend": ("His place in the team", "change in his share from the season before"),
    "qmin_cum": ("Career shape", "quality minutes so far"),
    "seasons_senior": ("Career shape", "seasons with first-division minutes"),
    "growth_q": ("Career shape", "growth in quality minutes from the season before"),
    "cohort_pct": ("Career shape", "rank among players born the same year (quality minutes so far)"),
    "age_first_app": ("Career shape", "age at his first senior appearance"),
    "yi_apps": ("Youth internationals", "youth international appearances"),
    "yi_top_level": ("Youth internationals", "oldest youth national team he was selected for"),
    "yi_selected": ("Youth internationals", "selected for a youth national team"),
    "senior_cap": ("Youth internationals", "selected for the senior national team"),
    "mv_moves_2y": ("Moves and loans", "club moves, last 24 months"),
    "mv_loans_done": ("Moves and loans", "completed loans"),
    "mv_days_since": ("Moves and loans", "days since his last move"),
    "mv_last_step": ("Moves and loans", "step in level of his last move"),
    "clubs_2y": ("Moves and loans", "clubs played for, last 24 months"),
}


def contributions(model, rows: pd.DataFrame) -> tuple[float, pd.DataFrame]:
    """(intercept, long table: row index, input, raw value, missing, log-odds contribution) for a fitted ladder.Logit."""
    X = model._x(rows)
    coef = model.m.coef_[0]
    names = list(model.cols) + [c + "_na" for c in model.flagged]
    contrib = X * coef
    raw = rows[model.cols].astype(float)
    out = []
    for j, name in enumerate(names):
        base = name[:-3] if name.endswith("_na") else name
        out.append(pd.DataFrame({"row": rows.index, "input": base, "term": name, "contribution": contrib[:, j],
                                 "value": raw[base].to_numpy(), "missing": raw[base].isna().to_numpy()}))
    long = pd.concat(out, ignore_index=True)
    long = long.groupby(["row", "input"], as_index=False).agg(contribution=("contribution", "sum"), value=("value", "first"),
                                                              missing=("missing", "first"))
    long["group"] = long.input.map(lambda c: INPUTS.get(c, ("Other", c))[0])
    long["label"] = long.input.map(lambda c: INPUTS.get(c, ("Other", c))[1])
    return float(model.m.intercept_[0]), long


def to_prob(logit: np.ndarray | float) -> np.ndarray | float:
    return 1 / (1 + np.exp(-np.asarray(logit)))
