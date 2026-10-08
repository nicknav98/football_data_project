# Scout

Answers scouting questions from the gold tables. `scout_api.py` serves HTTP,
`scout_chat_app.py` is a Streamlit chat, and `scout_backend.py` holds the
queries and the assistant.

## Configuration

Set in `.env` beside `scout_api.py`, or in the environment. Restart after a change.

| Variable | Purpose |
| --- | --- |
| `DATABRICKS_SERVER_HOSTNAME` | Databricks workspace hostname |
| `DATABRICKS_HTTP_PATH` | SQL warehouse HTTP path |
| `DATABRICKS_TOKEN` | Token with `SELECT` on the two gold objects |
| `OPENAI_API_KEY` | OpenAI API key |
| `OPENAI_MODEL` | Model to use |
| `SCOUT_API_KEY` | Shared secret for `POST /scout/ask` |
| `SCOUT_REASONING_EFFORT` | Optional. `minimal`, `low` (default), `medium` or `high`. Sent to `gpt-5`, `gpt-5-mini` and `gpt-5-nano` only. `medium` and `high` are slower, cost more, and double the output budget. |
| `SCOUT_GOLD_SCHEMA` | Optional. Catalog and schema of the gold views. Default `workspace.football_data_project_sportmonks`. |

## Run

```bash
uvicorn scout_api:app                    # API; OpenAPI at /docs
python -m streamlit run scout_chat_app.py   # chat
```

`app.yaml` starts the chat as a Databricks App. The gold views must exist first.

## Endpoints

| Endpoint | Returns | Key parameters |
| --- | --- | --- |
| `GET /health` | Status | |
| `GET /metrics` | Ranking metrics and roles | |
| `GET /players` | Players matching a name | `name`, `limit` (max 10) |
| `GET /players/{player_id}/seasons` | A player's league seasons | |
| `GET /leaderboard` | Top players on one metric | `metric`, `league_id`, `season`, `min_minutes` (default 450), `limit` |
| `GET /shortlist` | Top players for a role | `role`, `season`, `league_id`, `max_age`, `min_minutes` (default 1500), `exclude_team`, `limit` |
| `POST /scout/ask` | An answer and the season rows behind it | `question`, optional `history`; header `X-Scout-API-Key` |

```bash
curl 'http://localhost:8000/shortlist?role=defensive_mid&season=2025&max_age=24&exclude_team=Chelsea'
curl -X POST 'http://localhost:8000/scout/ask' \
  -H "X-Scout-API-Key: $SCOUT_API_KEY" -H 'Content-Type: application/json' \
  -d '{"question":"Shortlist defensive midfielders under 24 for the 2025 season."}'
```

## Roles

A shortlist ranks the players whose profile `detailed_position` fits the role.
`role_score` is 0 to 100: a weighted average of percentile ranks among those
players, across all five leagues, with at least `min_minutes`.

| Role | Detailed positions | Weights |
| --- | --- | --- |
| `defensive_mid` | Defensive Midfield | Duels won % 25, adjusted tackles 20, adjusted interceptions 20, ball recoveries 15, pass accuracy 10, passes 10 |
| `central_mid` | Central Midfield | Key passes 15, final-third passes 15, passes 15, pass accuracy 15, adjusted tackles 10, adjusted interceptions 10, ball recoveries 10, duels won % 10 |
| `creative_mid` | Attacking Midfield | Key passes 30, big chances created 20, assists 20, goals 15, dribble success 15 |
| `winger` | Left/Right Wing, Left/Right Midfield | Goals 25, key passes 20, big chances created 15, assists 15, dribble success 15, shots 10 |
| `centre_back` | Centre Back | Duels won % 20, aerials won % 20, adjusted interceptions 20, adjusted tackles 10, clearances 10, pass accuracy 10, passes 10 |
| `full_back` | Left Back, Right Back | Adjusted tackles 20, key passes 20, adjusted interceptions 15, duels won % 15, pass accuracy 15, dribble success 15 |
| `striker` | Centre Forward, Secondary Striker | Goals 40, shots 15, shots on target % 15, assists 15, key passes 15 |

Counts are per 90. "Adjusted" means possession-adjusted: see
[Statistics](statistics.md#how-rates-are-computed). Weights live in
`ROLE_PROFILES` in `scout_backend.py`. League, age, and club filters narrow
the list without changing a score.

Percentages in a role score have no minimum-attempts guard beyond
`min_minutes`.

## Ranking metrics

`goals_per_90`, `assists_per_90`, `shots_per_90`, `key_passes_per_90`,
`tackles_per_90`, `interceptions_per_90`, `saves_per_90`, `pass_accuracy_pct`,
`duel_win_pct`, `dribble_success_pct`, `average_rating`,
`tackles_possession_adjusted_per_90`, `interceptions_possession_adjusted_per_90`,
`ball_recoveries_per_90`, `clearances_per_90`, `big_chances_created_per_90`,
`passes_final_third_per_90`, `touches_per_90`, `aerial_win_pct`.

| Guard | Rule |
| --- | --- |
| Per 90 | Minutes with that statistic must reach `min_minutes` |
| Percentages | At least 100 passes, 20 duels, 20 aerial duels, 10 dribbles |
| Rating | At least 5 rated matches |

## Percentiles

Every season row, from the seasons, leaderboard and shortlist lookups alike,
carries `<metric>_percentile` for each ranking metric and for `passes_per_90`:
the share of the comparison
group the player is above, with a tie counted as half.

| Part | Rule |
| --- | --- |
| Comparison group | Same `detailed_position`, same season, all five leagues |
| Minutes floor | A third of the most minutes anyone played that season, returned as `percentile_pool_min_minutes` (1,140 for a full season) |
| Group size | Returned as `percentile_pool_size` |
| Percentages and rating | Null unless the player and the group member both meet the attempts guard below |
| Small sample | `small_sample` is true below the minutes floor, or below 900 minutes when the floor is lower, as early in a season. The row is still ranked; the assistant is told to say the minutes are too few. |

A shortlist's `role_score` ranks only players with the requested `min_minutes`,
so it uses a different group from these percentiles.

## Markers

The model does not type statistics. Where a figure belongs it writes a marker,
and `fill_markers` in `scout_backend.py` puts the value from that row in its
place. A figure in an answer therefore cannot differ from the data.

```
The model writes:  Scott made {37550443:39:2025 tackles_per_90} tackles per 90
                   ({37550443:39:2025 tackles_per_90_percentile}).
The user sees:     Scott made 1.92 tackles per 90 (51st percentile (average)).
```

| Part | Rule |
| --- | --- |
| Form | `{player_id:league_id:season field}`. `field` is any key of that row. |
| Display | Counts get thousands separators, rates two decimals, `_pct` a percent sign, `_percentile` reads "35th percentile (below average)", a missing value reads "not available" |
| Sources | The rows an answer drew on are listed on a final `Sources:` line, below the [figures table](#figures-table) |
| Level words | Code states the level of a percentile: low (under 20), below average (20 to 39), average (40 to 59), above average (60 to 79), high (80 and over). The assistant is told not to add its own. |
| Judgements | The assistant is told to give the figure and its percentile whenever it says a player is good, poor, better or worse at something, and to name seasons by year |
| Bad marker | One naming a row that was not retrieved, or a field not in it, is sent back once for correction, then the answer is rejected. So is an answer with no marker. |
| Typed figure | A statistic typed as digits is sent back once. If it persists the answer is shown with a "Not verified" note listing the figures, also returned as `unverified_figures`. |
| Not counted as typed | Seasons, player and league IDs, numbers in the question or the lookup arguments, "per 90", decades such as "mid-40s", whole numbers below 10 |
| Earlier turns | A follow-up must retrieve a row again to use it |
| Known gap | A marker can still name the wrong row or field. The value shown is then real but misplaced. |

## Figures table

`figures_table` in `scout_backend.py` adds a table below every answer, built
from the rows the answer drew on, not by the model. A judgement in the prose
can then be held against the figure and its percentile.

| Part | Rule |
| --- | --- |
| Rows | One per season the answer used a marker from |
| Grouping | One table per `detailed_position`, since percentiles are within a position |
| Columns | Minutes, the statistics the position's role is scored on (see [Roles](#roles)), and rating. A shortlist row also shows its role score. |
| Cells | The value, then its percentile in brackets where one was computed. A dash means no value. |
| Small samples | Minutes marked † when the row's `small_sample` is true |
| Other positions | Goalkeepers: saves, pass accuracy, rating. Any other: passes, pass accuracy, duels won, rating. |

## Assistant

| Rule | Detail |
| --- | --- |
| Data access | Four fixed read-only tools: search, seasons, leaderboard, shortlist. The model cannot write SQL. |
| Lookups | Up to six per question |
| Figures | Written as markers and filled in from the retrieved rows. See [Markers](#markers). The rejected text of a failed answer is logged as a warning. |
| Weaknesses | The instructions list the statistics each role is scored on, built from `ROLE_PROFILES`. For each shortlisted player, and a player assessed alone, the assistant is told to name the one with his lowest percentile. |
| Adjusted rates | The assistant is told not to cite raw tackles or interceptions for a role scored on the adjusted versions |
| Possession | The assistant is told to call `average_team_possession_pct` his team's possession in the matches he played, since it is weighted by his minutes and differs between team-mates |
| Percentiles | Season rows carry a 0 to 100 percentile for each ranking metric and for passes per 90. The assistant is told to call a figure high or low from that, not from the raw number. |
| History | The service keeps none. Send earlier turns in `history` (up to 20). |
| Output budget | 4,096 tokens, retried once at 8,192 if truncated. Doubled at `medium` or `high` reasoning effort, since reasoning counts against it. |
| Timeout | 120 seconds, no automatic retry |
| Not in the data | Fees, wages, contracts, scout notes. The assistant says so. |

## Logs

There is no log file. Both the API and the chat write timestamped lines to
standard error. For the Databricks App, open the **Logs** tab on the app's page,
or the app's URL with `/logz` added. It shows the running app, not a history.

| Line | Level | Meaning |
| --- | --- | --- |
| `Scout OpenAI response completed: model=... effort=... elapsed=...` | Info | One per model call, with the model and reasoning effort in use |
| `Scout data lookup: tool=... rows=...` | Info | One per lookup |
| `Scout answer rejected (...)` | Warning | A marker was unusable or a figure was typed; includes the answer text |
| `Scout model response truncated` | Warning | The output budget was reached |
| `Scout OpenAI request timed out` | Warning | The 120-second timeout was reached |

## Access

| Surface | Protection |
| --- | --- |
| `POST /scout/ask` | `SCOUT_API_KEY`. Keep it server-side. |
| Other endpoints | None |
| Chat app | None. It calls the assistant in its own process and ignores `SCOUT_API_KEY`. Put it behind a sign-in. |

Add user rate limits and a spending cap before any public use.
