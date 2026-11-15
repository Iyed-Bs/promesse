# Research

I'm a football fan before anything else, and every part of Promesse started with something I wanted to know while watching
young players come through. This is the reading I did to answer those questions: what the papers say, what I tried myself,
and what I took from it. Under each section I left the few links that carried the conclusion. A claim that I couldn't
check against a primary source isn't here.

A few terms, so nothing below is a riddle:
- **Right picks in 100.** Take pairs of young players, one who later became a regular and one who didn't, and ask the model
  who it picks. 50 in 100 is a coin flip, 100 is perfect, higher is better. (Researchers call it AUC.)
- **95 % range.** The range the true value falls in 95 times out of 100, worked out by resampling the players. If it includes
  zero, I don't count the difference as real.
- **Pass mark.** A bar I wrote down before computing a result, so I couldn't move it afterwards. A reading goes on the page
  only if it clears its bar.
- **Odd/even test.** Split a season's matches into the odd-numbered and even-numbered ones, measure the same thing on each
  half, and see whether the two halves agree (a correlation between 0 and 1, higher is better). If a reading is real, they do.
- **Regular.** A player who plays at least half of his team's league minutes in a season, in one of the 31 first divisions I follow.

## Can I trust a number before I put it on a page?

I started from a doubt: a lot of football numbers look precise and change completely from one month to the next. Franks and
his co-authors have a name for the checks that matter. A metric should be *stable* (it measures the same thing over time),
it should *discriminate* (it separates players) and it should be *independent* (it adds something the others don't). They
show it on basketball and ice-hockey statistics.

What I took: every reading in Promesse has to pass the odd/even test before it appears, with the bar fixed in advance. The
second check, discrimination, I don't run yet. A reading can repeat perfectly just because everyone sits near the average,
and the odd/even test can't see that. It's the next thing I want to add.

- [Franks, D'Amour, Cervone and Bornn, "Meta-Analytics: Tools for Understanding the Statistical Properties of Sports Metrics" (arXiv)](https://www.arxiv.org/pdf/1609.09830)

## What does "a role" mean for a footballer?

A winger who tucks inside and a winger who stays wide are both "wingers" in a team sheet. Aalbers and Van Haaren built 21
roles from sports media and Football Manager, refined them with SciSports' analysts, and defined each by what shows up in
match events (Wyscout data from seven European leagues). Their framing is the recruiter's one: would this player fit
how this team plays?

What I did: 22 roles, each written as a weighted mix of what a player does per 90 minutes and his share of his team's
actions. Each role went through the odd/even test. 21 of 22 passed, with agreement between 0.62 and 0.92. The one that
failed is the goalkeeper's shot-stopping at 0.19: over a season it either depends on other data I couldn't notice, or it's just bad luck, so I hide it. The same recruiter's question
is behind the fit model ("who fits Flick's Barça?"), which I tested on 1,080 moves between clubs it had never seen. Its
average error was 0.650 against 0.974 for "he plays the same as before" (lower is better). Most of that gain is players
drifting back to their usual level, and the part that comes from the new team's game model is small: 0.039, with a 95 % range
of 0.027 to 0.050.

- [Aalbers and Van Haaren, "Distinguishing Between Roles of Football Players in Play-by-play Match Event Data" (arXiv)](https://arxiv.org/pdf/1809.05173)

## Can a team's style be put in numbers?

Fernandez-Navarro and colleagues looked at 97 matches of LaLiga and the Premier League and found six factors and twelve
styles of play, with direct play and possession play on the strongest factor. I recognised it straight away: every fan
splits teams on that axis.

In Promesse the same axis is the strongest one: I measure eleven things about how a team plays (possession, going long, width,
winning the ball back and so on) and each one passed the odd/even test. My attempt to sort teams into five game-model
families is weaker, so the desk shows the eleven numbers and treats a family's name as a label, nothing more.

- [Fernandez-Navarro, Fradua, Zubillaga, Ford and McRobert, "Attacking and defensive styles of play in soccer" (author manuscript)](https://researchonline.ljmu.ac.uk/id/eprint/3791/)

## Does a coach really bring his style with him?

Everyone says "he'll bring his ideas". Muehlheusser and co-authors study German coach sackings and find that a change helps
results only in fairly even teams, and they warn that studies of coach changes usually carry a selection bias: clubs
choose the coach they want.

My question was different, style rather than results. Across 220 coach moves, a new club's style moves toward the coach's
previous club on 8 of my 11 readings. Three (width, dribbling, how often a team reaches the box) come with the players. The
warning applies to my result too, because part of the "carry" can be the club hiring the style it wants. A test that
separates the two would need sackings forced by results, and I don't have enough of them to say.

- [Muehlheusser, Schneemann and Sliwka, "The Impact of Managerial Change on Performance: The Role of Team Heterogeneity", Economic Inquiry (RePEc)](https://ideas.repec.org/a/bla/ecinqu/v54y2016i2p1128-1149.html)

## When do players peak, and does the month of birth matter?

Dendir used WhoScored ratings for Europe's top four leagues and found the average player peaking between 25 and 27:
forwards around 25, defenders around 27. That tells me where the curve I'm projecting should flatten.

The relative age effect is the other classic. Across ten countries, players born early in the selection year are
over-represented in youth national teams from under-15 to under-18. So I checked it on my own players, since birth quarter is
an input of the engine: one row per player the first time he appears aged 17 to 18, from the training seasons
only. The skew is mild there, which makes sense, since these players
are already in senior squads and past the selection the paper measured. Late-born players become regulars within three
seasons slightly more often, but the 95 % ranges overlap. Too weak to
build an interaction on, so birth quarter stays a plain input.

- [Dendir, "When do soccer players peak? A note", Journal of Sports Analytics (catalogue record)](https://lida.sport-iat.de/dfb/Record/4045076?lng=en)
- ["The relative age effect in youth soccer across Europe", Journal of Sports Sciences (catalogue record)](https://lida.sport-iat.de/dfb/Record/4010495?lng=en)

## How hard is the market to beat?

This is the question I care about most. Transfermarkt's values come from a crowd, and Peeters showed that forecasts built on
them beat the FIFA ranking and Elo ratings for international matches. Müller, Simons and Weinmann went the other way and
estimated values from player data for 4,217 players of the big five leagues, getting about as close as the crowd. So the
crowd is strong, and that's why market value is the benchmark Promesse has to beat, never an input.

Where I can still compete is the question. Market value prices a player overall; I only ask whether a young player becomes a
regular within three seasons. On unseen seasons (2021-22) the engine gets 77.9 right picks in 100 and market value 77.5.
The gap, +0.4, has a 95 % range from -1.4 to +2.2, so on average the engine is just ahead and level with the market in
what I can prove.

Team strength is the other piece. Hvattum and Arntzen use Elo ratings (a rating that rises with wins and falls with losses)
to predict results, and I use one to weigh minutes by the level of the match. The first version drifted: the Danish
Superliga's median team rated above the Bundesliga's, because leagues that rarely meet inflate. I fixed it by giving each
league a level moved by the games between leagues, and on league-to-league test games the Brier score fell from 0.176 to
0.165 (the average squared gap between a predicted chance and what happened, 0 or 1; lower is better; 95 % range of the
gain 0.007 to 0.015).

- [Peeters, "Testing the Wisdom of Crowds in the field", International Journal of Forecasting (RePEc)](https://ideas.repec.org/a/eee/intfor/v34y2018i1p17-29.html)
- [Müller, Simons and Weinmann, "Beyond crowd judgments" (open access)](https://repub.eur.nl/pub/120757)
- [Hvattum and Arntzen, "Using ELO ratings for match result prediction in association football" (record)](https://www.bibsonomy.org/bibtex/a0ef8f0c642f671fd027607d2b69ac6a)
- [Transfermarkt datasets on Kaggle (player-scores), the open data I check the engine's inputs against](https://www.kaggle.com/datasets/davidcariboo/player-scores)

## What do other people know about which young players make it?

Kelly and colleagues used 53 factors from eight kinds of data on 18 under-18 players at one English academy, to predict who
earned a professional contract. Höner and colleagues followed 13,869 players of Germany's talent programme from under-12
to under-15 and looked at who reached a professional academy three seasons later (about 9 %). In their combined model, the
coach's rating of tactical skill had an odds ratio of 2.09 per standard deviation at under-15, then dribbling 1.53 and sprint
1.36, and the combined models explain 15 to 20 % of the variance.

These studies are deep and narrow: one academy, one country, an intermediate milestone. I went the other way, wide and
shallow: 50,149 players in the open Transfermarkt datasets, on public data, with a senior career as the outcome. They
complement each other. What a club measures (growth, maturation, training) is what the data dial in the desk lists as the
first thing a club's own data would add. The odds ratios above are the starting effects of the club-variables simulator,
carried over to a different outcome and labelled as a simulation wherever it appears.

- [Höner, Murr, Larkin, Schreiner and Leyhr, Frontiers in Sports and Active Living (2021)](https://www.frontiersin.org/journals/sports-and-active-living/articles/10.3389/fspor.2021.638227/full)
- [Kelly et al., "A Multidisciplinary Investigation into the Talent Development Processes at an English Football Academy", Sports (2022)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9611883/)

## Can single actions be valued?

Decroos and colleagues value every action on the ball by how it changes the chance of scoring and of conceding over the next
few actions (they call it VAEP). I'd love to use it. Promesse only reads totals per match for 31 leagues, though, so it can't
value one pass. With event data (the open ones for the leagues they cover, or a club's own), I could improve two
things I now measure crudely: vision, meaning the value of the passes a player chooses and not only their count, and
composure, meaning what a lost ball costs. That's a line on the data dial: what a club's data would add.

- [Decroos, Bransen, Van Haaren and Davis, "Actions speak louder than goals: Valuing player actions in soccer", KU Leuven project page](https://dtai.cs.kuleuven.be/sports/vaep)
