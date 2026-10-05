## Football Data Project

### Five league matchday sync

`sync_matchday_stats.py` fetches Premier League (39), La Liga (140), Bundesliga
(78), Serie A (135), and Ligue 1 (61) for `FOOTBALL_SEASON` (default 2026)
and the two preceding seasons. Set `FOOTBALL_HISTORY_SEASONS` to change
the history depth (default 2). With the defaults, it syncs 2024 through 2026.
It writes one CSV per matchday under `AWS_S3_PREFIX`, for example
`league_39/season_2026/ENG_PREMIER_LEAGUE_MATCHDAY_01.csv` and
`league_140/season_2026/ESP_LA_LIGA_MATCHDAY_01.csv`. For rounds without a
number, the suffix uses the round name, such as
`GER_BUNDESLIGA_MATCHDAY_RELEGATION_ROUND.csv`. Each row retains
`league_id`, `season`, and `fixture_id`. A player's appearances remain separate
by league, season, fixture, team, and player ID, including after transfers.
State lives in
`state/processed_fixtures.json`, keyed by `league_id:season:fixture_id`.

The first run with this layout refetches completed fixtures because prior state
entries do not represent matchday files. Existing fixture and older matchday
objects are left in S3. The Databricks reader uses only the
current nested matchday layout; run the sync to completion before relying on it.
The Databricks merge key also includes league and season. Use a fresh Auto Loader
checkpoint and schema location when switching an existing stream to this layout.

### Sportmonks as the data provider

Both sync scripts can read from Sportmonks instead of API-Football. Set these
in `.env`:

| Variable | Purpose |
| --- | --- |
| `FOOTBALL_DATA_PROVIDER` | `sportmonks`, or `api_football` (the default) |
| `SPORTMONKS_API_TOKEN` | Sportmonks API token |
| `SPORTMONKS_S3_PREFIX` | S3 prefix for Sportmonks files, required when the provider is `sportmonks` |

`sportmonks.py` converts Sportmonks responses to the API-Football layout, so
the CSV files keep their names and columns. League IDs (39, 140, 78, 135, 61)
and seasons (2025 for 2025/26) are unchanged. Fixture, team, and player IDs
are Sportmonks IDs, so the two providers' rows must never share a bronze
table. For that reason Sportmonks files go to their own S3 prefix, with state
in `state/sportmonks/` and local copies in `output/sportmonks/`. To cut over,
load them into empty bronze tables with new Auto Loader checkpoint and schema
locations, then rebuild silver and gold.

Differences from API-Football data:

- Sportmonks leaves a statistic out when it is zero. A count missing for a
  player who played is written as 0 when the fixture has detailed statistics.
  Saves and penalties saved are filled for goalkeepers only. A substitute who
  did not play has blank statistics.
- Matchday rows gain `games_detailed_position` and `games_formation_field`.
  The detailed position is the slot in the starting formation, such as
  Central Midfield. It is blank for substitutes and rarely says Defensive
  Midfield.
- Profiles gain `position` and `detailed_position`, the player's usual role,
  such as Defensive Midfield. Profiles come from each team's season squad.
  `birth_place`, `birth_country`, and `injured` are blank.
- A second yellow card adds one to `cards_red`.
- `tackles_blocks` is Sportmonks' blocked shots.

One fixture's statistics take one request, and a league season's fixture list
takes eight. Sportmonks allows a set number of requests per entity per hour.
When that runs out, the sync waits for the reset and continues.

### Deploying the Databricks job

`databricks.yml` and `resources/matchday_ingest.job.yml` define the MatchDay
Ingest job as a Databricks Asset Bundle. Deploying uploads the scripts and the
silver notebook and creates or updates the job, so the job always runs the
code in the deployed commit.

```bash
databricks bundle validate
databricks bundle deploy            # dev, the default target
databricks bundle run matchday_ingest
databricks bundle deploy -t prod
```

The job copies S3 files into the volumes, then loads player profiles,
fixtures, and matchday stats independently, then runs the silver notebook.
Each task receives the catalog and schema as parameters.

| Target | Job name | Schema | Schedule |
| --- | --- | --- | --- |
| `dev` | `[dev <user>] MatchDay Ingest` | `dev_<user>_football_data_project`, created by the bundle with its four volumes | Paused |
| `prod` | `MatchDay Ingest` | `football_data_project`, existing and not managed by the bundle | Daily |

The first `prod` deploy creates a new job beside any job made by hand in the
UI. To have the bundle take over an existing job instead, run
`databricks bundle deployment bind matchday_ingest <job id> -t prod` before
deploying. To reprocess all of bronze into silver, run the job with the
`silver` task's `full_refresh` parameter set to `true`.
`databricks_gold_player_summaries.sql` is not part of the bundle and names the
production schema directly.

### Copying S3 files into Databricks volumes

Run `databricks_volume_sync.py` in Databricks before the bronze loaders. It
copies matchday files to `football_data/<season>/`, fixture files to
`football_data/fixtures/`, and the profile file to `player_profiles_data/`.
The matchday Auto Loader reads only files named `*_MATCHDAY_*.csv`, so it
ignores the fixtures folder. It records
the S3 ETag of each copied file in
`_checkpoints/s3_volume_sync/copied_etags.json` and downloads a file again
only when its ETag has changed or its copy is missing. The first run copies
everything. Delete the manifest to force a full copy.

### Fixtures

Each sync also writes the full fixture list for every league and season to
`reference/fixtures/league_39_season_2026.csv` (and so on) under
`AWS_S3_PREFIX`. It needs no extra API requests. Each row has the kickoff time
in UTC, status, round, referee, venue, home and away teams, and the full-time
and half-time score. Unplayed fixtures are included with blank scores. A file
is uploaded again only when its content changes.

In Databricks, run `databricks_volume_sync.py` to copy these files into the
`fixtures` folder of the `football_data` volume, then run `databricks_fixtures.py` to upsert
`bronze_fixtures` by league, season, and fixture ID. Use its own Auto Loader schema and checkpoint locations. Matchday
statistics join to fixtures on `league_id`, `season`, and `fixture_id`; a
player's team is at home when `team_id` equals `home_team_id`.

### Silver layer

Run the silver notebook, `Silver Layer Matchday Stats By League.ipynb`, after
each bronze load. It maintains one table for all five leagues,
`silver_matchday_stats`, clustered by league and season. Each run merges only
the bronze rows ingested since the previous run, so corrections update rows in
place. Set the notebook's `full_refresh` parameter to `true` to reprocess every
bronze row, for example after changing a cleaning rule. Its `catalog` and
`schema` parameters select the schema to read and write.

Silver keeps one row per league, season, fixture, team, and player. Whole-number
statistics are stored as integers. A value outside its valid range (a negative
count, more than 130 minutes, a rating above 10) is replaced with null, and
the row's `quality_issues` array records the rule, for example
`games_rating_out_of_range`. A part that exceeds its whole, such as more shots
on target than shots or more accurate passes than passes, is recorded in `quality_issues` but left as
reported. The last notebook cell prints the count of each issue and fails if
any key is duplicated.

When `bronze_fixtures` exists, the notebook also maintains `silver_fixtures`
with a typed `kickoff_utc`, `match_date`, `is_finished`, and `result` (`H`,
`D`, or `A`).

This layout replaces the five per-league tables named
`silver_<league>_matchday_stats`. The first run builds `silver_matchday_stats`
from all of bronze. Then run `databricks_gold_player_summaries.sql` again so
gold reads the new table. After that the five old tables can be dropped.

### Player profiles

Run `python sync_player_profiles.py` to collect profiles for the same five
leagues and three seasons. The script reads every paginated `/players` response
and keeps one profile per player ID. A completed scan is cached for seven days
in `state/player_profiles.json`; set `PLAYER_PROFILE_CACHE_HOURS=0` to force a
new scan. Connection failures and HTTP 429 or 5xx responses are retried up to
three times.

The script uploads `reference/player_profiles/player_profiles.csv` under
`AWS_S3_PREFIX`. Profiles include age, birth date, nationality, and
`fetched_at`. Age is the value reported when the profile was fetched, not a
historical age for `source_season`. Matchday statistics remain in their
existing files and join to profiles by `player_id`.

In Databricks, run `databricks_player_profiles.py` to upsert
`bronze_player_profiles` by `player_id`. Use its own Auto Loader schema and
checkpoint locations, separate from matchday statistics.

### Gold player summaries

Run the silver notebook after the bronze matchday load. Run
`databricks_player_profiles.py` so the profile table exists. Then execute `databricks_gold_player_summaries.sql` in a
Databricks SQL editor using a Pro or Serverless SQL warehouse. Its first
statement creates `gold_player_season_summary`, one row per player, league,
and season. Its second creates `gold_player_observed_summary`, one row per
player across only the league seasons present in the data.

The gold materialized view uses `TRIGGER ON UPDATE` to refresh after the
silver table or the profile table changes. The silver notebook merges changed
rows and enables row tracking, so Databricks can refresh the view
incrementally where the query allows it. This is a refreshable serving table,
not an event stream.

The season summary relies on silver holding one row per league, season,
fixture, team, and player. It includes teams, appearances, starts, minutes,
position, totals, per 90 rates, shooting and duel percentages, pass accuracy
(`accurate_passes` over `passes_with_accuracy`, counting matches that report
both), and the latest available profile fields. It also has
offsides, blocks, times dribbled past, fouls drawn and committed, and
penalties won, committed, scored, missed, and saved. `non_penalty_goals` uses
only matches that report both goals and penalties scored. `save_pct` is saves
divided by saves plus goals conceded, counted in matches played as goalkeeper. Percentages use matches where both
parts of the ratio are present. Each per 90 rate uses minutes from matches
where that stat is present. The corresponding `*_observed_minutes` and
coverage columns show how much data supports a rate. An all missing stat
remains null. Profile age is age when fetched, not age during that season.
The observed summary is not a career total outside the loaded leagues and
seasons.

Check the result in Databricks SQL:

```sql
SELECT player_id, league_id, season, COUNT(*) AS rows_per_key
FROM workspace.football_data_project.gold_player_season_summary
GROUP BY player_id, league_id, season
HAVING COUNT(*) > 1;

SELECT player_id, player_name, league_name, season, appearances, minutes,
       goals, goals_observed_minutes, goals_per_90, profile_age, nationality
FROM workspace.football_data_project.gold_player_season_summary
WHERE minutes >= 450
ORDER BY goals_per_90 DESC
LIMIT 20;
```

The first query should return no rows. `silver_as_of` shows the latest silver
processing time in each summary. It does not guarantee that every fixture in
the source API has been ingested.

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

A shortlist scores players of one position for a role: `defensive_mid`,
`creative_mid`, `defender`, or `striker`. `role_score` is a 0 to 100 weighted
average of percentile ranks, taken among all players of that position in the
season with at least `min_minutes`, across all five leagues. League, age, and
club filters narrow the output without changing a score. The weights are in
`ROLE_PROFILES` in `scout_backend.py`. Positions in the data are only
goalkeeper, defender, midfielder, and forward, so a role is a statistical
profile, not a recorded position.

Install `requirements.txt` and set these server-side environment variables:

| Variable | Purpose |
| --- | --- |
| `DATABRICKS_SERVER_HOSTNAME` | Databricks workspace hostname |
| `DATABRICKS_HTTP_PATH` | SQL warehouse HTTP path |
| `DATABRICKS_TOKEN` | Token with read access to the gold views |
| `OPENAI_API_KEY` | OpenAI API key |
| `OPENAI_MODEL` | Model available to your OpenAI project |
| `SCOUT_API_KEY` | Shared secret required by the question endpoint |

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
