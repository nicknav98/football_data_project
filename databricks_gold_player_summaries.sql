/* Run after all five silver tables and bronze_player_profiles exist.
   The materialized view refreshes when a source table changes. */
CREATE OR REPLACE MATERIALIZED VIEW workspace.football_data_project.gold_player_season_summary
TRIGGER ON UPDATE
AS
WITH all_matchdays AS (
    SELECT * FROM workspace.football_data_project.silver_premier_league_matchday_stats
    UNION ALL
    SELECT * FROM workspace.football_data_project.silver_la_liga_matchday_stats
    UNION ALL
    SELECT * FROM workspace.football_data_project.silver_bundesliga_matchday_stats
    UNION ALL
    SELECT * FROM workspace.football_data_project.silver_serie_a_matchday_stats
    UNION ALL
    SELECT * FROM workspace.football_data_project.silver_ligue_1_matchday_stats
),
ranked_matchdays AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY league_id, season, fixture_id, team_id, player_id
            ORDER BY silver_processing_time DESC, ingestion_time DESC
        ) AS row_rank
    FROM all_matchdays
),
matchdays AS (
    SELECT * FROM ranked_matchdays WHERE row_rank = 1
),
position_minutes AS (
    SELECT
        player_id,
        league_id,
        season,
        games_position,
        SUM(CASE WHEN games_minutes >= 0 THEN games_minutes ELSE 0 END) AS minutes_at_position
    FROM matchdays
    WHERE games_position IS NOT NULL AND games_position <> ''
    GROUP BY player_id, league_id, season, games_position
),
ranked_positions AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY player_id, league_id, season
            ORDER BY minutes_at_position DESC, games_position
        ) AS position_rank
    FROM position_minutes
),
season_totals AS (
    SELECT
        player_id,
        league_id,
        season,
        MAX(league_name) AS league_name,
        MAX_BY(player_name, silver_processing_time) AS matchday_player_name,
        ARRAY_SORT(COLLECT_SET(team_name)) AS team_names,
        COUNT(DISTINCT team_id) AS teams_played_for,
        COUNT(*) AS matches_in_data,
        COUNT_IF(games_minutes > 0) AS appearances,
        COUNT_IF(games_minutes > 0 AND games_substitute = false) AS starts,
        COUNT_IF(games_minutes > 0 AND games_substitute = true) AS substitute_appearances,
        COUNT_IF(games_minutes IS NOT NULL AND games_minutes >= 0) AS matches_with_minutes,
        COUNT_IF(games_minutes IS NULL OR games_minutes < 0) AS matches_missing_valid_minutes,
        SUM(CASE WHEN games_minutes >= 0 THEN games_minutes ELSE 0 END) AS minutes,
        CASE WHEN COUNT(goals_total) > 0 THEN SUM(goals_total) END AS goals,
        COUNT(goals_total) AS matches_with_goals_stat,
        SUM(CASE WHEN goals_total IS NOT NULL AND games_minutes >= 0 THEN games_minutes ELSE 0 END) AS goals_observed_minutes,
        CASE WHEN COUNT(goals_assists) > 0 THEN SUM(goals_assists) END AS assists,
        COUNT(goals_assists) AS matches_with_assists_stat,
        SUM(CASE WHEN goals_assists IS NOT NULL AND games_minutes >= 0 THEN games_minutes ELSE 0 END) AS assists_observed_minutes,
        CASE WHEN COUNT(shots_total) > 0 THEN SUM(shots_total) END AS shots,
        CASE WHEN COUNT(shots_on) > 0 THEN SUM(shots_on) END AS shots_on_target,
        SUM(CASE WHEN shots_total IS NOT NULL AND games_minutes >= 0 THEN games_minutes ELSE 0 END) AS shots_observed_minutes,
        SUM(CASE WHEN shots_total IS NOT NULL AND shots_on IS NOT NULL THEN shots_total END) AS shots_with_on_target_data,
        SUM(CASE WHEN shots_total IS NOT NULL AND shots_on IS NOT NULL THEN shots_on END) AS paired_shots_on_target,
        CASE WHEN COUNT(passes_total) > 0 THEN SUM(passes_total) END AS passes_attempted,
        CASE WHEN COUNT(passes_key) > 0 THEN SUM(passes_key) END AS key_passes,
        SUM(CASE WHEN passes_key IS NOT NULL AND games_minutes >= 0 THEN games_minutes ELSE 0 END) AS key_passes_observed_minutes,
        CASE WHEN COUNT(tackles_total) > 0 THEN SUM(tackles_total) END AS tackles,
        SUM(CASE WHEN tackles_total IS NOT NULL AND games_minutes >= 0 THEN games_minutes ELSE 0 END) AS tackles_observed_minutes,
        CASE WHEN COUNT(tackles_interceptions) > 0 THEN SUM(tackles_interceptions) END AS interceptions,
        SUM(CASE WHEN tackles_interceptions IS NOT NULL AND games_minutes >= 0 THEN games_minutes ELSE 0 END) AS interceptions_observed_minutes,
        CASE WHEN COUNT(duels_total) > 0 THEN SUM(duels_total) END AS duels,
        CASE WHEN COUNT(duels_won) > 0 THEN SUM(duels_won) END AS duels_won,
        SUM(CASE WHEN duels_total IS NOT NULL AND duels_won IS NOT NULL THEN duels_total END) AS duels_with_won_data,
        SUM(CASE WHEN duels_total IS NOT NULL AND duels_won IS NOT NULL THEN duels_won END) AS paired_duels_won,
        CASE WHEN COUNT(dribbles_attempts) > 0 THEN SUM(dribbles_attempts) END AS dribbles_attempted,
        CASE WHEN COUNT(dribbles_success) > 0 THEN SUM(dribbles_success) END AS dribbles_successful,
        SUM(CASE WHEN dribbles_attempts IS NOT NULL AND dribbles_success IS NOT NULL THEN dribbles_attempts END) AS dribbles_with_success_data,
        SUM(CASE WHEN dribbles_attempts IS NOT NULL AND dribbles_success IS NOT NULL THEN dribbles_success END) AS paired_dribbles_successful,
        CASE WHEN COUNT(goals_saves) > 0 THEN SUM(goals_saves) END AS saves,
        SUM(CASE WHEN goals_saves IS NOT NULL AND games_minutes >= 0 THEN games_minutes ELSE 0 END) AS saves_observed_minutes,
        CASE WHEN COUNT(goals_conceded) > 0 THEN SUM(goals_conceded) END AS goals_conceded,
        CASE WHEN COUNT(cards_yellow) > 0 THEN SUM(cards_yellow) END AS yellow_cards,
        CASE WHEN COUNT(cards_red) > 0 THEN SUM(cards_red) END AS red_cards,
        ROUND(AVG(games_rating), 2) AS average_rating,
        COUNT(games_rating) AS matches_with_rating,
        SUM(CASE
            WHEN passes_total > 0 AND passes_accuracy BETWEEN 0 AND 100
            THEN passes_total * passes_accuracy ELSE 0
        END) AS weighted_pass_accuracy_points,
        SUM(CASE
            WHEN passes_total > 0 AND passes_accuracy BETWEEN 0 AND 100
            THEN passes_total ELSE 0
        END) AS passes_with_accuracy,
        MAX(silver_processing_time) AS silver_as_of
    FROM matchdays
    GROUP BY player_id, league_id, season
)
SELECT
    s.player_id,
    s.league_id,
    s.league_name,
    s.season,
    COALESCE(p.name, s.matchday_player_name) AS player_name,
    r.games_position AS primary_position,
    s.team_names,
    s.teams_played_for,
    s.matches_in_data,
    s.appearances,
    s.starts,
    s.substitute_appearances,
    s.matches_with_minutes,
    s.matches_missing_valid_minutes,
    s.minutes,
    s.goals,
    s.matches_with_goals_stat,
    s.goals_observed_minutes,
    s.assists,
    s.matches_with_assists_stat,
    s.assists_observed_minutes,
    s.shots,
    s.shots_on_target,
    s.shots_observed_minutes,
    s.shots_with_on_target_data,
    s.passes_attempted,
    s.key_passes,
    s.key_passes_observed_minutes,
    s.tackles,
    s.tackles_observed_minutes,
    s.interceptions,
    s.interceptions_observed_minutes,
    s.duels,
    s.duels_won,
    s.duels_with_won_data,
    s.dribbles_attempted,
    s.dribbles_successful,
    s.dribbles_with_success_data,
    s.saves,
    s.saves_observed_minutes,
    s.goals_conceded,
    s.yellow_cards,
    s.red_cards,
    s.average_rating,
    s.matches_with_rating,
    s.passes_with_accuracy,
    CASE WHEN s.passes_with_accuracy > 0
        THEN ROUND(s.weighted_pass_accuracy_points / s.passes_with_accuracy, 1)
    END AS pass_accuracy_pct,
    CASE WHEN s.shots_with_on_target_data > 0
        THEN ROUND(100.0 * s.paired_shots_on_target / s.shots_with_on_target_data, 1)
    END AS shots_on_target_pct,
    CASE WHEN s.duels_with_won_data > 0
        THEN ROUND(100.0 * s.paired_duels_won / s.duels_with_won_data, 1)
    END AS duel_win_pct,
    CASE WHEN s.dribbles_with_success_data > 0
        THEN ROUND(100.0 * s.paired_dribbles_successful / s.dribbles_with_success_data, 1)
    END AS dribble_success_pct,
    CASE WHEN s.goals_observed_minutes > 0
        THEN ROUND(90.0 * s.goals / s.goals_observed_minutes, 2)
    END AS goals_per_90,
    CASE WHEN s.assists_observed_minutes > 0
        THEN ROUND(90.0 * s.assists / s.assists_observed_minutes, 2)
    END AS assists_per_90,
    CASE WHEN s.shots_observed_minutes > 0
        THEN ROUND(90.0 * s.shots / s.shots_observed_minutes, 2)
    END AS shots_per_90,
    CASE WHEN s.key_passes_observed_minutes > 0
        THEN ROUND(90.0 * s.key_passes / s.key_passes_observed_minutes, 2)
    END AS key_passes_per_90,
    CASE WHEN s.tackles_observed_minutes > 0
        THEN ROUND(90.0 * s.tackles / s.tackles_observed_minutes, 2)
    END AS tackles_per_90,
    CASE WHEN s.interceptions_observed_minutes > 0
        THEN ROUND(90.0 * s.interceptions / s.interceptions_observed_minutes, 2)
    END AS interceptions_per_90,
    CASE WHEN s.saves_observed_minutes > 0
        THEN ROUND(90.0 * s.saves / s.saves_observed_minutes, 2)
    END AS saves_per_90,
    p.age AS profile_age,
    TRY_CAST(p.birth_date AS DATE) AS birth_date,
    p.nationality,
    TRY_CAST(p.fetched_at AS TIMESTAMP) AS profile_fetched_at,
    s.silver_as_of
FROM season_totals s
LEFT JOIN ranked_positions r
    ON s.player_id = r.player_id
    AND s.league_id = r.league_id
    AND s.season = r.season
    AND r.position_rank = 1
LEFT JOIN workspace.football_data_project.bronze_player_profiles p
    ON s.player_id = p.player_id;

/* This view summarizes only the seasons and leagues present in the gold table. */
CREATE OR REPLACE VIEW workspace.football_data_project.gold_player_observed_summary AS
SELECT
    player_id,
    MAX_BY(player_name, season) AS player_name,
    MAX(profile_age) AS profile_age,
    MAX(nationality) AS nationality,
    MIN(season) AS first_season_in_data,
    MAX(season) AS last_season_in_data,
    COUNT(DISTINCT season) AS seasons_in_data,
    COUNT(*) AS league_seasons_in_data,
    ARRAY_SORT(COLLECT_SET(league_name)) AS leagues_in_data,
    SUM(matches_in_data) AS matches_in_data,
    SUM(appearances) AS appearances,
    SUM(starts) AS starts,
    SUM(minutes) AS minutes,
    SUM(matches_with_minutes) AS matches_with_minutes,
    SUM(goals) AS goals,
    SUM(matches_with_goals_stat) AS matches_with_goals_stat,
    SUM(goals_observed_minutes) AS goals_observed_minutes,
    SUM(assists) AS assists,
    SUM(matches_with_assists_stat) AS matches_with_assists_stat,
    SUM(assists_observed_minutes) AS assists_observed_minutes,
    SUM(shots) AS shots,
    SUM(shots_observed_minutes) AS shots_observed_minutes,
    SUM(key_passes) AS key_passes,
    SUM(key_passes_observed_minutes) AS key_passes_observed_minutes,
    SUM(tackles) AS tackles,
    SUM(tackles_observed_minutes) AS tackles_observed_minutes,
    SUM(interceptions) AS interceptions,
    SUM(interceptions_observed_minutes) AS interceptions_observed_minutes,
    SUM(saves) AS saves,
    SUM(saves_observed_minutes) AS saves_observed_minutes,
    CASE WHEN SUM(goals_observed_minutes) > 0
        THEN ROUND(90.0 * SUM(goals) / SUM(goals_observed_minutes), 2)
    END AS goals_per_90,
    CASE WHEN SUM(assists_observed_minutes) > 0
        THEN ROUND(90.0 * SUM(assists) / SUM(assists_observed_minutes), 2)
    END AS assists_per_90,
    CASE WHEN SUM(shots_observed_minutes) > 0
        THEN ROUND(90.0 * SUM(shots) / SUM(shots_observed_minutes), 2)
    END AS shots_per_90,
    CASE WHEN SUM(key_passes_observed_minutes) > 0
        THEN ROUND(90.0 * SUM(key_passes) / SUM(key_passes_observed_minutes), 2)
    END AS key_passes_per_90,
    CASE WHEN SUM(tackles_observed_minutes) > 0
        THEN ROUND(90.0 * SUM(tackles) / SUM(tackles_observed_minutes), 2)
    END AS tackles_per_90,
    CASE WHEN SUM(interceptions_observed_minutes) > 0
        THEN ROUND(90.0 * SUM(interceptions) / SUM(interceptions_observed_minutes), 2)
    END AS interceptions_per_90,
    CASE WHEN SUM(saves_observed_minutes) > 0
        THEN ROUND(90.0 * SUM(saves) / SUM(saves_observed_minutes), 2)
    END AS saves_per_90,
    MAX(silver_as_of) AS silver_as_of
FROM workspace.football_data_project.gold_player_season_summary
GROUP BY player_id;
