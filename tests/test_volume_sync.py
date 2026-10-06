"""Checks that the S3 to volume copy skips files it has already copied."""

from pathlib import Path
import tempfile
import unittest

import databricks_volume_sync as volume_sync


MATCHDAY = "raw/league_39/season_2026/ENG_PREMIER_LEAGUE_MATCHDAY_01.csv"
FIXTURES = "raw/reference/fixtures/league_39_season_2026.csv"
PROFILES = "raw/reference/player_profiles/player_profiles.csv"


class S3:
    def __init__(self, etags):
        self.etags = etags
        self.downloads = []
        self.fail_on = None

    def get_paginator(self, _name):
        return self

    def paginate(self, **_kwargs):
        keys = sorted(self.etags)
        return [
            {"Contents": [{"Key": "raw/"}] + [{"Key": key, "ETag": self.etags[key]} for key in keys[:2]]},
            {"Contents": [{"Key": key, "ETag": self.etags[key]} for key in keys[2:]]},
        ]

    def download_file(self, _bucket, key, target):
        if key == self.fail_on:
            raise RuntimeError("s3 down")
        self.downloads.append(key)
        Path(target).write_text(self.etags[key])


class VolumeSyncTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.volumes = {name: str(self.root / name) for name in ("matchdays", "fixtures", "profiles")}
        self.manifest = str(self.root / "state" / "copied_etags.json")
        self.s3 = S3({MATCHDAY: "a1", FIXTURES: "b1", PROFILES: "c1"})

    def sync(self):
        return volume_sync.sync_s3_to_volumes(self.s3, "bucket", "raw/", self.volumes, self.manifest)

    def test_each_file_goes_to_the_volume_its_loader_reads(self):
        downloaded, skipped = self.sync()
        self.assertEqual((len(downloaded), skipped), (3, 0))
        self.assertTrue((self.root / "matchdays/2026/ENG_PREMIER_LEAGUE_MATCHDAY_01.csv").exists())
        # A fixture key contains season_2026 but must stay out of the matchday volume.
        self.assertTrue((self.root / "fixtures/league_39_season_2026.csv").exists())
        self.assertFalse((self.root / "matchdays/2026/league_39_season_2026.csv").exists())
        self.assertTrue((self.root / "profiles/player_profiles.csv").exists())

    def test_default_volumes_keep_fixtures_in_their_own_folder(self):
        root = volume_sync.VOLUME_ROOT
        self.assertEqual(volume_sync.destination(MATCHDAY),
                         f"{root}/football_data/2026/ENG_PREMIER_LEAGUE_MATCHDAY_01.csv")
        self.assertEqual(volume_sync.destination(FIXTURES),
                         f"{root}/football_data/fixtures/league_39_season_2026.csv")
        self.assertEqual(volume_sync.destination(PROFILES),
                         f"{root}/player_profiles_data/player_profiles.csv")

    def test_second_run_downloads_only_changed_or_missing_files(self):
        self.sync()
        self.s3.downloads.clear()
        self.assertEqual(self.sync(), ([], 3))

        self.s3.etags[MATCHDAY] = "a2"
        (self.root / "profiles/player_profiles.csv").unlink()
        downloaded, skipped = self.sync()
        self.assertEqual((sorted(downloaded), skipped), ([MATCHDAY, PROFILES], 1))
        self.assertEqual((self.root / "matchdays/2026/ENG_PREMIER_LEAGUE_MATCHDAY_01.csv").read_text(), "a2")

    def test_failed_run_keeps_completed_downloads(self):
        self.s3.fail_on = PROFILES
        with self.assertRaises(RuntimeError):
            self.sync()
        self.s3.fail_on = None
        self.s3.downloads.clear()
        downloaded, skipped = self.sync()
        self.assertEqual((downloaded, skipped), ([PROFILES], 2))


if __name__ == "__main__":
    unittest.main()
