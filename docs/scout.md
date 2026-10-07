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

`GET /players/{player_id}/seasons` and the assistant's season lookup return
`<metric>_percentile` for each ranking metric: the share of the comparison
group the player is above, with a tie counted as half.

| Part | Rule |
| --- | --- |
| Comparison group | Same `detailed_position`, same season, all five leagues |
| Minutes floor | A third of the most minutes anyone played that season, returned as `percentile_pool_min_minutes` (1,140 for a full season) |
| Group size | Returned as `percentile_pool_size` |
| Percentages and rating | Null unless the player and the group member both meet the attempts guard below |
| Player below the floor | Still ranked. The assistant is told to say the sample is small. |

Leaderboard and shortlist rows do not carry percentiles.

## Figure check

`unmatched_figures` in `scout_backend.py` compares the numbers in an answer
with the cited rows.

| Case | Treatment |
| --- | --- |
| Rounding | A figure passes if a row value rounds to it |
| Not checked | Whole numbers below 10, "per 90", decades such as "mid-40s", the second year in "2025/26" |
| Pass on any line | Player IDs, league IDs, seasons, numbers in the question, the lookup arguments, and name-search results |
| Row from an earlier turn | Lines citing it are not checked |
| Known gap | A figure the model worked out itself, such as a sum, is flagged even when right. The assistant is told not to calculate. |

## Assistant

| Rule | Detail |
| --- | --- |
| Data access | Four fixed read-only tools: search, seasons, leaderboard, shortlist. The model cannot write SQL. |
| Lookups | Up to six per question |
| Citations | Every figure cites a retrieved row as `[player_id:league_id:season]`. An answer that cites no row, or a row that was not retrieved, is sent back once for correction, then rejected. The rejected text is logged as a warning. |
| Figures | Each figure must be in the row cited on its line, or on the closest cited line above. A mismatch is sent back once for correction. If it persists the answer is shown with a "Not verified" note listing the figures, also returned as `unverified_figures`. |
| Percentiles | Season rows carry a 0 to 100 percentile for each ranking metric. The assistant is told to call a figure high or low from that, not from the raw number. |
| History | The service keeps none. Send earlier turns in `history` (up to 20). |
| Output budget | 4,096 tokens, retried once at 8,192 if truncated |
| Timeout | 120 seconds, no automatic retry |
| Not in the data | Fees, wages, contracts, scout notes. The assistant says so. |

## Access

| Surface | Protection |
| --- | --- |
| `POST /scout/ask` | `SCOUT_API_KEY`. Keep it server-side. |
| Other endpoints | None |
| Chat app | None. It calls the assistant in its own process and ignores `SCOUT_API_KEY`. Put it behind a sign-in. |

Add user rate limits and a spending cap before any public use.
