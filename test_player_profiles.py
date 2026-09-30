"""Checks for paginated player profiles and their S3 snapshot."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
import requests

import sync_player_profiles as reference


class PlayerProfileTests(unittest.TestCase):
    def test_api_retries_disconnect_and_server_error(self):
        class Response:
            status_code = 503
            headers = {}

            def raise_for_status(self):
                raise requests.HTTPError("503")

        class Success:
            status_code = 200
            headers = {}

            def raise_for_status(self):
                pass

            def json(self):
                return {"response": []}

        with patch.object(reference.matchdays.http_session, "get", side_effect=[
                requests.ConnectionError("remote closed"), Response(), Success(),
        ]) as get, patch.object(reference.matchdays.time, "sleep") as sleep:
            payload = reference.matchdays.api_get("/players", {"league": 39, "season": 2026})
        self.assertEqual(payload, {"response": []})
        self.assertEqual(get.call_count, 3)
        self.assertTrue(sleep.called)

    def test_api_raises_after_retry_limit(self):
        with patch.object(reference.matchdays.http_session, "get",
                          side_effect=requests.ConnectionError("remote closed")) as get, \
                patch.object(reference.matchdays.time, "sleep"):
            with self.assertRaises(requests.ConnectionError):
                reference.matchdays.api_get("/players", {"league": 39, "season": 2026}, max_retries=2)
        self.assertEqual(get.call_count, 3)

    def test_completed_profile_scan_is_reused_after_failure(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(reference, "PROFILE_CACHE_PATH", Path(directory) / "profiles.json"):
            scans = []

            def fetch():
                scans.append(True)
                return {10: {"player_id": 10, "age": 26}}

            self.assertEqual(reference.load_or_fetch_profiles(fetch),
                             {10: {"player_id": 10, "age": 26}})
            self.assertEqual(reference.load_or_fetch_profiles(fetch),
                             {10: {"player_id": 10, "age": 26}})
            self.assertEqual(len(scans), 1)

    def test_profiles_read_every_page_and_keep_latest_season(self):
        calls = []

        def api_get(path, params):
            calls.append((path, params.copy()))
            season, page = params["season"], params["page"]
            player_id = 10 if page == 1 else 20
            return {
                "paging": {"current": page, "total": 2},
                "response": [{"player": {
                    "id": player_id, "name": "Player", "age": 26,
                    "nationality": "England", "birth": {"date": "2000-01-01"},
                }}],
            }

        with patch.object(reference.matchdays, "SEASONS", (2025, 2026)), \
                patch.object(reference.matchdays, "LEAGUES", {39: ("ENG", "PREMIER_LEAGUE")}):
            profiles = reference.fetch_profiles(api_get)

        self.assertEqual(len(calls), 4)
        self.assertEqual(set(profiles), {10, 20})
        self.assertEqual(profiles[10]["source_season"], 2026)
        self.assertEqual(profiles[20]["birth_date"], "2000-01-01")
        self.assertEqual(profiles[10]["nationality"], "England")

    def test_profile_snapshot_has_its_own_path_and_header(self):
        class S3:
            def __init__(self):
                self.keys = []

            def upload_file(self, path, bucket, key, ExtraArgs):
                self.keys.append(key)
                self.frame = pd.read_csv(path)

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(reference, "OUTPUT_PATH", Path(directory) / "player_profiles.csv"), \
                patch.object(reference.matchdays, "AWS_S3_PREFIX", "raw"), \
                patch.object(reference.matchdays, "AWS_S3_BUCKET", "bucket"):
            s3 = S3()
            reference.write_snapshot(s3, [{"player_id": 10, "age": 26,
                                           "nationality": "England"}])
            self.assertEqual(s3.keys, ["raw/reference/player_profiles/player_profiles.csv"])
            self.assertEqual(list(s3.frame), list(reference.PROFILE_COLUMNS))
            self.assertEqual(s3.frame.loc[0, "nationality"], "England")


if __name__ == "__main__":
    unittest.main()
