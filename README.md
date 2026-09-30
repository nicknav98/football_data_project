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
