## Football Data Project

### Compare players in the browser

The comparison UI reads matchday CSV files directly from the S3 bucket used
by `sync_matchday_stats.py`. Configure `AWS_S3_BUCKET`, `AWS_S3_PREFIX` (optional),
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_REGION` in `.env` or
`.dotenv`. Shell environment variables take precedence. IAM credentials from
the usual boto3 provider chain also work. The AWS principal needs
`s3:ListBucket` on the bucket and `s3:GetObject` on the CSV objects.

```bash
python -m pip install -r requirements.txt
python -m streamlit run compare_players_app.py
```

Use the sidebar to filter leagues, seasons, teams, and matchdays. Select up to ten
players and the stat columns to compare. Counting stats can be shown as totals
or per 90 minutes. Rating is averaged across matches; pass accuracy is weighted
by passes attempted where available. The comparison can be downloaded as CSV.

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
objects are left in S3. The comparison app and Databricks reader use only the
current nested matchday layout; run the sync to completion before relying on them.
The Databricks merge key also includes league and season. Use a fresh Auto Loader
checkpoint and schema location when switching an existing stream to this layout.

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

Run the silver notebook, `Silver Layer Matchday Stats By League.ipynb`, after
the bronze matchday load. Run `databricks_player_profiles.py` so the profile
table exists. Then execute `databricks_gold_player_summaries.sql` in a
Databricks SQL editor using a Pro or Serverless SQL warehouse. Its first
statement creates `gold_player_season_summary`, one row per player, league,
and season. Its second creates `gold_player_observed_summary`, one row per
player across only the league seasons present in the data.

The gold materialized view uses `TRIGGER ON UPDATE` to refresh after any of
the five silver tables or the profile table changes. The silver notebook
currently overwrites whole league tables. A direct row stream from those
tables would not safely carry corrections, so the gold layer uses triggered
materialized view refreshes. Databricks may use a full refresh after an
overwrite. This is a refreshable serving table, not an event stream. Run the
silver notebook again before creating gold if its tables were built by an
older notebook that replaced missing numeric values with zero.

The season summary deduplicates on league, season, fixture, team, and player.
It includes teams, appearances, starts, minutes, position, totals, per 90
rates, shooting and duel percentages, pass accuracy weighted by attempts,
and the latest available profile fields. Percentages use matches where both
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
name search, player season summaries, a metric leaderboard, a ranking metric
list, and a scouting question endpoint. The question endpoint uses fixed
read-only tools over the gold tables and returns the retrieved season rows
alongside its answer. Model-generated SQL cannot run. Questions are
independent; the service does not retain chat history. The data contains
statistical indicators and has no written scout observations or transfer
history.
Rankings require at least the requested minutes of coverage for per 90 stats.
Percentage rankings also require a minimum number of observed attempts or
rated matches.

Install `requirements.txt` and set these server-side environment variables:

| Variable | Purpose |
| --- | --- |
| `DATABRICKS_SERVER_HOSTNAME` | Databricks workspace hostname |
| `DATABRICKS_HTTP_PATH` | SQL warehouse HTTP path |
| `DATABRICKS_TOKEN` | Token with read access to the gold views |
| `OPENAI_API_KEY` | OpenAI API key |
| `OPENAI_MODEL` | Model available to your OpenAI project |
| `SCOUT_API_KEY` | Shared secret required by the question endpoint |

Start the service with `uvicorn scout_api:app`. Its OpenAPI description is at
`/docs`. Example requests:

```bash
curl 'http://localhost:8000/players?name=Haaland'
curl 'http://localhost:8000/leaderboard?metric=goals_per_90&season=2025&min_minutes=900'
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
