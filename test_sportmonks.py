"""Checks that Sportmonks responses become the layouts the sync scripts read."""

from datetime import date
import os
import unittest
from unittest.mock import patch

import requests

import sportmonks
import sync_matchday_stats as sync


def detail(code, value):
    return {"type": {"code": code}, "data": {"value": value}}


def lineup(player_id, team_id, position_id, details, bench=False, slot=None):
    return {
        "player_id": player_id, "team_id": team_id, "position_id": position_id,
        "player_name": f"Player {player_id}\xa0", "jersey_number": player_id,
        "type_id": sportmonks.BENCH if bench else 11,
        "formation_field": None if bench else "3:2",
        "detailedposition": {"name": slot} if slot else None,
        "details": details,
    }


FIXTURE = {
    "id": 900, "starting_at": "2025-08-16 14:00:00",
    "round": {"name": "7"}, "state": {"developer_name": "FT_PEN"},
    "venue": {"id": 5, "name": "Ground", "city_name": "Town"},
    "participants": [
        {"id": 1, "name": "Home", "meta": {"location": "home"}},
        {"id": 2, "name": "Away", "meta": {"location": "away"}},
    ],
    "scores": [
        {"description": "1ST_HALF", "score": {"goals": 1, "participant": "home"}},
        {"description": "1ST_HALF", "score": {"goals": 0, "participant": "away"}},
        {"description": "CURRENT", "score": {"goals": 2, "participant": "home"}},
        {"description": "CURRENT", "score": {"goals": 1, "participant": "away"}},
    ],
    "referees": [
        {"type_id": 7, "referee": {"name": "Assistant"}},
        {"type_id": sportmonks.MAIN_REFEREE, "referee": {"name": "Main Referee"}},
    ],
    "lineups": [
        lineup(10, 1, 26, [detail("minutes-played", 90), detail("passes", 40),
                           detail("accurate-passes", 35), detail("rating", 7.1),
                           detail("captain", True), detail("yellowcards", 1),
                           detail("yellowred-cards", 1)], slot="Defensive Midfield"),
        lineup(11, 1, 24, [detail("minutes-played", 90), detail("saves", 3)], slot="Goalkeeper"),
        lineup(12, 2, 27, [], bench=True),
    ],
}


class Response:
    def __init__(self, status_code, payload=None):
        self.status_code, self.payload, self.headers = status_code, payload, {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self.payload


@patch.dict(os.environ, {"SPORTMONKS_API_TOKEN": "token"})
class ApiTests(unittest.TestCase):
    def test_api_retries_disconnect_and_server_error(self):
        with patch.object(sportmonks._session, "get", side_effect=[
                requests.ConnectionError("remote closed"), Response(503), Response(200, {"data": []}),
        ]) as get, patch.object(sportmonks.time, "sleep") as sleep:
            payload = sportmonks.api_get("/fixtures")
        self.assertEqual(payload, {"data": []})
        self.assertEqual(get.call_count, 3)
        self.assertTrue(sleep.called)

    def test_api_raises_after_retry_limit(self):
        failing = patch.object(sportmonks._session, "get",
                               side_effect=requests.ConnectionError("remote closed"))
        with failing as get, patch.object(sportmonks.time, "sleep"):
            with self.assertRaises(requests.ConnectionError):
                sportmonks.api_get("/fixtures", max_retries=2)
        self.assertEqual(get.call_count, 3)

    def test_api_waits_for_the_reset_when_the_hourly_limit_runs_out(self):
        spent = {"data": [], "rate_limit": {"remaining": 0, "resets_in_seconds": 1200,
                                            "requested_entity": "Fixture"}}
        with patch.object(sportmonks._session, "get", return_value=Response(200, spent)):
            with patch.object(sportmonks.time, "sleep") as sleep:
                sportmonks.api_get("/fixtures")
        sleep.assert_called_with(1200)

    def test_api_reports_a_response_without_data(self):
        denied = Response(200, {"message": "No access"})
        with patch.object(sportmonks._session, "get", return_value=denied):
            with patch.object(sportmonks.time, "sleep"):
                with self.assertRaisesRegex(ValueError, "No access"):
                    sportmonks.api_get("/fixtures")


class FixtureTests(unittest.TestCase):
    def test_fixture_matches_the_layout_flatten_fixture_reads(self):
        row = sync.flatten_fixture(39, 2025, sportmonks.to_fixture(39, 2025, FIXTURE))
        self.assertEqual(row["round"], "Regular Season - 7")
        self.assertEqual(row["kickoff_utc"], "2025-08-16T14:00:00+00:00")
        self.assertEqual(row["status"], "PEN")
        self.assertEqual(row["referee"], "Main Referee")
        self.assertEqual((row["venue_id"], row["venue_city"]), (5, "Town"))
        self.assertEqual((row["home_team_id"], row["away_team_name"]), (1, "Away"))
        self.assertEqual((row["home_goals"], row["away_goals"]), (2, 1))
        self.assertEqual((row["halftime_home_goals"], row["halftime_away_goals"]), (1, 0))

    def test_unplayed_fixture_has_blank_scores_and_its_own_state(self):
        unplayed = {**FIXTURE, "scores": [], "state": {"developer_name": "NS"}, "round": None}
        fixture = sportmonks.to_fixture(39, 2025, unplayed)
        self.assertEqual(fixture["goals"], {"home": None, "away": None})
        self.assertEqual(fixture["fixture"]["status"]["short"], "NS")
        self.assertEqual(fixture["league"]["round"], "No Round")

    def test_season_ids_are_looked_up_once_per_league(self):
        league = {"data": {"seasons": [{"id": 77, "name": "2025/2026"}, {"id": 66, "name": "2024/2025"}]}}
        with patch.dict(sportmonks._season_ids, clear=True), \
                patch.object(sportmonks, "api_get", return_value=league) as api_get:
            self.assertEqual(sportmonks.season_id(39, 2025), 77)
            self.assertEqual(sportmonks.season_id(39, 2024), 66)
            with self.assertRaisesRegex(ValueError, "no season 2023"):
                sportmonks.season_id(39, 2023)
        api_get.assert_called_once_with("/leagues/8", {"include": "seasons"})

    def test_pages_are_read_until_the_last(self):
        pages = [{"data": [1, 2], "pagination": {"has_more": True}},
                 {"data": [3], "pagination": {"has_more": False}}]
        with patch.object(sportmonks, "api_get", side_effect=pages) as api_get:
            self.assertEqual(sportmonks.get_pages("/fixtures", {"filters": "x"}), [1, 2, 3])
        self.assertEqual(api_get.call_args.args[1], {"filters": "x", "per_page": 50, "page": 2})


class PlayerStatsTests(unittest.TestCase):
    def rows(self, fixture=FIXTURE):
        flat = sync.flatten_fixture_players(900, "Regular Season - 7", sportmonks.to_player_stats(fixture))
        return {row["player_id"]: row for row in flat}

    def test_rows_use_the_existing_csv_columns(self):
        midfielder = self.rows()[10]
        self.assertEqual((midfielder["team_id"], midfielder["team_name"]), (1, "Home"))
        self.assertEqual(midfielder["player_name"], "Player 10")
        self.assertEqual((midfielder["games_minutes"], midfielder["games_position"]), (90, "M"))
        self.assertEqual(midfielder["games_detailed_position"], "Defensive Midfield")
        self.assertEqual((midfielder["passes_total"], midfielder["passes_accuracy"]), (40, 35))
        self.assertIs(midfielder["games_captain"], True)
        self.assertIs(midfielder["games_substitute"], False)

    def test_missing_counts_are_zero_for_a_player_who_played(self):
        rows = self.rows()
        self.assertEqual(rows[10]["goals_total"], 0)
        self.assertEqual(rows[10]["tackles_total"], 0)
        self.assertIsNone(rows[10]["goals_saves"])  # outfield players make no saves
        self.assertEqual((rows[11]["goals_saves"], rows[11]["penalty_saved"]), (3, 0))
        self.assertIsNone(rows[11]["games_rating"])

    def test_whole_stays_blank_when_only_its_part_is_reported(self):
        entry = lineup(10, 1, 27, [detail("minutes-played", 90), detail("passes", 20),
                                   detail("successful-dribbles", 1)])
        row = self.rows({**FIXTURE, "lineups": [entry]})[10]
        self.assertEqual(row["dribbles_success"], 1)
        self.assertIsNone(row["dribbles_attempts"])
        self.assertEqual(row["shots_total"], 0)

    def test_lineup_entry_without_a_player_id_is_skipped(self):
        unknown = {**lineup(13, 1, 27, [detail("minutes-played", 9)], bench=True), "player_id": None}
        rows = self.rows({**FIXTURE, "lineups": FIXTURE["lineups"] + [unknown]})
        self.assertEqual(sorted(rows), [10, 11, 12])

    def test_extra_statistics_and_team_possession_reach_the_row(self):
        fixture = {**FIXTURE, "statistics": [
            {"participant_id": 1, "type": {"code": "ball-possession"}, "data": {"value": 62}},
            {"participant_id": 2, "type": {"code": "ball-possession"}, "data": {"value": 38}},
            {"participant_id": 1, "type": {"code": "corners"}, "data": {"value": 7}},
        ], "lineups": [
            lineup(10, 1, 26, [detail("minutes-played", 90), detail("passes", 40),
                               detail("ball-recovery", 9), detail("aeriels-won", 2),
                               detail("tackles-won", 1)]),
            lineup(11, 1, 24, [detail("minutes-played", 90), detail("punches", 1)]),
            lineup(12, 2, 27, [], bench=True),
        ]}
        rows = self.rows(fixture)
        self.assertEqual((rows[10]["team_possession_pct"], rows[12]["team_possession_pct"]), (62, 38))
        self.assertEqual((rows[10]["ball_recoveries"], rows[10]["aerials_won"]), (9, 2))
        self.assertEqual((rows[10]["clearances"], rows[10]["aerials_lost"]), (0, 0))
        # Tackles won was reported without tackles, so the total is unknown.
        self.assertEqual((rows[10]["tackles_won"], rows[10]["tackles_total"]), (1, None))
        self.assertIsNone(rows[10]["goalkeeper_punches"])
        self.assertEqual((rows[11]["goalkeeper_punches"], rows[11]["goalkeeper_high_claims"]), (1, 0))

    def test_possession_is_blank_when_the_fixture_has_none(self):
        self.assertIsNone(self.rows()[10]["team_possession_pct"])

    def test_second_yellow_counts_as_a_red_card(self):
        self.assertEqual((self.rows()[10]["cards_yellow"], self.rows()[10]["cards_red"]), (1, 1))

    def test_unused_substitute_has_no_statistics(self):
        substitute = self.rows()[12]
        self.assertIs(substitute["games_substitute"], True)
        self.assertIsNone(substitute["games_minutes"])
        self.assertIsNone(substitute["goals_total"])
        self.assertIsNone(substitute["games_detailed_position"])

    def test_counts_stay_blank_when_the_fixture_has_no_detailed_statistics(self):
        sparse = {**FIXTURE, "lineups": [lineup(10, 1, 26, [detail("minutes-played", 90)])]}
        self.assertIsNone(self.rows(sparse)[10]["goals_total"])


class ProfileTests(unittest.TestCase):
    def test_profile_keeps_existing_columns_and_adds_positions(self):
        player = {
            "id": 44, "display_name": "Rodri\xa0", "firstname": "Rodrigo", "lastname": "Hernández",
            "date_of_birth": "1996-06-22", "height": 191, "weight": None,
            "image_path": "https://example.test/44.png",
            "nationality": {"name": "Spain"}, "position": {"name": "Midfielder"},
            "detailedposition": {"name": "Defensive Midfield"},
        }
        profile = sportmonks.to_profile(player, 39, 2026, date(2026, 6, 21), "now")
        self.assertEqual((profile["name"], profile["age"]), ("Rodri", 29))
        self.assertEqual((profile["height"], profile["weight"]), ("191 cm", None))
        self.assertEqual(profile["nationality"], "Spain")
        self.assertEqual((profile["position"], profile["detailed_position"]),
                         ("Midfielder", "Defensive Midfield"))
        self.assertEqual((profile["source_league_id"], profile["source_season"]), (39, 2026))

    def test_squads_are_read_for_every_team_and_latest_season_wins(self):
        def api_get(path, params=None):
            if path.startswith("/teams/seasons/"):
                return {"data": [{"id": 1}, {"id": 2}]}
            season = int(path.split("/")[3])
            return {"data": [{"player": {"id": 44, "display_name": f"Season {season}"}},
                             {"player": None}]}

        with patch.object(sportmonks, "api_get", side_effect=api_get) as calls, \
                patch.object(sportmonks, "season_id", side_effect=lambda league, season: season):
            profiles = sportmonks.fetch_profiles([39], [2025, 2026])
        self.assertEqual(list(profiles), [44])
        self.assertEqual(profiles[44]["name"], "Season 2026")
        self.assertEqual(calls.call_count, 6)


if __name__ == "__main__":
    unittest.main()
