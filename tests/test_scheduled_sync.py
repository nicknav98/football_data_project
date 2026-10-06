"""Checks for the unattended sync wrapper."""

import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import scheduled_sync


class ScheduledSyncTests(unittest.TestCase):
    def test_profiles_are_due_without_a_cache_or_when_it_is_old(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "player_profiles.json"
            self.assertTrue(scheduled_sync.profiles_are_due(cache, 168))
            cache.write_text("{}")
            self.assertFalse(scheduled_sync.profiles_are_due(cache, 168))
            eight_days_ago = time.time() - 8 * 24 * 3600
            os.utime(cache, (eight_days_ago, eight_days_ago))
            self.assertTrue(scheduled_sync.profiles_are_due(cache, 168))

    def test_a_large_log_is_set_aside(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "logs" / "sync.log"
            log_path.parent.mkdir()
            log_path.write_text("old run\n")
            with patch.multiple(scheduled_sync, LOG_PATH=log_path, MAX_LOG_BYTES=4):
                scheduled_sync.open_log().close()
            self.assertEqual(log_path.read_text(), "")
            self.assertEqual(log_path.with_suffix(".previous.log").read_text(), "old run\n")


if __name__ == "__main__":
    unittest.main()
