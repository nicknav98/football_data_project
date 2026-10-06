#!/usr/bin/env python3
"""Sync player profile fields into a separate S3 CSV snapshot."""

import json
import os
from datetime import datetime, timedelta, timezone

import pandas as pd

import sportmonks
import sync_matchday_stats as matchdays


PROFILE_CACHE_PATH = matchdays.STATE_PATH.parent / "player_profiles.json"
OUTPUT_PATH = matchdays.OUTPUT_DIR / "reference" / "player_profiles" / "player_profiles.csv"
PROFILE_COLUMNS = (
    "player_id", "name", "firstname", "lastname", "age", "birth_date",
    "birth_place", "birth_country", "nationality", "height", "weight",
    "injured", "photo", "position", "detailed_position",
    "source_league_id", "source_season", "fetched_at",
)
# Nullable whole numbers; Int64 keeps "30" rather than "30.0" next to blanks,
# which the bronze loader's integer columns would otherwise read as null.
PROFILE_INT_COLUMNS = ("player_id", "age", "source_league_id", "source_season")


def fetch_profiles():
    """One profile per player from every team's squad in each league season."""
    return sportmonks.fetch_profiles(matchdays.LEAGUES, matchdays.SEASONS)


def load_or_fetch_profiles(fetch=fetch_profiles):
    """Reuse a completed profile scan when resuming an interrupted run."""
    cache_hours = int(os.environ.get("PLAYER_PROFILE_CACHE_HOURS", 168))
    if cache_hours < 0:
        raise ValueError("PLAYER_PROFILE_CACHE_HOURS must be zero or greater")
    if PROFILE_CACHE_PATH.exists():
        cached = json.loads(PROFILE_CACHE_PATH.read_text())
        age = datetime.now(timezone.utc) - datetime.fromisoformat(cached["saved_at"])
        if age < timedelta(hours=cache_hours):
            print(f"Reusing {len(cached['profiles'])} cached player profiles")
            return {int(key): value for key, value in cached["profiles"].items()}
    profiles = fetch()
    PROFILE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    pending = PROFILE_CACHE_PATH.with_suffix(".tmp")
    pending.write_text(json.dumps({
        "saved_at": datetime.now(timezone.utc).isoformat(), "profiles": profiles,
    }))
    pending.replace(PROFILE_CACHE_PATH)
    return profiles


def write_snapshot(s3, rows):
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows, columns=PROFILE_COLUMNS)
    for column in PROFILE_INT_COLUMNS:
        frame[column] = frame[column].astype("Int64")
    frame.to_csv(OUTPUT_PATH, index=False)
    relative_key = "reference/player_profiles/player_profiles.csv"
    key = f"{matchdays.AWS_S3_PREFIX}/{relative_key}" if matchdays.AWS_S3_PREFIX else relative_key
    matchdays.upload_to_s3(s3, OUTPUT_PATH, key)
    return len(rows)


def main():
    profiles = load_or_fetch_profiles()
    s3 = matchdays.build_s3_client()
    profile_count = write_snapshot(s3, profiles.values())
    print(f"Synced {profile_count} player profiles")


if __name__ == "__main__":
    main()
