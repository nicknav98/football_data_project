# For analysts

What numbers the project computes, how, and what to be sceptical of. Written
for a football analyst who needs to judge the output, not run the code.

There is no predictive model here. The project is descriptive statistics in
four layers: season rates, a possession adjustment, percentile ranks within
position, and a hand-weighted role score. The language model in the scouting
assistant writes the sentences. It computes nothing: every figure in an answer
is filled in by code from the tables (see [Scout](scout.md#markers)).

## The four layers

| Layer | What is computed | Formula |
| --- | --- | --- |
| 1. Season rates | Per-90 figures and success percentages for each player, league and season | 90 × total ÷ minutes; 100 × successes ÷ attempts |
| 2. Possession adjustment | Tackles and interceptions scaled to an opponent with half the ball | Each match's count × 50 ÷ opponent possession, summed, then per 90 |
| 3. Percentiles | Where a player ranks on each metric among players in his position that season | Share of the group he is above, a tie counted as half |
| 4. Role score | A 0 to 100 fit for one of seven roles | Weighted average of his percentile ranks on that role's metrics |

The source is Sportmonks player statistics for each match in five European
leagues. Everything is built up from per-match counts. The full list of what is
collected, and every derived metric, is in [Statistics](statistics.md).

## How each layer works

| Topic | Rule |
| --- | --- |
| Per 90 | Minutes are counted only in matches that report the statistic |
| Percentages | Counted only over matches that report both the attempts and the successes |
| Possession adjustment | Applied to tackles and interceptions only. Uses the team's possession for the whole match. |
| Comparison group | Same detailed position (such as Defensive Midfield), same season, all five leagues pooled |
| Minutes floor for the group | A third of the most minutes anyone played that season: 1,140 for a full season |
| Percentage guards | A percentage is ranked only with at least 100 passes, 20 duels, 20 aerial duels or 10 dribbles; a rating with at least 5 rated matches |
| Small samples | A season is flagged below the minutes floor, or below 900 minutes when the floor is lower, as early in a season |
| Level words | Low (under 20th percentile), below average (20 to 39), average (40 to 59), above average (60 to 79), high (80 and over) |
| Direction | A higher percentile is always the better one. No ranked metric is "lower is better". |

Why adjust for possession: a midfielder on a team that rarely has the ball gets
more chances to tackle. James Garner at Everton, who averaged 43.6% possession
in 2025/26, goes from 3.19 tackles per 90 to 2.94 adjusted.

## Key indicators by role

The role-score weights, in percent. All counts are per 90.

| Role | Positions | Indicators and weights |
| --- | --- | --- |
| Defensive midfield | Defensive Midfield | Duels won % 25, adjusted tackles 20, adjusted interceptions 20, ball recoveries 15, pass accuracy 10, passes 10 |
| Central midfield | Central Midfield | Key passes 15, final-third passes 15, passes 15, pass accuracy 15, adjusted tackles 10, adjusted interceptions 10, ball recoveries 10, duels won % 10 |
| Creative midfield | Attacking Midfield | Key passes 30, big chances created 20, assists 20, goals 15, dribble success 15 |
| Winger | Left/Right Wing, Left/Right Midfield | Goals 25, key passes 20, big chances created 15, assists 15, dribble success 15, shots 10 |
| Centre back | Centre Back | Duels won % 20, aerials won % 20, adjusted interceptions 20, adjusted tackles 10, clearances 10, pass accuracy 10, passes 10 |
| Full back | Left Back, Right Back | Adjusted tackles 20, key passes 20, adjusted interceptions 15, duels won % 15, pass accuracy 15, dribble success 15 |
| Striker | Centre Forward, Secondary Striker | Goals 40, shots 15, shots on target % 15, assists 15, key passes 15 |

The weights were chosen by hand. They were not fitted to results, transfer
outcomes, or any other measure. Goalkeepers have no role score.

A role score ranks only players with the minutes asked for (1,500 by default),
so it is built on a slightly different group from the percentiles shown beside
it.

## A worked example

James Garner, Premier League 2025/26, ranked among 123 defensive midfielders.
Figures as loaded on 2026-10-07.

| Indicator | Value | Percentile | Level |
| --- | --- | --- | --- |
| Adjusted tackles per 90 | 2.94 | 87th | High |
| Adjusted interceptions per 90 | 1.36 | 73rd | Above average |
| Duels won | 61.3% | 91st | High |
| Ball recoveries per 90 | 4.88 | 58th | Average |
| Pass accuracy | 87.2% | 63rd | Above average |
| Passes per 90 | 47.27 | 48th | Average |

His defensive-midfield role score was 74.6, fourth among Premier League
defensive midfielders with 1,500 minutes.

## What to be sceptical of

| Limit | Consequence |
| --- | --- |
| No expected goals | Goals and shots on target say nothing about chance quality. Finishing cannot be judged. |
| No opposition or league strength | The five leagues are pooled as if equal |
| No locations or tracking | Nothing about where actions happen, pressing, or work off the ball |
| Weights are opinion | The role score is a transparent index, not a validated rating |
| One position per player | Taken from his current profile and applied to every season. A player who changed role is ranked in the wrong group for earlier years. |
| Crude possession adjustment | Uses the team's possession for the whole match, not the player's time on the pitch, and only for two statistics |
| Rating | Sportmonks' own match rating, averaged across matches without weighting by minutes |
| Age | His age when the profile was fetched, not his age in the season shown |
| Role-score percentages | No minimum-attempts guard beyond the minutes floor. The percentiles shown beside them do have one. |
| Save percentage | Saves ÷ (saves + goals conceded). Not adjusted for shot quality. |
| One season at a time | A percentile describes one season. It is not a forecast. |

## Where to look next

| Question | Page |
| --- | --- |
| What exactly is collected, and each formula | [Statistics](statistics.md) |
| Percentile and role rules as implemented | [Scout](scout.md#percentiles) |
| Known gaps in the data | [Operations](operations.md#known-data-gaps) |
| Where a number comes from in code | `databricks_gold_player_summaries.sql` for layers 1 and 2; `scout_backend.py` for layers 3 and 4 |
