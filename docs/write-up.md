# Project write-up

A scouting assistant for five European football leagues: from a sports data
API, through a Databricks lakehouse, to a chat that answers questions such as
"Compare Alex Scott to James Garner" with figures it cannot get wrong.

Built from 2026-09-04 to 2026-10-14. The project is now paused: it ran on a
Sportmonks trial, and the data stops at the sixth matchday of 2026/27.

## At a glance

| | |
| --- | --- |
| Leagues | Premier League, La Liga, Bundesliga, Serie A, Ligue 1 |
| Seasons | 2024/25, 2025/26, and the start of 2026/27 |
| Data | 161,150 player-match rows; 9,453 player-season summaries; about 70 statistics per player per match |
| Stack | Python, Sportmonks API, AWS S3, Databricks (Asset Bundles, Unity Catalog, jobs, SQL, Apps), FastAPI, Streamlit, OpenAI, Vega-Lite |
| Delivery | 24 pull requests, 88 unit tests, a scheduled sync every three hours, a daily Databricks job |

## The problem

Football statistics are easy to collect and easy to misuse. A player who
scored twice in 200 minutes looks better than one who scored 20 in a season.
A defender at a team that rarely has the ball makes more tackles without being
better at tackling. And a language model asked to compare two players will
happily invent a number.

I wanted a tool that answers a scout's question in plain language, where every
figure is correct, fair to compare, and honest about how much it can be
trusted.

## What I built

| Step | What happens |
| --- | --- |
| 1. Sync | A Python client fetches fixtures, player match statistics and profiles from Sportmonks, and writes CSV files to S3. A Windows scheduled task runs it every three hours and only fetches what changed. |
| 2. Bronze | A daily Databricks job copies the files into Unity Catalog volumes and loads them into tables, with schema evolution for new columns. |
| 3. Silver | One clean, typed row per player per match, with rows that fail quality checks flagged rather than dropped. |
| 4. Gold | One row per player, league and season: totals, per-90 rates, percentages, and possession-adjusted defensive rates. |
| 5. Scout | An API and a chat app. The model decides which lookups to run and writes the prose; code supplies every number. |

The Databricks side is defined as code (an Asset Bundle), with separate
development and production targets.

## Design decisions worth explaining

### The model never types a number

Early answers from the chat got figures wrong or rounded them oddly. Instead of
asking the model to be more careful, I took the numbers away from it. The model
writes a marker, such as "his tackles go here", and code replaces each marker
with the figure from the database. Code also adds a table of the figures and a
list of the sources. If the model types a figure itself, the answer is marked
"Not verified".

The same rule covers the judgement words. "High" or "below average" comes
from code, from fixed percentile thresholds, not from the model's impression.
So does the choice of each player's weakest statistic, after the model once
named the wrong one.

### Fair comparisons

| Problem | What the scout does |
| --- | --- |
| Players have different minutes | Every count is per 90 minutes |
| A defender's team rarely has the ball | Tackles and interceptions are adjusted for the opponent's possession in each match |
| A centre-back and a striker do different jobs | A percentile ranks a player only against players in the same position, that season, across all five leagues |
| A few good games look like a great season | Rows with too few minutes are flagged, and get a range and a "shrunk" estimate pulled toward the position average |
| Charts invite unfair visual comparisons | Two players share a chart only if their positions are related; a centre-back and a striker do not |

The methods (Poisson and Wilson intervals, shrinkage toward the group average)
are written up in plain language in [Statistical method](analyst.md).

### Checking the data against its source

Most pipelines check each table against the one before it. I compared every
layer against the original files instead, because two tables can agree with
each other and both be wrong. A reconcile script compares row counts, keys,
columns and minutes across files, bronze, silver and gold, and spot-checks
known players' goals and minutes.

That check caught real problems:

| What happened | How it was found | Fix |
| --- | --- | --- |
| One blank player ID made a whole ID column decimal in 111 files; bronze read those IDs as null, and de-duplication merged each team's players in a match into one row. **About 45,000 rows were lost**, while fixture counts still looked right. | Bronze held 113,731 rows where the files had about 159,000 | The sync writes whole-number IDs; the loader fails a batch with a null key |
| The first provider, API-Football, left zero statistics blank, so gold left those matches out of per-90 rates. **Declan Rice showed 1.39 goals per 90; the true figure was 0.12.** | Comparing gold with a hand calculation | Moved to Sportmonks, which reports zeros, and documented the migration in [History](history.md) |

## What I would do next

| Idea | Why |
| --- | --- |
| A regression suite for the chat | Testing the chat meant deploying and reading answers by hand. A fixed set of questions, with figures checked by code, would catch regressions. |
| Let code choose what each answer discusses | Answers were correct but thin: they sometimes skipped a player's strongest statistics, or failed to point to a fuller season when one was available. |
| Similar-player search | Find players whose percentile profile matches a target player's |
| Run the gold SQL inside the daily job | It was run by hand |

## What I learned

| Lesson | In practice |
| --- | --- |
| Constrain a language model with structure, not instructions | Better prompts gave better prose but still wrong figures. Markers that code fills in made the figures correct. |
| Verify against the source | A pipeline can run green while losing a third of its rows |
| Make the honest answer the default | Small samples, ranges and position groups are in the data the model receives, so it cannot leave them out |
| Check claims against the platform | My docs said the chat was open to anyone; it had been behind sign-in all along |

## Where to look

| Page | Contents |
| --- | --- |
| [README](../README.md) | How to run it |
| [Statistical method](analyst.md) | How each number is calculated, and its limits |
| [Scout](scout.md) | The API, the chat, markers, charts |
| [Pipeline](pipeline.md) | Sync, S3 layout, Databricks job, tables |
| [History](history.md) | Why the project moved from API-Football to Sportmonks |
