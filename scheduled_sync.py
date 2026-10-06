#!/usr/bin/env python3
"""Run both syncs unattended and log to logs/sync.log.

Windows Task Scheduler runs this with pythonw.exe, which has no console, so
all output goes to the log. See docs/operations.md for the task.
"""
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG_PATH = ROOT / "logs" / "sync.log"
MAX_LOG_BYTES = 5_000_000


def open_log():
    LOG_PATH.parent.mkdir(exist_ok=True)
    # Keep one previous log so the file cannot grow without limit.
    if LOG_PATH.exists() and LOG_PATH.stat().st_size > MAX_LOG_BYTES:
        LOG_PATH.replace(LOG_PATH.with_suffix(".previous.log"))
    return open(LOG_PATH, "a", encoding="utf-8", buffering=1)


def profiles_are_due(cache_path, cache_hours):
    """True when there is no completed profile scan younger than the cache period."""
    if not cache_path.exists():
        return True
    return time.time() - cache_path.stat().st_mtime > cache_hours * 3600


def main():
    os.chdir(ROOT)
    log = open_log()
    sys.stdout = sys.stderr = log
    print(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} sync started")
    try:
        import sync_matchday_stats
        import sync_player_profiles

        sync_matchday_stats.main()
        cache_hours = int(os.environ.get("PLAYER_PROFILE_CACHE_HOURS", 168))
        if profiles_are_due(sync_player_profiles.PROFILE_CACHE_PATH, cache_hours):
            sync_player_profiles.main()
        else:
            print("Player profiles are up to date.")
    except Exception:
        traceback.print_exc()
        print(f"=== {datetime.now():%Y-%m-%d %H:%M:%S} sync FAILED")
        return 1
    print(f"=== {datetime.now():%Y-%m-%d %H:%M:%S} sync finished")
    return 0


if __name__ == "__main__":
    sys.exit(main())
