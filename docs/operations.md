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
| Every three hours | `scheduled_sync.py`: match statistics, and profiles when the last scan is over seven days old | Windows scheduled task on one PC |
| Daily | Sportmonks Ingest | Databricks, scheduled |
| After `databricks_gold_player_summaries.sql` changes | Rerun it | Databricks SQL editor |

Run the sync on one machine only. Each machine keeps its own fetch record, so
a second one fetches every fixture again.

## Scheduled sync on Windows

| | |
| --- | --- |
| Task | `Football Data Sync` in Task Scheduler |
| Runs | `.venv\Scripts\pythonw.exe scheduled_sync.py` in the project folder, every three hours |
| Log | `logs\sync.log`; set aside as `sync.previous.log` above 5 MB |
| Code | Whatever branch is checked out in the project folder. Keep it on `prod`. |
| Missed runs | Run when the PC is next on. Nothing runs while it is off or asleep. |
| Overlap | A run still going when the next is due is left to finish |

```powershell
Get-ScheduledTask -TaskName "Football Data Sync" | Get-ScheduledTaskInfo   # last and next run
Start-ScheduledTask -TaskName "Football Data Sync"                         # run now
Disable-ScheduledTask -TaskName "Football Data Sync"                       # pause
Unregister-ScheduledTask -TaskName "Football Data Sync"                    # remove
```

To create it on another PC:

```powershell
$root = "C:\path\to\football_data_project"
$action = New-ScheduledTaskAction -Execute "$root\.venv\Scripts\pythonw.exe" -Argument "scheduled_sync.py" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 3)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -RunOnlyIfNetworkAvailable
Register-ScheduledTask -TaskName "Football Data Sync" -Action $action -Trigger $trigger -Settings $settings
```

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
| Scheduled sync does nothing | The PC was off, or the task is disabled | Check `logs\sync.log` and the task's last run |
| Bronze task fails with a null key | A file has a blank or malformed ID | Fix the file and re-upload |
| Bronze task fails once, then passes | New columns in the files | None needed |
| Gold SQL fails on a missing column | Silver has not loaded files with that column | Run the job first |
| Scout fails with table not found | Gold views missing in `SCOUT_GOLD_SCHEMA` | Run the gold SQL |
