# DEVLOG

My log on the way to the version I'm publishing. I write it as I go, questions included, aaand some dead ends ig?

## Where it started
The Tactical Patcher left me with one question. If real careers can balance a game's ratings, can they also tell who
actually comes through? So: take every under-21 in 31 first divisions, look at his minutes and the level of the matches he
played, and ask whether he is a regular three seasons later. (A regular here means he plays at least half of his team's league minutes in a season.)

## Stage 1, the first engine: what should I compare it with?
A model that scores well against nothing means nothing. So the ladder came before the model: a base rate (everyone gets the
same chance), then market value, then game ratings, then my model. Market value is the hard one, because it's what the whole
trade thinks. Rule I wrote down early: ratings and values are never inputs, only things to beat or match.

I also fixed how I'd judge it. Models are fitted on early seasons, chosen on a validation season (2019-20), and judged once
on seasons they never saw (2021-22). Once that last test is read, it's spent.

## Stage 2, Leak
The transfer moves looked like a strong input, and that was the problem. An archived copy of the open transfer data showed
that moves were kept mostly for players who stayed in the game later, so a move on record gave the answer away.
Question: how do I know the model isn't reading the future? Answer: I took the moves out and checked every input against
what was known at the time. On clean inputs the engine sat 3.9 right picks in 100 behind the market (50 is a coin flip, 100 is
perfect). That was the first honest number, and I think it's worth more than a better-looking one.

This loophole gave me a habit. Any new input now gets two checks before the engine sees it: does the fact that it's missing
tell the model something, and does an old copy of the data say the same thing as the new one. (Mirror image)

## Stage 3, what each kind of data is worth?
The data dial: take one group of inputs away at a time and see what the engine loses. What it showed is that what helps
depends on how much a player has played. For someone with a full season, level and role carry it. For someone with no senior
minutes, age, position and youth finals do. That led to evidence tiers, and to a projection that says what data would move a
player up instead of a number it can't back.

## Stage 4, the projection: a range that holds
A projection of minutes is a guess; a range is a promise (Promesse, practically the idea influenced by the original Tactical Patcher for Master League). So I tested the promise: do 80 % ranges contain the real minutes 80
times in 100? My first design for the test failed even for the plain version, because one calibration year four years before
the test season can't keep every group of players inside 77 to 83. That was my design's fault, not the model's, so I rebuilt
the test with more calibration years and ran it again. After calibration the plain version holds 80.3 in 100 on seasons it
never saw (79.1 before).

Then I tried a sharper version, with narrower ranges. It was a tidy idea and it didn't work: in the group of players with the
most evidence it held 77.0 against the 80 I aimed for. A sharper model that breaks its own promise is worse than a plain one
that keeps it, so the plain version stays and the sharper one is written up as not passed.

## Stage 5, the tests that failed
Which systems grow young players fastest? This is the question I most wanted to answer, and the answer so far is no.

First attempt: I added the team's game model to a prediction of how much a young player plays next season. It made the
prediction slightly worse, and so did the coach. Maybe I just had too few players (1,387). So I rebuilt it on 2.3 times as many,
with three more seasons and a game model measured for ten styles of play.

Along the way I caught a mistake of mine. For players who stay at a club, I compared my model with "no change". But players
who stay after a good year drift back toward their usual level, so "no change" was an easy bar and my model looked good against
it for the wrong reason. I changed the bar to the training years' average change before looking at any test season, which makes
the test harder and not easier.

Result on the final test: the game model adds +0.0038 and the coach +0.0043 to the prediction's accuracy, on a baseline error of
6.90 (squared error on the log of minutes; lower is better), and both 95 % ranges include zero (-0.066 to +0.076 and -0.043 to
+0.052). The desk says "unknown", and I think that line is the most useful one on the page: how much a young player plays next
season is explained by what he already is, with the public data I have.

## Stage 6, reading the game, not only the player
How does a team play, does a coach carry his style from club to club, what does a player do inside his team and beyond his
system, how would he fit elsewhere? Five tests passed. The sixth is the one above. Each reading went through the same pass
mark: split a season into odd and even matches and see whether the two halves agree. Pressing, chance quality, set pieces and
counter-attacks didn't, so they're off the page.

## Stage 7, eight more seasons
Adding match line-ups back to 2013/14 and per-player stats from 2016/17 (privately collected data), each read against its own
league, moved the engine from 74.4 to 77.9 right picks in 100. Market value gets 77.5. Is that "beating the market"? No:
the gap is +0.4 and its 95 % range runs from -1.4 to +2.2. Level with the market, just ahead on average. I wrote it that way
everywhere, including the pass mark I had set first ("ahead of market value"), which the engine didn't meet.

## Stage 8, Promesse 1.0
Every model output in one folder, each file with its fingerprint and what it measures. A later change means a new release (PaaP: Promesse as a Product. lol). The club deep dives (Barcelona first) are built on that release.


## What's next
The 2024 cohort is the next clean judge, after the 2026/27 season: every earlier test season is spent. And I'd like to run
Promesse on a club's own data through the contract the repository ships, to see what that data adds to what public records can read.
