# Operations

## Deploy

```bash
databricks bundle validate
databricks bundle deploy            # dev
databricks bundle deploy -t prod
databricks bundle run sportmonks_ingest -t prod
```

Deploying uploads the scripts and notebook, so the job runs the deployed commit.

## Routine

| When | What | Where |
| --- | --- | --- |
| Every few hours | `python sync_matchday_stats.py` | One local machine |
| Weekly | `python sync_player_profiles.py` | Same machine |
| Daily | Sportmonks Ingest | Databricks, scheduled |
| After `databricks_gold_player_summaries.sql` changes | Rerun it | Databricks SQL editor |

Run the sync on one machine only. Each machine keeps its own fetch record, so
a second one fetches every fixture again.

`com.footballdata.matchdaysync.plist` schedules the sync on macOS.

## Sportmonks limits

| Fact | Detail |
| --- | --- |
| Allowance | A set number of requests per entity per hour (2,000 on the current plan) |
| Counted separately | Fixtures, leagues, teams, squads |
| At zero | The sync waits for the reset and continues |
| On HTTP 429 with no reset time | Waits five minutes, up to three retries |
| Full refetch | About 3,900 fixture requests: two to three hours |

## Fetch everything again

Needed after the sync starts writing new columns.

1. Deploy the new code to prod first.
2. Move or delete `state/sportmonks/processed_fixtures.json`.
3. Run `python sync_matchday_stats.py`. It resumes if interrupted.
4. Run the job. The bronze matchday task fails once on new columns and passes on retry.
5. Rerun the gold SQL.

Deploying after step 3 would let the old loader read the new files and drop
the new columns.

## Rebuild silver

Run the job with the `silver` task's `full_refresh` parameter set to `true`.

## Force a full volume copy

Delete `_checkpoints/s3_volume_sync/copied_etags.json` in the schema's volume.

## Known data gaps

| Gap | Effect |
| --- | --- |
| Lineup entries with no Sportmonks player ID | Skipped and logged. About 120 player-match rows across three seasons. |
| Abandoned and awarded fixtures | No player rows. Three so far. |
| Part reported above its whole | About 30 rows. Flagged in silver, left as reported. |
| Players with no profile | No age or position in gold. A handful. |
| Profiles with no detailed position | About 3%. Those players appear in no role shortlist. |
| Blank in profiles | `birth_place`, `birth_country`, `injured` |

## Checks after a load

| Check | Expect |
| --- | --- |
| Bronze and silver matchday row counts | Equal to each other and to the rows in the local files |
| Rows with a null `player_id` | None |
| Duplicate keys in gold | None |
| A known player's minutes and goals | Match a public source |

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Sync returns "rate limit reached" at once | Another machine is running the sync | Stop it; keep one |
| Bronze task fails with a null key | A file has a blank or malformed ID | Fix the file and re-upload |
| Bronze task fails once, then passes | New columns in the files | None needed |
| Gold SQL fails on a missing column | Silver has not loaded files with that column | Run the job first |
| Scout fails with table not found | Gold views missing in `SCOUT_GOLD_SCHEMA` | Run the gold SQL |
