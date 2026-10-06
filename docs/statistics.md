# Statistics

What the pipeline collects for each player in each match, what gold derives
from it, and which scouting questions each metric helps answer.

## Collected per player per match

Source: Sportmonks lineup details. One row per league, season, fixture, team,
and player.

### Identity and playing time

| Column | Meaning |
| --- | --- |
| `league_id`, `season`, `round`, `fixture_id` | Match |
| `team_id`, `team_name` | Team |
| `player_id`, `player_name` | Player |
| `games_minutes` | Minutes played. Blank for an unused substitute. |
| `games_substitute` | Named on the bench |
| `games_position` | G, D, M, or F |
| `games_detailed_position` | Slot in the starting formation. Blank for substitutes. |
| `games_formation_field`, `games_number`, `games_captain` | Formation cell, shirt number, captain |
| `games_rating` | Sportmonks match rating, 0 to 10 |

### Shooting and scoring

| Column | Sportmonks statistic |
| --- | --- |
| `goals_total` | Goals. Excludes own goals. |
| `own_goals` | Own goals |
| `shots_total` | Shots. Includes blocked shots. |
| `shots_on`, `shots_off` | Shots on and off target |
| `shots_blocked` | The player's shots that were blocked |
| `shots_woodwork` | Shots against the post or bar |
| `big_chances_missed` | Big chances missed |
| `penalty_scored`, `penalty_missed`, `penalty_won` | Penalties scored, missed, won |
| `offsides` | Offsides |

### Passing and creating

| Column | Sportmonks statistic |
| --- | --- |
| `passes_total`, `passes_accuracy` | Passes, accurate passes (a count) |
| `passes_key` | Key passes |
| `goals_assists` | Assists |
| `big_chances_created` | Big chances created |
| `passes_final_third` | Passes into the final third |
| `crosses_total`, `crosses_accurate` | Crosses, accurate crosses |
| `long_balls_total`, `long_balls_accurate` | Long balls, accurate long balls |
| `through_balls_total`, `through_balls_accurate` | Through balls, accurate through balls |

### On the ball

| Column | Sportmonks statistic |
| --- | --- |
| `touches` | Touches |
| `dribbles_attempts`, `dribbles_success` | Dribbles attempted, successful |
| `possession_lost` | Possession lost |
| `dispossessed` | Times dispossessed |
| `fouls_drawn` | Fouls drawn |

### Defending

| Column | Sportmonks statistic |
| --- | --- |
| `tackles_total`, `tackles_won` | Tackles, tackles won |
| `tackles_interceptions` | Interceptions |
| `tackles_blocks` | Shots the player blocked |
| `clearances` | Clearances |
| `ball_recoveries` | Ball recoveries |
| `duels_total`, `duels_won` | Duels, duels won |
| `aerials_won`, `aerials_lost` | Aerial duels won, lost |
| `dribbles_past` | Times dribbled past |
| `errors_leading_to_shot`, `errors_leading_to_goal` | Errors leading to a shot, a goal |
| `goals_conceded` | Team goals conceded while on the pitch |

### Discipline

| Column | Sportmonks statistic |
| --- | --- |
| `fouls_committed` | Fouls |
| `cards_yellow` | Yellow cards |
| `cards_red` | Red cards. A second yellow adds one. |
| `penalty_commited` | Penalties conceded |

### Goalkeeping

Filled for goalkeepers only.

| Column | Sportmonks statistic |
| --- | --- |
| `goals_saves`, `saves_inside_box` | Saves, saves from shots inside the box |
| `goalkeeper_goals_conceded` | Goals conceded as goalkeeper |
| `penalty_saved` | Penalties saved |
| `goalkeeper_punches`, `goalkeeper_high_claims` | Punches, high claims |

### Team context

| Column | Meaning |
| --- | --- |
| `team_possession_pct` | The team's share of possession in the match. Same on every row of that team. |

## Collected per player

Source: each team's season squad. One row per player.

| Column | Meaning |
| --- | --- |
| `player_id`, `name`, `firstname`, `lastname` | Player |
| `birth_date`, `age` | Birth date; age on the day of the fetch |
| `nationality`, `height`, `weight` | Nationality, height, weight |
| `position` | Goalkeeper, Defender, Midfielder, or Attacker |
| `detailed_position` | Usual role, such as Defensive Midfield |

## Collected per fixture

| Column | Meaning |
| --- | --- |
| `kickoff_utc`, `status`, `round` | Kickoff, state, matchday |
| `home_team_*`, `away_team_*` | Teams |
| `home_goals`, `away_goals`, `halftime_*` | Full-time and half-time score |
| `referee`, `venue_*` | Referee and venue |

## Gold metrics

One row per player, league, and season in `gold_player_season_summary`.

| Kind | Metrics |
| --- | --- |
| Playing time | `minutes`, `appearances`, `starts`, `substitute_appearances` |
| Totals | A season total for every collected count |
| Per 90 | `goals`, `non_penalty_goals`, `assists`, `shots`, `key_passes`, `big_chances_created`, `passes_final_third`, `touches`, `possession_lost`, `tackles`, `interceptions`, `blocks`, `clearances`, `ball_recoveries`, `aerials_won`, `fouls_drawn`, `fouls_committed`, `saves` (each as `<name>_per_90`) |
| Possession-adjusted per 90 | `tackles_possession_adjusted_per_90`, `interceptions_possession_adjusted_per_90` |
| Percentages | `pass_accuracy_pct`, `shots_on_target_pct`, `duel_win_pct`, `aerial_win_pct`, `dribble_success_pct`, `tackle_success_pct`, `cross_accuracy_pct`, `long_ball_accuracy_pct`, `save_pct` |
| Context | `average_team_possession_pct`, `average_rating`, `primary_position`, `detailed_position`, `profile_age`, `nationality`, `team_names` |
| Coverage | `<stat>_observed_minutes` and `<stat>_with_*_data`: how much data supports each rate |

### How rates are computed

| Metric | Formula |
| --- | --- |
| Per 90 | 90 × total ÷ minutes in matches that report the statistic |
| Percentage | 100 × part ÷ whole, over matches that report both |
| Possession-adjusted count | Each match's count × 50 ÷ opponent possession, summed |
| `average_team_possession_pct` | Team possession weighted by the player's minutes |
| `save_pct` | Saves ÷ (saves + goals conceded), in matches played as goalkeeper |

## Scouting questions

| Question | Metrics | Roles it matters for |
| --- | --- | --- |
| Who wins the ball back? | `tackles_possession_adjusted_per_90`, `interceptions_possession_adjusted_per_90`, `ball_recoveries_per_90`, `tackle_success_pct` | Defensive midfield, full back |
| Who wins duels and headers? | `duel_win_pct`, `aerial_win_pct`, `aerials_won_per_90` | Centre back, striker |
| Who defends the box? | `clearances_per_90`, `blocks_per_90`, `errors_leading_to_goal` | Centre back |
| Who moves the ball forward? | `passes_final_third_per_90`, `long_ball_accuracy_pct`, `key_passes_per_90` | Central midfield, centre back |
| Who creates chances? | `key_passes_per_90`, `big_chances_created_per_90`, `assists_per_90`, `cross_accuracy_pct` | Attacking midfield, winger, full back |
| Who scores? | `goals_per_90`, `non_penalty_goals_per_90`, `shots_per_90`, `shots_on_target_pct`, `big_chances_missed` | Striker, winger |
| Who beats a man? | `dribble_success_pct`, `dribbles_attempted`, `fouls_drawn_per_90` | Winger, attacking midfield |
| Who keeps the ball? | `pass_accuracy_pct`, `possession_lost_per_90`, `dispossessed` | All midfield roles |
| How involved is he? | `touches_per_90`, `passes_attempted` | All |
| How good is the goalkeeper? | `save_pct`, `saves_per_90`, `saves_inside_box`, `goalkeeper_high_claims` | Goalkeeper |
| Is he reliable and available? | `minutes`, `starts`, `yellow_cards`, `red_cards`, `fouls_committed_per_90` | All |
| Is the number his or his team's? | `average_team_possession_pct`, the adjusted rates | Defensive counts |
| What does he actually play? | `detailed_position` | All |

## What the data cannot answer

| Question | Missing |
| --- | --- |
| Can we afford him? | Transfer fees, market values, wages, contracts |
| Is he finishing above expectation? | Expected goals |
| What does he do off the ball? | Tracking and event locations |
| Why did he miss matches? | Injury records |
| How strong was the opposition? | Team and league strength ratings |

## Rules to know

| Rule | Detail |
| --- | --- |
| Zero means zero | Sportmonks omits a zero. The sync writes 0 for a player who played in a match with detailed statistics. |
| Blank means unknown | Unused substitutes, and a total whose part was reported without it |
| Small samples | Rates on few minutes or attempts are unstable. Filter on minutes and on the coverage columns. |
| Adjusted rates | Use team possession for the whole match, not the player's time on the pitch |
| Position | From the profile, as of the last fetch. One per player across all seasons. |
| Age | Age when the profile was fetched, not age during the season |
