## Football Data Project

Player statistics for five European leagues, from Sportmonks to a scouting
assistant. Two local scripts fetch the data and write CSV files to S3. A
Databricks job loads them into bronze and silver tables, a SQL file builds the
gold summaries, and the scout API and chat answer questions from gold.

### Configuration

The sync scripts read these from `.env` beside them or from the environment:

| Variable | Purpose |
| --- | --- |
| `SPORTMONKS_API_TOKEN` | Sportmonks API token |
| `SPORTMONKS_S3_PREFIX` | S3 prefix for the files, `sportmonks/football-matchday-stats` |
| `AWS_S3_BUCKET` | S3 bucket |
| `AWS_REGION` | Optional AWS region |
| `FOOTBALL_SEASON` | Latest season to sync, by starting year (default 2026) |
| `FOOTBALL_HISTORY_SEASONS` | Earlier seasons to sync as well (default 2) |
| `PLAYER_PROFILE_CACHE_HOURS` | How long a profile scan is reused (default 168) |

AWS credentials come from the usual boto3 provider chain.

### Five league matchday sync

`sync_matchday_stats.py` fetches the Premier League (39), La Liga (140),
Bundesliga (78), Serie A (135), and Ligue 1 (61) for `FOOTBALL_SEASON` and the
preceding `FOOTBALL_HISTORY_SEASONS`. With the defaults, it syncs 2024 through
2026. The league IDs are the project's own; `sportmonks.py` maps them to
Sportmonks league and season IDs. Fixture, team, and player IDs are
Sportmonks IDs.

It writes one CSV per matchday under `SPORTMONKS_S3_PREFIX`, for example
`league_39/season_2026/ENG_PREMIER_LEAGUE_MATCHDAY_01.csv`. For rounds without
a number, the suffix uses the round name, such as
`GER_BUNDESLIGA_MATCHDAY_RELEGATION_ROUND.csv`. Each file holds one row per
player per fixture. A player's appearances remain separate by league, season,
fixture, team, and player ID, including after transfers. Local copies go to
`output/sportmonks/`. State lives in `state/sportmonks/processed_fixtures.json`,
keyed by `league_id:season:fixture_id`.

A matchday is fetched when it has a finished fixture the state does not hold,
and again while any of its fixtures kicked off less than 12 hours ago, so
corrections arrive. A matchday file is always replaced as a whole. Fixtures
that were abandoned or awarded are not treated as finished and have no player
rows.

How Sportmonks statistics become rows:

- Sportmonks leaves a statistic out when it is zero. A count missing for a
  player who played is written as 0 when the fixture has detailed statistics.
  Saves and penalties saved are filled for goalkeepers only. A substitute who
  did not play has blank statistics. A total, such as dribbles attempted,
  stays blank when Sportmonks reports only its part.
- Sportmonks has no player ID for a few lineup entries. The sync skips them
  and prints the fixture and name.
- `games_position` is G, D, M, or F. `games_detailed_position` is the slot in
  the starting formation, such as Central Midfield. It is blank for
  substitutes and rarely says Defensive Midfield, so use the profile's
  `detailed_position` for a player's role.
- `passes_accuracy` is the number of accurate passes, not a percentage.
- `team_possession_pct` is the team's share of possession over the whole
  match, the same on every row of that team.
- Rows also carry statistics API-Football never had: touches, passes into the
  final third, crosses, long balls, through balls, big chances created and
  missed, shots off target, blocked, and against the woodwork, own goals,
  possession lost, dispossessed, tackles won, clearances, ball recoveries,
  aerials won and lost, errors leading to a shot or goal, and for goalkeepers
  saves inside the box, goals conceded, punches, and high claims.
- `shots_total` includes blocked shots. `shots_blocked` is the player's own
  shots that were blocked; `tackles_blocks` is shots the player blocked.
- A second yellow card adds one to `cards_red`.

One fixture's statistics take one request, and a league season's fixture list
takes eight. Sportmonks allows a set number of requests per entity per hour.
When that runs out, the sync waits for the reset and continues. Connection
failures and HTTP 429 or 5xx responses are retried up to three times.

`com.footballdata.matchdaysync.plist` runs the sync every three hours on
macOS. Run the sync on one machine only: each keeps its own state, so a second
machine fetches every fixture again and uses the same hourly allowance.

After a change that adds columns, delete `state/sportmonks/processed_fixtures.json`
and run the sync to fetch every fixture again. Bronze and silver add the new
columns when the job next runs.

### Fixtures

Each sync also writes the full fixture list for every league and season to
`reference/fixtures/league_39_season_2026.csv` (and so on) under
`SPORTMONKS_S3_PREFIX`. Each row has the kickoff time in UTC, status, round,
referee, venue, home and away teams, and the full-time and half-time score.
Unplayed fixtures are included with blank scores. A file is uploaded again
only when its content changes.

Matchday statistics join to fixtures on `league_id`, `season`, and
`fixture_id`. A player's team is at home when `team_id` equals `home_team_id`.

### Player profiles

Run `python sync_player_profiles.py` to collect profiles for the same leagues
and seasons. It reads every team's squad in each league season and keeps one
profile per player ID, the latest season winning. A completed scan is cached
for seven days in `state/sportmonks/player_profiles.json`; set
`PLAYER_PROFILE_CACHE_HOURS=0` to force a new scan.

The script uploads `reference/player_profiles/player_profiles.csv` under
`SPORTMONKS_S3_PREFIX`. Profiles include birth date, nationality, height,
weight, `position`, `detailed_position` (the player's usual role, such as
Defensive Midfield), and `fetched_at`. Age is computed from the birth date on
the day of the fetch, not a historical age for `source_season`. `birth_place`,
`birth_country`, and `injured` are blank. Matchday statistics join to profiles
by `player_id`.

### Deploying the Databricks job

`databricks.yml` and `resources/sportmonks_ingest.job.yml` define the
Sportmonks Ingest job as a Databricks Asset Bundle. Deploying uploads the
scripts and the silver notebook and creates or updates the job, so the job
always runs the code in the deployed commit.

```bash
databricks bundle validate
databricks bundle deploy            # dev, the default target
databricks bundle run sportmonks_ingest
databricks bundle deploy -t prod
```

The job copies S3 files into the volumes, then loads player profiles,
fixtures, and matchday stats independently, then runs the silver notebook.
Each task receives the catalog and schema as parameters. The bundle creates
the schema and its four volumes in both targets.

| Target | Job name | Schema | Schedule |
| --- | --- | --- | --- |
| `dev` | `[dev <user>] Sportmonks Ingest` | `dev_<user>_football_data_project_sportmonks` | Paused |
| `prod` | `Sportmonks Ingest` | `football_data_project_sportmonks` | Daily |

To reprocess all of bronze into silver, run the job with the `silver` task's
`full_refresh` parameter set to `true`. `databricks_gold_player_summaries.sql`
is not part of the bundle; see Gold player summaries.

The job tasks:

- **`databricks_volume_sync.py`** copies matchday files to
  `football_data/<season>/`, fixture files to `football_data/fixtures/`, and
  the profile file to `player_profiles_data/`. It records the S3 ETag of each
  copied file in `_checkpoints/s3_volume_sync/copied_etags.json` and downloads
  a file again only when its ETag has changed or its copy is missing. Delete
  the manifest to force a full copy.
- **`databricks_matchday_stream.py`** upserts `bronze_matchday_stats` by
  league, season, fixture, team, and player. It reads only files named
  `*_MATCHDAY_*.csv` and fails if a key column is null. When files bring new
  columns, Auto Loader stops once and the task's retry reads them.
- **`databricks_fixtures.py`** upserts `bronze_fixtures` by league, season,
  and fixture ID.
- **`databricks_player_profiles.py`** upserts `bronze_player_profiles` by
  `player_id`.

Each loader has its own Auto Loader schema and checkpoint locations.

### Silver layer

The silver notebook, `Silver Layer Matchday Stats By League.ipynb`, maintains
one table for all five leagues, `silver_matchday_stats`, clustered by league
and season. Each run merges only the bronze rows ingested since the previous
run, so corrections update rows in place. Set the notebook's `full_refresh`
parameter to `true` to reprocess every bronze row, for example after changing
a cleaning rule. Its `catalog` and `schema` parameters select the schema to
read and write.

Silver keeps one row per league, season, fixture, team, and player.
Whole-number statistics are stored as integers. A value outside its valid
range (a negative count, more than 130 minutes, a rating above 10) is replaced
with null, and the row's `quality_issues` array records the rule, for example
`games_rating_out_of_range`. A part that exceeds its whole, such as more shots
on target than shots, is recorded in `quality_issues` but left as reported.
Sportmonks reports a few such rows. The last notebook cell prints the count of
each issue and fails if any key is duplicated.

When `bronze_fixtures` exists, the notebook also maintains `silver_fixtures`
with a typed `kickoff_utc`, `match_date`, `is_finished`, and `result` (`H`,
`D`, or `A`).

### Gold player summaries

After the job has run, execute `databricks_gold_player_summaries.sql` in a
Databricks SQL editor using a Pro or Serverless SQL warehouse. Its table names
have no schema, so select the schema first:

```sql
USE workspace.football_data_project_sportmonks;
```

Its first statement creates `gold_player_season_summary`, one row per player,
league, and season. Its second creates `gold_player_observed_summary`, one row
per player across only the league seasons present in the data. They need to be
created once per schema.

The gold materialized view uses `TRIGGER ON UPDATE` to refresh after the
silver table or the profile table changes. The silver notebook merges changed
rows and enables row tracking, so Databricks can refresh the view
incrementally where the query allows it. This is a refreshable serving table,
not an event stream.

The season summary includes teams, appearances, starts, minutes, position,
`detailed_position` from the profile, totals, per 90 rates, shooting and duel
percentages, pass accuracy (`accurate_passes` over `passes_with_accuracy`,
counting matches that report both), and the latest available profile fields.
It also has offsides, blocks, times dribbled past, fouls drawn and committed,
and penalties won, committed, scored, missed, and saved, and totals for the
extra Sportmonks statistics, with per 90 rates for touches, passes into the
final third, big chances created, possession lost, clearances, ball
recoveries, and aerials won, and percentages for aerials, crosses, long balls,
and tackles.

`tackles_possession_adjusted_per_90` and
`interceptions_possession_adjusted_per_90` correct for how much of the ball a
player's team has. Each match's count is multiplied by 50 and divided by the
opponent's possession, so a player whose opponents had 60% of the ball has the
count scaled down by a sixth. Possession is the team's for the whole match,
not only while the player was on the pitch. `average_team_possession_pct` is
the team's possession weighted by the player's minutes. `non_penalty_goals`
uses only matches that report both goals and penalties scored. `save_pct` is
saves divided by saves plus goals conceded, counted in matches played as
goalkeeper. Percentages use matches where both parts of the ratio are present.
Each per 90 rate uses minutes from matches where that stat is present. The
corresponding `*_observed_minutes` and coverage columns show how much data
supports a rate. An all missing stat remains null. Profile age is age when
fetched, not age during that season. The observed summary is not a career
total outside the loaded leagues and seasons.

Check the result in Databricks SQL:

```sql
SELECT player_id, league_id, season, COUNT(*) AS rows_per_key
FROM workspace.football_data_project_sportmonks.gold_player_season_summary
GROUP BY player_id, league_id, season
HAVING COUNT(*) > 1;

SELECT player_id, player_name, league_name, season, appearances, minutes,
       goals, goals_observed_minutes, goals_per_90, profile_age, nationality
FROM workspace.football_data_project_sportmonks.gold_player_season_summary
WHERE minutes >= 450
ORDER BY goals_per_90 DESC
LIMIT 20;
```

The first query should return no rows. `silver_as_of` shows the latest silver
processing time in each summary. It does not guarantee that every fixture in
the source API has been ingested.

### History: API-Football

The pipeline was first built on API-Football and moved to Sportmonks in
October 2026. Two limits of the API-Football data led to the move.

- **Positions.** API-Football labels a player only as goalkeeper, defender,
  midfielder, or forward. The scout had to guess a role such as defensive
  midfielder from statistics. Sportmonks records a detailed position, such as
  Defensive Midfield, on each player profile.
- **Inflated per 90 rates.** API-Football leaves a statistic blank when it is
  zero. The gold summaries treat a blank as not recorded and leave that
  match's minutes out of the rate, so a rate was computed only over the
  matches where the player registered the statistic. For 2025/26 the
  API-Football gold shows Erling Haaland at 1.42 goals per 90 and Declan Rice
  at 1.39, where goals divided by minutes gives 0.82 and 0.12. Tackles,
  interceptions, and other counts are overstated in the same way, by less.
  The Sportmonks sync writes those zeros, so its gold rates are correct.

The API-Football client and its Databricks job have been removed. Its tables
remain in `workspace.football_data_project` and its files under the
`football-matchday-stats` S3 prefix. Nothing updates them, and the gold tables
there keep the inflated rates, so do not use them for per 90 comparisons.
Minutes, appearances, and goals agree between the two providers. The CSV
column names and the nested layout that `sportmonks.py` produces come from
API-Football.

### Scout API

`scout_api.py` serves the gold summaries over HTTP. Run the updated gold SQL
before starting it so `passes_with_accuracy` is available. It provides player
name search, player season summaries, a metric leaderboard, a role shortlist,
a list of ranking metrics and roles, and a scouting question endpoint. The
question endpoint uses fixed read-only tools over the gold tables and returns
the retrieved season rows alongside its answer. Model-generated SQL cannot
run. The service does not retain chat history. For a follow-up question, send
the earlier turns in `history` (up to 20, each with a `role` of `user` or
`assistant` and its `content`). The data contains statistical indicators and
has no written scout observations, transfer history, fees, or contracts.
Rankings require at least the requested minutes of coverage for per 90 stats.
Percentage rankings also require a minimum number of observed attempts or
rated matches.

The API reads the gold views built from Sportmonks data, in
`workspace.football_data_project_sportmonks` unless `SCOUT_GOLD_SCHEMA` names
another schema. Those views must exist before it starts.

A shortlist scores the players whose usual position fits a role. The position
is the `detailed_position` on the player's Sportmonks profile.

| Role | Detailed positions |
| --- | --- |
| `defensive_mid` | Defensive Midfield |
| `central_mid` | Central Midfield |
| `creative_mid` | Attacking Midfield |
| `winger` | Left Wing, Right Wing, Left Midfield, Right Midfield |
| `centre_back` | Centre Back |
| `full_back` | Left Back, Right Back |
| `striker` | Centre Forward, Secondary Striker |

`role_score` is a 0 to 100 weighted average of percentile ranks, taken among
the players in those positions in the season with at least `min_minutes`,
across all five leagues. League, age, and club filters narrow the output
without changing a score. The weights are in `ROLE_PROFILES` in
`scout_backend.py`. A profile has one position, so a player who changed role
is still scored under the profile's. Defensive counts are per 90 minutes and
are not adjusted for possession, so players on teams with less of the ball
tend to score higher on them.

Install `requirements.txt` and set these server-side environment variables:

| Variable | Purpose |
| --- | --- |
| `DATABRICKS_SERVER_HOSTNAME` | Databricks workspace hostname |
| `DATABRICKS_HTTP_PATH` | SQL warehouse HTTP path |
| `DATABRICKS_TOKEN` | Token with read access to the gold views |
| `OPENAI_API_KEY` | OpenAI API key |
| `OPENAI_MODEL` | Model available to your OpenAI project |
| `SCOUT_API_KEY` | Shared secret required by the question endpoint |
| `SCOUT_GOLD_SCHEMA` | Optional catalog and schema of the gold views |

The API and Streamlit chat automatically load `.env` beside `scout_api.py`.
Variables already set in the process environment take precedence. Restart the
running service after changing configuration.

Player search handles initial spacing (`J.Garner` versus `J. Garner`) and full
names whose stored form uses an initial (`Romeo Lavia` versus `R. Lavia`).
Multiple matching players still require clarification.

The assistant allows up to six data lookups and a final answer. Each model
response has a 4,096-token budget, including reasoning tokens. A response
truncated by that budget is retried once with 8,192 tokens before any partial
tool calls are executed. Further truncation produces a token-limit error,
not a claim that player data is missing. Truncation warnings appear in the
application logs.

The original GPT-5, GPT-5 mini, and GPT-5 nano aliases and dated snapshots use
low reasoning effort for interactive chat. Model requests allow up to 120
seconds of network inactivity, with a 10-second connection timeout. Automatic
SDK retries are disabled so a timeout does not silently repeat a long request.
Timeout messages and warnings identify OpenAI as the failing stage.

Start the service with `uvicorn scout_api:app`. Its OpenAPI description is at
`/docs`. Example requests:

```bash
curl 'http://localhost:8000/players?name=Haaland'
curl 'http://localhost:8000/leaderboard?metric=goals_per_90&season=2025&min_minutes=900'
curl 'http://localhost:8000/shortlist?role=defensive_mid&season=2025&max_age=24&exclude_team=Chelsea'
curl -X POST 'http://localhost:8000/scout/ask' \
  -H "X-Scout-API-Key: $SCOUT_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Compare the top scorers per 90 in the 2025 Premier League season."}'
```

Keep `SCOUT_API_KEY` on a trusted frontend server or API gateway, never in a
public browser bundle. For public access, proxy question requests through that
server and enforce user or IP rate limits and a spending budget at the gateway.
The API limits query size and tool calls, but these limits do not replace a
public traffic control layer. The Databricks identity needs `SELECT` on the
two gold objects, access to their catalog and schema, and permission to use
its SQL warehouse.

### Scout chat

`scout_chat_app.py` is a Streamlit chat over the same assistant. It keeps the
conversation in the browser session, sends the earlier turns with each
question, and shows the season rows behind each answer.

```bash
python -m pip install -r requirements.txt
python -m streamlit run scout_chat_app.py
```

The app calls the assistant in its own process, so it needs the Databricks
and OpenAI variables above but not `SCOUT_API_KEY`, and `scout_api.py` does
not have to be running. Anyone who can open the app can ask questions, so
put it behind your own sign-in. `app.yaml` starts it as a Databricks App.
