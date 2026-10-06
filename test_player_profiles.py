"""Checks for the player profile cache and its S3 snapshot."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import sync_player_profiles as reference


class PlayerProfileTests(unittest.TestCase):
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

    def test_snapshot_writes_whole_number_ages_beside_missing_ones(self):
        class S3:
            def upload_file(self, path, bucket, key, ExtraArgs):
                self.text = Path(path).read_text()

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(reference, "OUTPUT_PATH", Path(directory) / "player_profiles.csv"), \
                patch.object(reference.matchdays, "AWS_S3_PREFIX", ""), \
                patch.object(reference.matchdays, "AWS_S3_BUCKET", "bucket"):
            s3 = S3()
            reference.write_snapshot(s3, [{"player_id": 10, "age": 26, "source_season": 2026},
                                          {"player_id": 11, "age": None, "source_season": 2026}])
        # "26.0" would be read as null by the bronze loader's integer age column.
        self.assertIn("\n10,,,,26,", s3.text)
        self.assertIn("\n11,,,,,", s3.text)
        self.assertNotIn(".0", s3.text)


if __name__ == "__main__":
    unittest.main()
