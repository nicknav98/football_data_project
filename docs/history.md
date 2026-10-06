# History

## API-Football to Sportmonks, October 2026

The pipeline was first built on API-Football.

| Problem with API-Football | Effect | With Sportmonks |
| --- | --- | --- |
| Positions are only G, D, M, F | The scout guessed roles from statistics | Each profile has a detailed position, such as Defensive Midfield |
| A zero statistic is left blank | Gold left those matches' minutes out of per 90 rates, inflating them | The sync writes the zeros |
| Few statistics per player | No touches, recoveries, aerials, final-third passes | 27 more statistics per match |
| No team context | Defensive counts favoured teams with less of the ball | Team possession per match, and possession-adjusted rates |

### The inflation, measured

2025/26 season:

| Player | Goals per 90, API-Football gold | Goals ÷ minutes × 90 |
| --- | --- | --- |
| Erling Haaland | 1.42 | 0.82 |
| Declan Rice | 1.39 | 0.12 |

Tackles and interceptions were overstated the same way, by less. Minutes,
appearances, and goals agreed between the two providers.

### What remains from API-Football

| Item | State |
| --- | --- |
| Client and Databricks job | Removed |
| Tables in `workspace.football_data_project` | Kept, no longer updated. Their per 90 rates are inflated; do not use them. |
| Files under the `football-matchday-stats` S3 prefix | Kept, no longer updated |
| CSV column names (`goals_total`, `tackles_interceptions`, …) | Kept, so the tables did not have to change |
| League IDs 39, 140, 78, 135, 61 | Kept as the project's own IDs |

### Differences in the numbers

| Statistic | Difference |
| --- | --- |
| Shots | Sportmonks' total includes blocked shots, so it runs higher |
| Player, team, fixture IDs | Different. The two providers' rows cannot be joined on ID. |
