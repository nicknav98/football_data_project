# Statistical method

What each number is meant to measure, what it means, and how per-90 figures,
percentiles and role scores are calculated.

There is no predictive model. Every figure is one of four things: a season
rate, a possession-adjusted rate, a percentile within a position, or a role
score built from fixed weights. The source is Sportmonks player statistics for
each match in five European leagues.

## What each indicator targets

| Indicator | What it targets | How to read it |
| --- | --- | --- |
| Tackles per 90, adjusted | How often he goes to win the ball off an opponent | Adjusted for possession, so it compares across teams that defend more or less |
| Interceptions per 90, adjusted | Reading play and cutting out passes | Same adjustment as tackles |
| Ball recoveries per 90 | Picking up loose balls | Not adjusted. Higher on teams without the ball. |
| Duels won % | Success in contests for the ball | A rate of success, not of activity. Check the number of duels behind it. |
| Aerials won % | Success in the air | Meaningful mainly for centre backs and strikers |
| Clearances per 90 | Defending the box | Not adjusted. High on teams under pressure. |
| Pass accuracy % | Keeping the ball | Says nothing about how hard the passes were |
| Passes per 90 | Involvement in build-up | Depends heavily on the team's style |
| Final-third passes per 90 | Moving the ball forward | A count of passes into the final third, whether or not they led to anything |
| Key passes per 90 | Creating shots | Sportmonks defines a key pass as a pass leading to a shot |
| Big chances created per 90 | Creating clear scoring chances | "Big chance" is the provider's judgement of each chance |
| Assists per 90 | Passes that led to goals | Depends on the finisher. Noisy over one season. |
| Goals per 90 | Scoring | Includes penalties. `non_penalty_goals_per_90` is also stored. |
| Shots per 90 | Getting into shooting positions | Says nothing about the quality of the chances |
| Shots on target % | Accuracy of shooting | Not a measure of finishing: there is no expected goals |
| Dribble success % | Beating a man | Check the number of attempts behind it |
| Touches per 90 | Overall involvement | Context for the other rates |
| Saves per 90 | Goalkeeper workload | Higher behind a weak defence |
| Rating | Sportmonks' own 0 to 10 match rating, averaged | The provider's formula, not ours |
| Average team possession % | How much of the ball his team had while he played | Context for every defensive count. 50 is an even share. |

Only key passes has a definition in the provider reference this project uses
(the Sportmonks statistic types in football-docs). The others are Sportmonks'
counts, described here by their usual meaning. Every collected statistic is
listed in [Statistics](statistics.md).

## How a per-90 figure is calculated

| Kind | Formula |
| --- | --- |
| Per 90 | 90 × season total ÷ minutes played |
| Percentage | 100 × successes ÷ attempts |
| Possession-adjusted per 90 | In each match, count × 50 ÷ opponent's possession %. Sum the matches, then 90 × that sum ÷ minutes. |

Minutes and attempts are counted only in matches where Sportmonks reported the
statistic.

James Garner, Premier League 2025/26, 3,414 minutes, figures as loaded on
2026-10-07:

| Figure | Calculation | Result |
| --- | --- | --- |
| Tackles per 90 | 90 × 121 tackles ÷ 3,414 | 3.19 |
| Tackles per 90, adjusted | 90 × 111.6 adjusted tackles ÷ 3,414 | 2.94 |
| Ball recoveries per 90 | 90 × 185 ÷ 3,414 | 4.88 |
| Passes per 90 | 90 × 1,793 ÷ 3,414 | 47.27 |
| Duels won % | 100 × 209 ÷ 341 | 61.3% |

The adjustment lowers his tackles because Everton averaged 43.6% possession.
Their opponents had the ball more than half the time, so each match's tackles
are scaled down. A match against an opponent with 60% of the ball counts each
tackle as 50 ÷ 60 = 0.83 of a tackle; against an opponent with 40%, as 1.25.

## What a percentile means

A percentile is the share of a comparison group the player is above on one
indicator, with a tie counted as half. Higher is always better.

| Part | Rule |
| --- | --- |
| Comparison group | Same detailed position (such as Defensive Midfield), same season, all five leagues together |
| Minutes to be in the group | A third of the most minutes anyone played that season: 1,140 for a full season |
| Percentages | Ranked only with at least 100 passes, 20 duels, 20 aerial duels or 10 dribbles; rating with at least 5 rated matches |
| Small samples | A season is flagged below that minutes floor, or below 900 minutes when the floor is lower, as early in a season |

| Percentile | Level |
| --- | --- |
| 80 and over | High |
| 60 to 79 | Above average |
| 40 to 59 | Average |
| 20 to 39 | Below average |
| Under 20 | Low |

Garner's adjusted tackles of 2.94 per 90 put him in the 87th percentile of 123
defensive midfielders: above 87 in every 100 of them.

## Ranges and small-sample estimates

A figure from few minutes is partly luck. Two extra values say how much.
Both are worked out when the scout looks a player up; neither is stored in gold.

| Value | What it is | Shown for |
| --- | --- | --- |
| Range | Where the player's underlying level probably lies, from his own figure and the minutes or attempts behind it. It uses no average. Nine times in ten the level is inside it. | Every season |
| Estimate | His figure pulled toward the average of his comparison group. The fewer his minutes, the harder the pull. | Small-sample seasons only |

Both cover the per-90 counts and the four percentages (pass accuracy, duels,
dribbles, aerials). Rating has neither.

| Step | Per-90 count | Percentage |
| --- | --- | --- |
| Range | The 5th and 95th points of a Poisson rate for his count, by the Wilson–Hilferty approximation | Wilson's interval for successes out of attempts |
| Group average | Total count ÷ total minutes in the comparison group | Total successes ÷ total attempts |
| Weight of the average | Average ÷ (spread between members − spread chance alone would give), in minutes | The same, in attempts |
| Estimate | (count + average × weight) ÷ (minutes + weight) | (successes + average × weight) ÷ (attempts + weight) |

The comparison group is the one percentiles use. The weight is calculated from
the data, separately for each indicator, position and season: an indicator on
which players truly differ gets a small weight, and one that is mostly chance
gets a large one. A group of fewer than 10 gives no estimate.

Alex Scott's 2026/27 season so far, 447 minutes, among central midfielders:

| Indicator | Figure | Range | Estimate |
| --- | --- | --- | --- |
| Adjusted tackles per 90 | 1.81 | 0.94 to 3.16 | 1.89 |
| Key passes per 90 | 2.21 | 1.24 to 3.67 | 1.80 |
| Assists per 90 | 0.00 | 0.00 to 0.60 | 0.11 |
| Duels won % | 58.9% | 47.9% to 69.1% | 51.9% |

His 2025/26 key passes, over 2,863 minutes, have a range of 0.63 to 1.21.

| Caution | Detail |
| --- | --- |
| The estimate is cautious about outliers | A genuinely exceptional figure is pulled down like a lucky one, and the estimate can fall outside the range. Goals pull hardest. |
| Ranges are too narrow for high-volume counts | Passes and touches vary from match to match by more than the Poisson rule assumes |
| The average is of regulars | Players with few minutes are compared with those above the minutes floor, who are on average better |
| Percentiles ignore both | A percentile is still the rank of the actual figure |

## How a role score is calculated

A role score says how well a player's season fits one of seven roles, from 0 to
100.

1. Take the players in the role's positions, in one season, across all five
   leagues, with at least the minutes asked for (1,500 by default).
2. Rank each player in that group on each of the role's indicators, from 0
   (lowest) to 1 (highest): the players below him ÷ (group size − 1).
3. Multiply each rank by the indicator's weight.
4. Add them up and multiply by 100.

The weights are fixed and were chosen by hand. They are not calculated from
the data or fitted to results. They sum to 100 for each role. All counts are
per 90.

| Role | Positions | Indicators and weights |
| --- | --- | --- |
| Defensive midfield | Defensive Midfield | Duels won % 25, adjusted tackles 20, adjusted interceptions 20, ball recoveries 15, pass accuracy 10, passes 10 |
| Central midfield | Central Midfield | Key passes 15, final-third passes 15, passes 15, pass accuracy 15, adjusted tackles 10, adjusted interceptions 10, ball recoveries 10, duels won % 10 |
| Creative midfield | Attacking Midfield | Key passes 30, big chances created 20, assists 20, goals 15, dribble success 15 |
| Winger | Left/Right Wing, Left/Right Midfield | Goals 25, key passes 20, big chances created 15, assists 15, dribble success 15, shots 10 |
| Centre back | Centre Back | Duels won % 20, aerials won % 20, adjusted interceptions 20, adjusted tackles 10, clearances 10, pass accuracy 10, passes 10 |
| Full back | Left Back, Right Back | Adjusted tackles 20, key passes 20, adjusted interceptions 15, duels won % 15, pass accuracy 15, dribble success 15 |
| Striker | Centre Forward, Secondary Striker | Goals 40, shots 15, shots on target % 15, assists 15, key passes 15 |

Goalkeepers have no role score.

Garner's defensive-midfield score for 2025/26, among 101 defensive midfielders
with 1,500 minutes:

| Indicator | Value | Rank, 0 to 1 | Weight | Points |
| --- | --- | --- | --- | --- |
| Duels won % | 61.3% | 0.91 | 25 | 22.8 |
| Adjusted tackles per 90 | 2.94 | 0.87 | 20 | 17.4 |
| Adjusted interceptions per 90 | 1.36 | 0.74 | 20 | 14.8 |
| Ball recoveries per 90 | 4.88 | 0.56 | 15 | 8.4 |
| Pass accuracy % | 87.2% | 0.65 | 10 | 6.5 |
| Passes per 90 | 47.27 | 0.48 | 10 | 4.8 |
| **Role score** | | | **100** | **74.6** |

The points shown add to 74.7 because the ranks are rounded to two places here;
the score uses them unrounded. It placed him fourth among Premier League
defensive midfielders.

The ranks differ slightly from the percentiles in the section above because the
groups differ: 101 players with 1,500 minutes here, 123 players above the
1,140-minute floor there.

## Limits

| Limit | Consequence |
| --- | --- |
| No expected goals | Goals and shots on target say nothing about chance quality. Finishing cannot be judged. |
| No opposition or league strength | The five leagues are pooled as if equal |
| No locations or tracking | Nothing about where actions happen, pressing, or work off the ball |
| Weights are opinion | The role score is a transparent index, not a validated rating |
| One position per player | Taken from his current profile and applied to every season. A player who changed role is ranked in the wrong group for earlier years. |
| Crude possession adjustment | Uses the team's possession for the whole match, not the player's time on the pitch, and only for tackles and interceptions |
| Rating | Averaged across matches without weighting by minutes |
| Age | His age when the profile was fetched, not his age in the season shown |
| Role-score percentages | No minimum-attempts guard beyond the minutes floor. Percentiles do have one. |
| Save percentage | Saves ÷ (saves + goals conceded). Not adjusted for shot quality. |
| One season at a time | A percentile describes one season. It is not a forecast, and neither is a small-sample estimate: it says what the season so far supports. |

## Where to look next

| Question | Page |
| --- | --- |
| What exactly is collected, and each formula | [Statistics](statistics.md) |
| Percentile and role rules as implemented | [Scout](scout.md#percentiles) |
| Known gaps in the data | [Operations](operations.md#known-data-gaps) |
| Where a number comes from in code | `databricks_gold_player_summaries.sql` for rates and the possession adjustment; `scout_backend.py` for percentiles and role scores |
