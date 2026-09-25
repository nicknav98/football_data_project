"""Behavior checks for five-league matchday sync and CSV migration."""

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import sync_matchday_stats as sync
import player_comparison as comparison


def fixture(league_id, fixture_id, round_number=1):
    return {
        "fixture": {"id": fixture_id, "date": "2024-08-01T12:00:00+00:00", "status": {"short": "FT"}},
        "league": {"id": league_id, "season": 2026, "round": f"Regular Season - {round_number}"},
    }


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
    def test_all_leagues_have_separate_matchday_files_and_fixture_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            output_dir = Path(tmp) / "output"
            uploaded = []
            fixtures = {league_id: [fixture(league_id, league_id * 100)] for league_id in sync.LEAGUES}
            fixtures[39].append(fixture(39, 3901))

            def get_fixtures(league_id):
                return fixtures[league_id]

            def upload(_s3, local_path, key):
                uploaded.append(key)
                self.assertTrue(Path(local_path).exists())
                return f"s3://bucket/{key}"

            with patch.multiple(sync, STATE_PATH=state_path, OUTPUT_DIR=output_dir,
                                SEASON=2026, AWS_S3_PREFIX="raw"), \
                    patch.object(sync, "get_fixtures", side_effect=get_fixtures), \
                    patch.object(sync, "get_fixture_player_stats", side_effect=players) as fetch, \
                    patch.object(sync, "build_s3_client", return_value=object()), \
                    patch.object(sync, "upload_to_s3", side_effect=upload):
                sync.main()
                sync.main()
                self.assertEqual(fetch.call_count, 6)
                self.assertEqual(len(uploaded), 5)

                fixtures[39].append(fixture(39, 3902))
                sync.main()

            self.assertEqual(fetch.call_count, 9)
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
                frame = pd.read_csv(output_dir / sync.matchday_path(league_id, "Regular Season - 1"))
                self.assertTrue(frame["league_id"].eq(league_id).all())
                self.assertTrue(frame["season"].eq(2026).all())
            premier = pd.read_csv(output_dir / "league_39/season_2026/ENG_PREMIER_LEAGUE_MATCHDAY_01.csv")
            self.assertEqual(set(premier["fixture_id"]), {3900, 3901, 3902})

    def test_comparison_reads_only_nested_matchday_files(self):
        class S3:
            def get_paginator(self, _name):
                return self

            def paginate(self, **_kwargs):
                return [{"Contents": [
                    {"Key": "raw/ENG_Premier_League_Matchday_01.csv"},
                    {"Key": "raw/league_39/season_2026/fixture_101.csv"},
                    {"Key": "raw/league_39/season_2026/ENG_PREMIER_LEAGUE_MATCHDAY_01.csv"},
                ]}]

            def get_object(self, **_kwargs):
                csv = "league_id,season,fixture_id,team_id,team_name,player_id,player_name\n39,2026,101,10,A,20,P\n"
                return {"Body": BytesIO(csv.encode())}

        with patch.object(comparison, "configure_environment", return_value=("bucket", "raw")), \
                patch.object(comparison.boto3, "client", return_value=S3()):
            frame, count = comparison.read_matchdays()

        self.assertEqual(count, 1)
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.loc[0, "fixture_id"], 101)


if __name__ == "__main__":
    unittest.main()
