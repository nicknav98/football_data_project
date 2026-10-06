# Pipeline

Sportmonks → CSV files in S3 → Databricks bronze → silver → gold.

## Configuration

Set in `.env` at the project root, or in the environment.

| Variable | Purpose | Default |
| --- | --- | --- |
| `SPORTMONKS_API_TOKEN` | Sportmonks API token | required |
| `SPORTMONKS_S3_PREFIX` | S3 prefix for the files | required; use `sportmonks/football-matchday-stats` |
| `AWS_S3_BUCKET` | S3 bucket | required |
| `AWS_REGION` | AWS region | boto3 default |
| `FOOTBALL_SEASON` | Latest season to sync, by starting year | `2026` |
| `FOOTBALL_HISTORY_SEASONS` | Earlier seasons to sync as well | `2` |
| `PLAYER_PROFILE_CACHE_HOURS` | How long a profile scan is reused | `168` |

AWS credentials come from the boto3 provider chain.

## 1. Sync

Runs on one local machine.

| Script | Fetches | Requests |
| --- | --- | --- |
| `sync_matchday_stats.py` | Fixture lists and player statistics per fixture | 8 per league season, plus 1 per fixture |
| `sync_player_profiles.py` | Every team's season squad | About 21 per league season |

| Behaviour | Detail |
| --- | --- |
| What is fetched | A matchday with a finished fixture not yet recorded, or one that kicked off under 12 hours ago |
| Finished means | Sportmonks state FT, AET, or FT_PEN. Abandoned and awarded fixtures get no player rows. |
| Fetch record | `state/sportmonks/processed_fixtures.json`, keyed `league_id:season:fixture_id` |
| Profile cache | `state/sportmonks/player_profiles.json`, reused for seven days |
| Local copies | `output/sportmonks/` |
| IDs | League IDs and seasons are the project's own. Fixture, team, and player IDs are Sportmonks'. |

### Files written to S3

Under `SPORTMONKS_S3_PREFIX`:

| File | Contents |
| --- | --- |
| `league_<id>/season_<year>/<COUNTRY>_<LEAGUE>_MATCHDAY_<NN>.csv` | One row per player per fixture in the matchday. Replaced as a whole. |
| `reference/fixtures/league_<id>_season_<year>.csv` | Every fixture in the league season, played or not |
| `reference/player_profiles/player_profiles.csv` | One row per player |

Columns are listed in [Statistics](statistics.md).

## 2. Databricks job: Sportmonks Ingest

Defined in `databricks.yml` and `resources/sportmonks_ingest.job.yml`.

| Task | Script | Result |
| --- | --- | --- |
| `copy_s3_data` | `databricks_volume_sync.py` | Copies new or changed S3 files into the volumes |
| `ingest_player_profiles` | `databricks_player_profiles.py` | Upserts `bronze_player_profiles` by player |
| `ingest_fixtures` | `databricks_fixtures.py` | Upserts `bronze_fixtures` by league, season, fixture |
| `ingest_matchday_stats` | `databricks_matchday_stream.py` | Upserts `bronze_matchday_stats` by league, season, fixture, team, player |
| `silver` | `Silver Layer Matchday Stats By League.ipynb` | Merges changed rows into `silver_matchday_stats` and `silver_fixtures` |

| Target | Job name | Schema | Schedule |
| --- | --- | --- | --- |
| `dev` | `[dev <user>] Sportmonks Ingest` | `dev_<user>_football_data_project_sportmonks` | Paused |
| `prod` | `Sportmonks Ingest` | `football_data_project_sportmonks` | Daily |

The bundle creates the schema and four volumes (`football_data`,
`player_profiles_data`, `_checkpoints`, `_schemas`) in both targets.

### Bronze

| Rule | Detail |
| --- | --- |
| Volume copy | Downloads a file only when its S3 ETag changed. Record: `_checkpoints/s3_volume_sync/copied_etags.json`. |
| Matchday files | Only `*_MATCHDAY_*.csv` under a season folder |
| Null keys | The matchday load fails if a key column is null |
| New columns | Added to bronze. Auto Loader stops once when it first sees them; the task retries. |

### Silver

| Rule | Detail |
| --- | --- |
| Grain | One row per league, season, fixture, team, player |
| Incremental | Merges only bronze rows ingested since the last run |
| Full rebuild | Run the job with the `silver` task's `full_refresh` set to `true` |
| Out of range | A negative count, over 130 minutes, a rating over 10, or possession outside 0 to 100 becomes null. The rule is recorded in `quality_issues`. |
| Part above whole | Flagged in `quality_issues`, left as reported |
| Duplicate keys | The last cell fails the run |
| Fixtures | `silver_fixtures` adds `kickoff_utc`, `match_date`, `is_finished`, `result` (H, D, A) |

## 3. Gold

Not part of the job. Run `databricks_gold_player_summaries.sql` once per schema
in a Databricks SQL editor, on a Pro or Serverless warehouse.

```sql
USE workspace.football_data_project_sportmonks;
```

| Object | Grain | Refresh |
| --- | --- | --- |
| `gold_player_season_summary` | Player, league, season | Materialized view, refreshes when silver or profiles change |
| `gold_player_observed_summary` | Player, across loaded seasons | View over the season summary |

Rerun the file after it changes. It fails if silver lacks a column it reads.

Checks:

```sql
-- Should return no rows.
SELECT player_id, league_id, season, COUNT(*)
FROM workspace.football_data_project_sportmonks.gold_player_season_summary
GROUP BY player_id, league_id, season
HAVING COUNT(*) > 1;
```

## Tables

All in `workspace.football_data_project_sportmonks`.

| Table | Layer | Grain |
| --- | --- | --- |
| `bronze_matchday_stats` | Bronze | Player per fixture |
| `bronze_fixtures` | Bronze | Fixture |
| `bronze_player_profiles` | Bronze | Player |
| `silver_matchday_stats` | Silver | Player per fixture |
| `silver_fixtures` | Silver | Fixture |
| `gold_player_season_summary` | Gold | Player, league, season |
| `gold_player_observed_summary` | Gold | Player |
