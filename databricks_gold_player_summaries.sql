/* Run after silver_matchday_stats and bronze_player_profiles exist.
   The materialized view refreshes when a source table changes.
   Silver holds one row per league, season, fixture, team, and player.

   Table names have no schema, so select the pipeline's schema first:
       USE workspace.football_data_project_sportmonks
   Silver needs the possession and extra statistic columns that
   sync_matchday_stats.py writes, so load those before running this. */
CREATE OR REPLACE MATERIALIZED VIEW gold_player_season_summary
TRIGGER ON UPDATE
AS
WITH matchdays AS (
    SELECT * FROM silver_matchday_stats
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
        /* Shots faced are saves plus goals conceded, counted for goalkeepers only. */
        SUM(CASE WHEN games_position = 'G' AND goals_saves IS NOT NULL AND goals_conceded IS NOT NULL
            THEN goals_saves + goals_conceded END) AS shots_faced_with_save_data,
        SUM(CASE WHEN games_position = 'G' AND goals_saves IS NOT NULL AND goals_conceded IS NOT NULL
            THEN goals_saves END) AS paired_saves,
        CASE WHEN COUNT(cards_yellow) > 0 THEN SUM(cards_yellow) END AS yellow_cards,
        CASE WHEN COUNT(cards_red) > 0 THEN SUM(cards_red) END AS red_cards,
        CASE WHEN COUNT(offsides) > 0 THEN SUM(offsides) END AS offsides,
        CASE WHEN COUNT(tackles_blocks) > 0 THEN SUM(tackles_blocks) END AS blocks,
        SUM(CASE WHEN tackles_blocks IS NOT NULL AND games_minutes >= 0 THEN games_minutes ELSE 0 END) AS blocks_observed_minutes,
        CASE WHEN COUNT(dribbles_past) > 0 THEN SUM(dribbles_past) END AS dribbled_past,
        CASE WHEN COUNT(fouls_drawn) > 0 THEN SUM(fouls_drawn) END AS fouls_drawn,
        SUM(CASE WHEN fouls_drawn IS NOT NULL AND games_minutes >= 0 THEN games_minutes ELSE 0 END) AS fouls_drawn_observed_minutes,
        CASE WHEN COUNT(fouls_committed) > 0 THEN SUM(fouls_committed) END AS fouls_committed,
        SUM(CASE WHEN fouls_committed IS NOT NULL AND games_minutes >= 0 THEN games_minutes ELSE 0 END) AS fouls_committed_observed_minutes,
        CASE WHEN COUNT(penalty_won) > 0 THEN SUM(penalty_won) END AS penalties_won,
        CASE WHEN COUNT(penalty_commited) > 0 THEN SUM(penalty_commited) END AS penalties_committed,
        CASE WHEN COUNT(penalty_scored) > 0 THEN SUM(penalty_scored) END AS penalties_scored,
        CASE WHEN COUNT(penalty_missed) > 0 THEN SUM(penalty_missed) END AS penalties_missed,
        CASE WHEN COUNT(penalty_saved) > 0 THEN SUM(penalty_saved) END AS penalties_saved,
        /* Non-penalty goals use only matches reporting both goals and penalties scored. */
        SUM(CASE WHEN goals_total IS NOT NULL AND penalty_scored IS NOT NULL
            THEN goals_total - penalty_scored END) AS non_penalty_goals,
        SUM(CASE WHEN goals_total IS NOT NULL AND penalty_scored IS NOT NULL AND games_minutes >= 0
            THEN games_minutes ELSE 0 END) AS non_penalty_goals_observed_minutes,
        ROUND(AVG(games_rating), 2) AS average_rating,
        COUNT(games_rating) AS matches_with_rating,
        /* passes_accuracy is the number of accurate passes, not a percentage. */
        SUM(CASE
            WHEN passes_total > 0 AND passes_accuracy BETWEEN 0 AND passes_total
            THEN passes_accuracy ELSE 0
        END) AS accurate_passes,
        SUM(CASE
            WHEN passes_total > 0 AND passes_accuracy BETWEEN 0 AND passes_total
            THEN passes_total ELSE 0
        END) AS passes_with_accuracy,
        /* Statistics below come from Sportmonks and have no API-Football counterpart. */
        CASE WHEN COUNT(shots_off) > 0 THEN SUM(shots_off) END AS shots_off_target,
        CASE WHEN COUNT(shots_blocked) > 0 THEN SUM(shots_blocked) END AS shots_blocked,
        CASE WHEN COUNT(shots_woodwork) > 0 THEN SUM(shots_woodwork) END AS shots_hit_woodwork,
        CASE WHEN COUNT(own_goals) > 0 THEN SUM(own_goals) END AS own_goals,
        CASE WHEN COUNT(big_chances_created) > 0 THEN SUM(big_chances_created) END AS big_chances_created,
        CASE WHEN COUNT(big_chances_missed) > 0 THEN SUM(big_chances_missed) END AS big_chances_missed,
        CASE WHEN COUNT(passes_final_third) > 0 THEN SUM(passes_final_third) END AS passes_final_third,
        CASE WHEN COUNT(crosses_total) > 0 THEN SUM(crosses_total) END AS crosses,
        CASE WHEN COUNT(crosses_accurate) > 0 THEN SUM(crosses_accurate) END AS crosses_accurate,
        CASE WHEN COUNT(long_balls_total) > 0 THEN SUM(long_balls_total) END AS long_balls,
        CASE WHEN COUNT(long_balls_accurate) > 0 THEN SUM(long_balls_accurate) END AS long_balls_accurate,
        CASE WHEN COUNT(through_balls_total) > 0 THEN SUM(through_balls_total) END AS through_balls,
        CASE WHEN COUNT(through_balls_accurate) > 0 THEN SUM(through_balls_accurate) END AS through_balls_accurate,
        CASE WHEN COUNT(touches) > 0 THEN SUM(touches) END AS touches,
        CASE WHEN COUNT(possession_lost) > 0 THEN SUM(possession_lost) END AS possession_lost,
        CASE WHEN COUNT(dispossessed) > 0 THEN SUM(dispossessed) END AS dispossessed,
        CASE WHEN COUNT(tackles_won) > 0 THEN SUM(tackles_won) END AS tackles_won,
        CASE WHEN COUNT(clearances) > 0 THEN SUM(clearances) END AS clearances,
        CASE WHEN COUNT(ball_recoveries) > 0 THEN SUM(ball_recoveries) END AS ball_recoveries,
        CASE WHEN COUNT(aerials_won) > 0 THEN SUM(aerials_won) END AS aerials_won,
        CASE WHEN COUNT(aerials_lost) > 0 THEN SUM(aerials_lost) END AS aerials_lost,
        CASE WHEN COUNT(errors_leading_to_shot) > 0 THEN SUM(errors_leading_to_shot) END AS errors_leading_to_shot,
        CASE WHEN COUNT(errors_leading_to_goal) > 0 THEN SUM(errors_leading_to_goal) END AS errors_leading_to_goal,
        CASE WHEN COUNT(saves_inside_box) > 0 THEN SUM(saves_inside_box) END AS saves_inside_box,
        CASE WHEN COUNT(goalkeeper_goals_conceded) > 0 THEN SUM(goalkeeper_goals_conceded) END AS goalkeeper_goals_conceded,
        CASE WHEN COUNT(goalkeeper_punches) > 0 THEN SUM(goalkeeper_punches) END AS goalkeeper_punches,
        CASE WHEN COUNT(goalkeeper_high_claims) > 0 THEN SUM(goalkeeper_high_claims) END AS goalkeeper_high_claims,
        SUM(CASE WHEN touches IS NOT NULL AND games_minutes >= 0 THEN games_minutes ELSE 0 END) AS touches_observed_minutes,
        SUM(CASE WHEN passes_final_third IS NOT NULL AND games_minutes >= 0 THEN games_minutes ELSE 0 END) AS passes_final_third_observed_minutes,
        SUM(CASE WHEN big_chances_created IS NOT NULL AND games_minutes >= 0 THEN games_minutes ELSE 0 END) AS big_chances_created_observed_minutes,
        SUM(CASE WHEN possession_lost IS NOT NULL AND games_minutes >= 0 THEN games_minutes ELSE 0 END) AS possession_lost_observed_minutes,
        SUM(CASE WHEN clearances IS NOT NULL AND games_minutes >= 0 THEN games_minutes ELSE 0 END) AS clearances_observed_minutes,
        SUM(CASE WHEN ball_recoveries IS NOT NULL AND games_minutes >= 0 THEN games_minutes ELSE 0 END) AS ball_recoveries_observed_minutes,
        SUM(CASE WHEN aerials_won IS NOT NULL AND games_minutes >= 0 THEN games_minutes ELSE 0 END) AS aerials_won_observed_minutes,
        SUM(CASE WHEN aerials_lost IS NOT NULL AND aerials_won IS NOT NULL THEN aerials_won + aerials_lost END) AS aerials_with_won_data,
        SUM(CASE WHEN aerials_lost IS NOT NULL AND aerials_won IS NOT NULL THEN aerials_won END) AS paired_aerials_won,
        SUM(CASE WHEN crosses_accurate IS NOT NULL AND crosses_total IS NOT NULL THEN crosses_total END) AS crosses_with_accuracy_data,
        SUM(CASE WHEN crosses_accurate IS NOT NULL AND crosses_total IS NOT NULL THEN crosses_accurate END) AS paired_crosses_accurate,
        SUM(CASE WHEN long_balls_accurate IS NOT NULL AND long_balls_total IS NOT NULL THEN long_balls_total END) AS long_balls_with_accuracy_data,
        SUM(CASE WHEN long_balls_accurate IS NOT NULL AND long_balls_total IS NOT NULL THEN long_balls_accurate END) AS paired_long_balls_accurate,
        SUM(CASE WHEN tackles_total IS NOT NULL AND tackles_won IS NOT NULL THEN tackles_total END) AS tackles_with_won_data,
        SUM(CASE WHEN tackles_total IS NOT NULL AND tackles_won IS NOT NULL THEN tackles_won END) AS paired_tackles_won,
        /* The team's share of possession, weighted by the player's minutes. */
        SUM(CASE WHEN team_possession_pct IS NOT NULL AND games_minutes > 0
            THEN team_possession_pct * games_minutes END) AS possession_minutes_product,
        SUM(CASE WHEN team_possession_pct IS NOT NULL AND games_minutes > 0
            THEN games_minutes ELSE 0 END) AS possession_observed_minutes,
        /* Possession-adjusted counts scale each match to an opponent with half
           the ball: count * 50 / opponent possession. Possession is the team's
           for the whole match, not only while the player was on the pitch. */
        SUM(CASE WHEN tackles_total IS NOT NULL AND team_possession_pct > 0 AND team_possession_pct < 100
            THEN tackles_total * 50.0 / (100 - team_possession_pct) END) AS tackles_possession_adjusted,
        SUM(CASE WHEN tackles_total IS NOT NULL AND team_possession_pct > 0 AND team_possession_pct < 100 AND games_minutes >= 0
            THEN games_minutes ELSE 0 END) AS tackles_possession_adjusted_observed_minutes,
        SUM(CASE WHEN tackles_interceptions IS NOT NULL AND team_possession_pct > 0 AND team_possession_pct < 100
            THEN tackles_interceptions * 50.0 / (100 - team_possession_pct) END) AS interceptions_possession_adjusted,
        SUM(CASE WHEN tackles_interceptions IS NOT NULL AND team_possession_pct > 0 AND team_possession_pct < 100 AND games_minutes >= 0
            THEN games_minutes ELSE 0 END) AS interceptions_possession_adjusted_observed_minutes,
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
    /* The player's usual role from the profile, such as Defensive Midfield. */
    p.detailed_position,
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
    s.shots_faced_with_save_data,
    s.yellow_cards,
    s.red_cards,
    s.offsides,
    s.blocks,
    s.blocks_observed_minutes,
    s.dribbled_past,
    s.fouls_drawn,
    s.fouls_drawn_observed_minutes,
    s.fouls_committed,
    s.fouls_committed_observed_minutes,
    s.penalties_won,
    s.penalties_committed,
    s.penalties_scored,
    s.penalties_missed,
    s.penalties_saved,
    s.non_penalty_goals,
    s.non_penalty_goals_observed_minutes,
    s.average_rating,
    s.matches_with_rating,
    s.accurate_passes,
    s.passes_with_accuracy,
    CASE WHEN s.passes_with_accuracy > 0
        THEN ROUND(100.0 * s.accurate_passes / s.passes_with_accuracy, 1)
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
    CASE WHEN s.shots_faced_with_save_data > 0
        THEN ROUND(100.0 * s.paired_saves / s.shots_faced_with_save_data, 1)
    END AS save_pct,
    CASE WHEN s.non_penalty_goals_observed_minutes > 0
        THEN ROUND(90.0 * s.non_penalty_goals / s.non_penalty_goals_observed_minutes, 2)
    END AS non_penalty_goals_per_90,
    CASE WHEN s.blocks_observed_minutes > 0
        THEN ROUND(90.0 * s.blocks / s.blocks_observed_minutes, 2)
    END AS blocks_per_90,
    CASE WHEN s.fouls_drawn_observed_minutes > 0
        THEN ROUND(90.0 * s.fouls_drawn / s.fouls_drawn_observed_minutes, 2)
    END AS fouls_drawn_per_90,
    CASE WHEN s.fouls_committed_observed_minutes > 0
        THEN ROUND(90.0 * s.fouls_committed / s.fouls_committed_observed_minutes, 2)
    END AS fouls_committed_per_90,
    s.shots_off_target,
    s.shots_blocked,
    s.shots_hit_woodwork,
    s.own_goals,
    s.big_chances_created,
    s.big_chances_missed,
    s.passes_final_third,
    s.crosses,
    s.crosses_accurate,
    s.long_balls,
    s.long_balls_accurate,
    s.through_balls,
    s.through_balls_accurate,
    s.touches,
    s.possession_lost,
    s.dispossessed,
    s.tackles_won,
    s.clearances,
    s.ball_recoveries,
    s.aerials_won,
    s.aerials_lost,
    s.errors_leading_to_shot,
    s.errors_leading_to_goal,
    s.saves_inside_box,
    s.goalkeeper_goals_conceded,
    s.goalkeeper_punches,
    s.goalkeeper_high_claims,
    s.touches_observed_minutes,
    CASE WHEN s.touches_observed_minutes > 0
        THEN ROUND(90.0 * s.touches / s.touches_observed_minutes, 2)
    END AS touches_per_90,
    s.passes_final_third_observed_minutes,
    CASE WHEN s.passes_final_third_observed_minutes > 0
        THEN ROUND(90.0 * s.passes_final_third / s.passes_final_third_observed_minutes, 2)
    END AS passes_final_third_per_90,
    s.big_chances_created_observed_minutes,
    CASE WHEN s.big_chances_created_observed_minutes > 0
        THEN ROUND(90.0 * s.big_chances_created / s.big_chances_created_observed_minutes, 2)
    END AS big_chances_created_per_90,
    s.possession_lost_observed_minutes,
    CASE WHEN s.possession_lost_observed_minutes > 0
        THEN ROUND(90.0 * s.possession_lost / s.possession_lost_observed_minutes, 2)
    END AS possession_lost_per_90,
    s.clearances_observed_minutes,
    CASE WHEN s.clearances_observed_minutes > 0
        THEN ROUND(90.0 * s.clearances / s.clearances_observed_minutes, 2)
    END AS clearances_per_90,
    s.ball_recoveries_observed_minutes,
    CASE WHEN s.ball_recoveries_observed_minutes > 0
        THEN ROUND(90.0 * s.ball_recoveries / s.ball_recoveries_observed_minutes, 2)
    END AS ball_recoveries_per_90,
    s.aerials_won_observed_minutes,
    CASE WHEN s.aerials_won_observed_minutes > 0
        THEN ROUND(90.0 * s.aerials_won / s.aerials_won_observed_minutes, 2)
    END AS aerials_won_per_90,
    s.aerials_with_won_data,
    CASE WHEN s.aerials_with_won_data > 0
        THEN ROUND(100.0 * s.paired_aerials_won / s.aerials_with_won_data, 1)
    END AS aerial_win_pct,
    s.crosses_with_accuracy_data,
    CASE WHEN s.crosses_with_accuracy_data > 0
        THEN ROUND(100.0 * s.paired_crosses_accurate / s.crosses_with_accuracy_data, 1)
    END AS cross_accuracy_pct,
    s.long_balls_with_accuracy_data,
    CASE WHEN s.long_balls_with_accuracy_data > 0
        THEN ROUND(100.0 * s.paired_long_balls_accurate / s.long_balls_with_accuracy_data, 1)
    END AS long_ball_accuracy_pct,
    s.tackles_with_won_data,
    CASE WHEN s.tackles_with_won_data > 0
        THEN ROUND(100.0 * s.paired_tackles_won / s.tackles_with_won_data, 1)
    END AS tackle_success_pct,
    CASE WHEN s.possession_observed_minutes > 0
        THEN ROUND(s.possession_minutes_product / s.possession_observed_minutes, 1)
    END AS average_team_possession_pct,
    ROUND(s.tackles_possession_adjusted, 1) AS tackles_possession_adjusted,
    s.tackles_possession_adjusted_observed_minutes,
    CASE WHEN s.tackles_possession_adjusted_observed_minutes > 0
        THEN ROUND(90.0 * s.tackles_possession_adjusted / s.tackles_possession_adjusted_observed_minutes, 2)
    END AS tackles_possession_adjusted_per_90,
    ROUND(s.interceptions_possession_adjusted, 1) AS interceptions_possession_adjusted,
    s.interceptions_possession_adjusted_observed_minutes,
    CASE WHEN s.interceptions_possession_adjusted_observed_minutes > 0
        THEN ROUND(90.0 * s.interceptions_possession_adjusted / s.interceptions_possession_adjusted_observed_minutes, 2)
    END AS interceptions_possession_adjusted_per_90,
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
LEFT JOIN bronze_player_profiles p
    ON s.player_id = p.player_id;

/* This view summarizes only the seasons and leagues present in the gold table. */
CREATE OR REPLACE VIEW gold_player_observed_summary AS
SELECT
    player_id,
    MAX_BY(player_name, season) AS player_name,
    MAX(profile_age) AS profile_age,
    MAX(nationality) AS nationality,
    MAX_BY(detailed_position, season) AS detailed_position,
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
    SUM(non_penalty_goals) AS non_penalty_goals,
    SUM(non_penalty_goals_observed_minutes) AS non_penalty_goals_observed_minutes,
    SUM(penalties_scored) AS penalties_scored,
    SUM(penalties_missed) AS penalties_missed,
    SUM(fouls_drawn) AS fouls_drawn,
    SUM(fouls_committed) AS fouls_committed,
    SUM(yellow_cards) AS yellow_cards,
    SUM(red_cards) AS red_cards,
    CASE WHEN SUM(non_penalty_goals_observed_minutes) > 0
        THEN ROUND(90.0 * SUM(non_penalty_goals) / SUM(non_penalty_goals_observed_minutes), 2)
    END AS non_penalty_goals_per_90,
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
FROM gold_player_season_summary
GROUP BY player_id;
