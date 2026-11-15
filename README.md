# Promesse 1.0

Promesse looks at young footballers (under 21) through what their actual on-pitch performance shows, and asks one question of each:
Can he be a regular in one of 31 first divisions within three seasons? It also draws a range for the minutes he would
play, reads how teams and coaches play, and shows where a player would fit in another system. It is tested on seasons it
never saw, always against a simple baseline, and in this file, I make sure to maintain honesty on the limitations found.

## What it does

| Part | The question | Public name |
|---|---|---|
| Engine | Will this under-21 become a regular in one of 31 first divisions within three seasons? | ProEngine |
| Projection | How many minutes will he play next season? Not one number but a range that holds 80 times in 100. | ProProjection |
| Tactical layer | How does a team play, does a coach carry his style from club to club, what is a player's role inside his team, what does he do beyond his system, how would he fit somewhere else? | (five parts: game models, coach fingerprints, roles, signature skills, system fit) |
| Development by system | Which systems grow young players fastest? | ProT6 (did not pass, see below) |
| Scout Desk | One page per player, each number with its source, a seat for every player in a stadium. | (the `scout/` folder) |

The file `NAMES.md` maps the public names to the source files, which keep the names of the version they were written as.

## How it is built

Each step reads only the published tables of the steps before it and writes its own, plus a report that a pass mark
(written before the result is computed) reads. `build.py` runs them in order:

    registry -> identity -> strength of each league -> careers -> targets -> game ratings -> spine (one row per player-season)
    -> extra inputs (youth caps, moves, youth tournaments) -> engine ladder -> projection -> scoring -> desk database

- `models/` the engine, its input rule (`inputs.py`), the ladder of baselines, the data dial, the projection and ProT6.
- `gold/` the tactical layer and the player-season table.
- `connect/` the data contract: the tables any source lands in (`contract.py`), the adapters, and the identity link that
  matches one player across multiple sources.
- `lake/` the scripts that clean and measure the raw tables. `scout/` the desk's server and web pages (without its data).


Three rules carry the method:
1. **Out-of-time tests only.** Models are fitted on early seasons, chosen on a validation season (2019-20), and judged once on unseen seasons (2021-22). That test is spent, therefore, it doesn't get used to tune anything again.
2. **Inputs are what happened** (minutes, level of the matches, age, moves, youth caps). Ratings and market values are
   benchmarks to compare against, never inputs (`models/inputs.py`).
3. **Point in time or nothing.** An input is allowed only if it could have been known on the day. One input failed this: transfer moves were kept mostly for players who stayed, which gave the answer away; they were taken out, and the engine, in its first training round, sat 3.9 right picks in 100 behind the market until more seasons of match data were added.

## Results, with their baselines

All figures: 2021-22 seasons the model never saw, players under 21 at the start. "AUC" is the share of pairs (one player who later became a regular, one who did not)
in which the model ranks the right one first: 50 in 100 is a coin toss, 100 is perfect, higher is better. The 95 % range
comes from resampling the players; if it includes zero, the difference is not counted as real.

- **ProEngine ranks 77.9 right pairs in 100.** Market value (Transfermarkt's, a benchmark never given to the engine) ranks
  77.5. The engine is just ahead; the gap, +0.4 in 100, has a 95 % range from -1.4 to +2.2, so it is level with the market
  on average, not a proven win. Its first version, ProEngine 0.1, scored 74.4; the gain, +3.6, is real (range +2.4 to +4.8).
  Calls cover 2,708 current under-21 players. (`results/ProEngine_test_2021-22.json`)
- **ProProjection's 80 % ranges hold 80.3 times in 100** on players it never saw (79.1 before calibration), which is what an honest 80 %
  range should show. By how much evidence a player has: 81.3, 80.9 and 79.4 in 100 for the first three of four groups. (`results/ProProjection.json`)
- **What the data adds** (the data dial): each group of inputs removed in turn, to see what the engine loses. (`results/ProEngine_data_dial.json`)
- **Tactical layer:** five of six tests passed (game models, coach fingerprints, roles, signature skills, system fit);
  the reports are in `results/Tactics_*.json`. **Player Combinations is a beta.**

### What did not pass
- **Development by system (ProT6):** the gain from adding the team's game model is +0.0038 in mean squared error of the prediction (lower is better; it is the same scale as the 6.90 baseline), the coach +0.0043; both 95 % ranges include zero (-0.066 to +0.076 and -0.043 to +0.052). Unknown, not shown as a finding.
- **ProProjection v2** (the next version, a sharper range, planned but not passed yet; I aim to find a solution in later months): its biggest evidence group held 77.0 % against the 80 % aimed for, so ProProjection stays.

## Data

Open sources, named with their terms, can be downloaded and used to rebuild part of the pipeline:
StatsBomb open data, the Transfermarkt datasets on Kaggle (davidcariboo/player-scores), Wyscout's public 2017/18 release,
SoccerMon, the DFL/IDSSE open Bundesliga sample, Impect's open data, SkillCorner's and Metrica's open samples. *(Each name
stays in this list only once its licence text has been checked: see `PUSH-PLAN.md`.)*

Credits the sources ask for:
- StatsBomb open data: data source StatsBomb. Its user agreement asks for the StatsBomb logo on any published analysis built on the data, and excludes commercial use.
- Wyscout's 2017/18 release: Pappalardo L, Massucco E. 2019. *Soccer match event dataset*. figshare, [doi 10.6084/m9.figshare.c.4415000.v2](https://doi.org/10.6084/m9.figshare.c.4415000.v2). CC BY 4.0; the data were collected by Wyscout.
- SoccerMon: Midoglu et al. 2022. *SoccerMon: A Large-Scale Multivariate Soccer Athlete Health, Performance, and Position Monitoring Dataset*. Zenodo, [doi 10.5281/zenodo.10033832](https://doi.org/10.5281/zenodo.10033832). CC BY 4.0.
- DFL/IDSSE: Bassek, Rein, Weber and Memmert. 2025. *An integrated dataset of spatiotemporal and event data in elite soccer*. Scientific Data, [doi 10.1038/s41597-025-04505-y](https://doi.org/10.1038/s41597-025-04505-y). Data owned by the DFL (Deutsche Fußball Liga), released under CC BY 4.0.
- Impect's open data: data provider Impect. Its terms exclude commercial use and ask for Impect to be credited on anything published from the data.
- SkillCorner open data: MIT licence, copyright SkillCorner; the data are credited to SkillCorner.
- Metrica Sports' sample data: the source is acknowledged (Metrica Sports).
Everything else the results rest on is **privately collected data**. It is not in this repository, and no table of players,
matches or ratings ever will be. Results that rest on it are stated as results of the engine.
The club-variables simulator (`models/club_variables.json`) is a **simulation**, labelled as one wherever it is used.

## Run it on your own data

1. Python 3.12, `pip install -r requirements.txt`.
2. Put your data under one folder and point `PROMESSE_DATA` at it (default `./data`; `promesse_config.py` is the only
   place a path lives). Your tables follow the contract in `connect/contract.py`: each source arrives through an adapter
   that writes the same keyed tables with `known_at` (when the row could first be known) and a licence on every row.
3. `python build.py` (or `--only <step>`, `--from <step>`). Each step prints its gate result.
4. `python scout/serve.py` starts the desk on port 8792.

## Ask for a run on our data

Rows are never handed out. If you are a club or a researcher, send a question (for example: "how would this profile read
across these leagues?"); Promesse is run on the data we hold, and the results come back to you. Contact: via the contact page of the author's site.

## Licence
MIT (see `LICENSE`). It covers the code and the documents in this repository; the data behind the results is not part of it.
