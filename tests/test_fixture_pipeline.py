"""Behavior checks for five-league matchday sync and CSV migration."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import sync_matchday_stats as sync


def fixture(league_id, fixture_id, round_number=1, season=2026):
    return {
        "fixture": {"id": fixture_id, "date": "2024-08-01T12:00:00+00:00", "status": {"short": "FT"}},
        "league": {"id": league_id, "season": season, "round": f"Regular Season - {round_number}"},
    }


def is_fixture_key(key):
    return "/reference/fixtures/" in key


def players(_fixture_id):
    return {
        "response": [{
            "team": {"id": 10, "name": "A"},
            "players": [{
                "player": {"id": 20, "name": "P"},
                "statistics": [{"games": {"minutes": 90}}],
            }],
        }]
    }


class FixturePipelineTests(unittest.TestCase):
    def test_unnumbered_round_has_readable_stable_path(self):
        path = sync.matchday_path(78, 2023, "Relegation Round")
        self.assertEqual(path, "league_78/season_2023/GER_BUNDESLIGA_MATCHDAY_RELEGATION_ROUND.csv")

    def test_historical_sync_keeps_season_in_path_rows_and_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            output_dir = Path(tmp) / "output"
            state = {}
            uploaded = []

            def upload(_s3, _local_path, key):
                uploaded.append(key)
                return f"s3://bucket/{key}"

            with patch.multiple(sync, STATE_PATH=state_path, OUTPUT_DIR=output_dir,
                                AWS_S3_PREFIX="raw"), \
                    patch.object(sync, "get_fixtures", return_value=[fixture(39, 101, season=2023)]), \
                    patch.object(sync, "get_fixture_player_stats", side_effect=players), \
                    patch.object(sync, "upload_to_s3", side_effect=upload):
                self.assertEqual(sync.sync_league_season(39, 2023, state, object()), 1)

            self.assertEqual(uploaded, [
                "raw/reference/fixtures/league_39_season_2023.csv",
                "raw/league_39/season_2023/ENG_PREMIER_LEAGUE_MATCHDAY_01.csv",
            ])
            self.assertIn("39:2023:101", state)
            frame = pd.read_csv(output_dir / "league_39/season_2023/ENG_PREMIER_LEAGUE_MATCHDAY_01.csv")
            self.assertEqual(tuple(frame.loc[0, ["league_id", "season", "fixture_id"]]), (39, 2023, 101))

    def test_all_leagues_have_separate_matchday_files_and_fixture_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            output_dir = Path(tmp) / "output"
            uploaded = []
            fixtures = {league_id: [fixture(league_id, league_id * 100)] for league_id in sync.LEAGUES}
            fixtures[39].append(fixture(39, 3901))

            def get_fixtures(league_id, season):
                self.assertEqual(season, 2026)
                return fixtures[league_id]

            def upload(_s3, local_path, key):
                uploaded.append(key)
                self.assertTrue(Path(local_path).exists())
                return f"s3://bucket/{key}"

            with patch.multiple(sync, STATE_PATH=state_path, OUTPUT_DIR=output_dir,
                                SEASON=2026, SEASONS=(2026,), AWS_S3_PREFIX="raw"), \
                    patch.object(sync, "get_fixtures", side_effect=get_fixtures), \
                    patch.object(sync, "get_fixture_player_stats", side_effect=players) as fetch, \
                    patch.object(sync, "build_s3_client", return_value=object()), \
                    patch.object(sync, "upload_to_s3", side_effect=upload):
                sync.main()
                sync.main()
                self.assertEqual(fetch.call_count, 6)
                self.assertEqual(len(uploaded), 10)

                fixtures[39].append(fixture(39, 3902))
                sync.main()

            self.assertEqual(fetch.call_count, 9)
            # Unchanged fixture lists are not uploaded again.
            fixture_keys = [key for key in uploaded if is_fixture_key(key)]
            self.assertEqual(len(fixture_keys), 6)
            self.assertEqual(fixture_keys.count("raw/reference/fixtures/league_39_season_2026.csv"), 2)
            uploaded = [key for key in uploaded if not is_fixture_key(key)]
            self.assertEqual(len(uploaded), 6)
            self.assertEqual(uploaded[0], "raw/league_39/season_2026/ENG_PREMIER_LEAGUE_MATCHDAY_01.csv")
            self.assertIn("raw/league_140/season_2026/ESP_LA_LIGA_MATCHDAY_01.csv", uploaded)
            self.assertIn("raw/league_78/season_2026/GER_BUNDESLIGA_MATCHDAY_01.csv", uploaded)
            self.assertIn("raw/league_135/season_2026/ITA_SERIE_A_MATCHDAY_01.csv", uploaded)
            self.assertIn("raw/league_61/season_2026/FRA_LIGUE_1_MATCHDAY_01.csv", uploaded)

            state = json.loads(state_path.read_text())
            self.assertEqual(len(state), 7)
            self.assertIn("39:2026:3902", state)
            for league_id in sync.LEAGUES:
                frame = pd.read_csv(output_dir / sync.matchday_path(league_id, 2026, "Regular Season - 1"))
                self.assertTrue(frame["league_id"].eq(league_id).all())
                self.assertTrue(frame["season"].eq(2026).all())
            premier = pd.read_csv(output_dir / "league_39/season_2026/ENG_PREMIER_LEAGUE_MATCHDAY_01.csv")
            self.assertEqual(set(premier["fixture_id"]), {3900, 3901, 3902})

    def test_fixture_list_keeps_match_context_for_played_and_unplayed_fixtures(self):
        played = fixture(39, 101)
        played["fixture"].update(referee="R", venue={"id": 5, "name": "Ground", "city": "Town"})
        played.update(
            teams={"home": {"id": 10, "name": "A"}, "away": {"id": 11, "name": "B"}},
            goals={"home": 2, "away": 1},
            score={"halftime": {"home": 1, "away": 0}},
        )
        unplayed = fixture(39, 102, round_number=2)
        unplayed["fixture"]["status"] = {"short": "NS"}
        unplayed.update(
            teams={"home": {"id": 11, "name": "B"}, "away": {"id": 10, "name": "A"}},
            goals={"home": None, "away": None},
        )

        with tempfile.TemporaryDirectory() as tmp:
            uploaded = []

            def upload(_s3, local_path, key):
                uploaded.append(key)
                return f"s3://bucket/{key}"

            with patch.multiple(sync, OUTPUT_DIR=Path(tmp), AWS_S3_PREFIX=""), \
                    patch.object(sync, "upload_to_s3", side_effect=upload):
                self.assertTrue(sync.sync_fixtures(39, 2026, [unplayed, played], object()))
                self.assertFalse(sync.sync_fixtures(39, 2026, [played, unplayed], object()))

            self.assertEqual(uploaded, ["reference/fixtures/league_39_season_2026.csv"])
            text = (Path(tmp) / uploaded[0]).read_text()
            frame = pd.read_csv(Path(tmp) / uploaded[0])

        self.assertEqual(list(frame), list(sync.FIXTURE_COLUMNS))
        self.assertEqual(list(frame["fixture_id"]), [101, 102])
        self.assertEqual(tuple(frame.loc[0, ["home_team_name", "away_team_name", "status"]]), ("A", "B", "FT"))
        self.assertEqual(tuple(frame.loc[0, ["home_goals", "away_goals", "halftime_home_goals"]]), (2, 1, 1))
        self.assertEqual(frame.loc[0, "kickoff_utc"], "2024-08-01T12:00:00+00:00")
        self.assertTrue(pd.isna(frame.loc[1, "home_goals"]))
        # Whole numbers stay whole next to blanks, so the bronze loader reads ints.
        self.assertNotIn("2.0", text)

    def test_failed_fixture_upload_is_retried_on_the_next_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.multiple(sync, OUTPUT_DIR=Path(tmp), AWS_S3_PREFIX=""), \
                    patch.object(sync, "upload_to_s3", side_effect=[RuntimeError("s3 down"), "s3://bucket/key"]) as upload:
                with self.assertRaises(RuntimeError):
                    sync.sync_fixtures(39, 2026, [fixture(39, 101)], object())
                self.assertTrue(sync.sync_fixtures(39, 2026, [fixture(39, 101)], object()))
            self.assertEqual(upload.call_count, 2)


if __name__ == "__main__":
    unittest.main()
