# Football Data Project

Player statistics for five European leagues, from Sportmonks to a scouting
assistant.

## How it works

| Step | What happens | Where |
| --- | --- | --- |
| 1. Sync | Fetch fixtures, player match statistics, and profiles. Write CSV files to S3. | `sync_matchday_stats.py`, `sync_player_profiles.py`, `sportmonks.py` |
| 2. Bronze | Copy the files into Databricks volumes and load them into tables. | `databricks_*.py`, run by the Sportmonks Ingest job |
| 3. Silver | Clean and type one row per player per match. | `Silver Layer Matchday Stats By League.ipynb` |
| 4. Gold | Summarise each player's season: totals, per 90 rates, percentages. | `databricks_gold_player_summaries.sql` |
| 5. Scout | Answer scouting questions from gold, over HTTP or chat. | `scout_api.py`, `scout_backend.py`, `scout_chat_app.py` |

## Coverage

| | |
| --- | --- |
| Leagues | Premier League (39), La Liga (140), Bundesliga (78), Serie A (135), Ligue 1 (61) |
| Seasons | 2024/25, 2025/26, 2026/27 (stored as 2024, 2025, 2026) |
| Grain | One row per player per match; one gold row per player, league, and season |
| Provider | Sportmonks v3 |

## Documentation

| Page | Contents |
| --- | --- |
| [For analysts](docs/analyst.md) | The statistical method: rates, possession adjustment, percentiles, role scores, and their limits. Start here with questions about how a number is computed. |
| [Statistics](docs/statistics.md) | What is collected, the gold metrics, and the scouting questions they answer |
| [Pipeline](docs/pipeline.md) | Sync, S3 layout, Databricks job, tables, configuration |
| [Scout](docs/scout.md) | API endpoints, roles, chat app, configuration |
| [Operations](docs/operations.md) | Deploying, refetching, rate limits, known data gaps |
| [History](docs/history.md) | Why the project moved from API-Football to Sportmonks |

## Quick start

```bash
python -m pip install -r requirements.txt
python sync_matchday_stats.py          # fixtures and match statistics to S3
python sync_player_profiles.py         # player profiles to S3
databricks bundle deploy -t prod       # create or update the Databricks job
databricks bundle run sportmonks_ingest -t prod
python -m streamlit run scout_chat_app.py
```

Settings go in `.env` at the project root. See [Pipeline](docs/pipeline.md#configuration)
and [Scout](docs/scout.md#configuration).

## Repository layout

| Path | Contents |
| --- | --- |
| `sync_*.py`, `sportmonks.py`, `scheduled_sync.py` | Local sync from Sportmonks to S3, and its scheduled wrapper |
| `databricks_*.py`, `*.ipynb`, `*.sql` | Code that runs in Databricks |
| `databricks.yml`, `resources/` | Databricks Asset Bundle: schema, volumes, job |
| `scout_*.py`, `app.yaml` | Scout API and chat app |
| `tests/` | Unit tests |
| `docs/` | Documentation |

## Tests

```bash
python -m unittest
```
