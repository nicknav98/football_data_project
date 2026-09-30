#!/usr/bin/env python3
"""Sync player profile fields into a separate S3 CSV snapshot."""

import json
import os
from datetime import datetime, timedelta, timezone

import pandas as pd

import sync_matchday_stats as matchdays


PROFILE_CACHE_PATH = matchdays.ROOT / "state" / "player_profiles.json"
OUTPUT_PATH = matchdays.OUTPUT_DIR / "reference" / "player_profiles" / "player_profiles.csv"
PROFILE_COLUMNS = (
    "player_id", "name", "firstname", "lastname", "age", "birth_date",
    "birth_place", "birth_country", "nationality", "height", "weight",
    "injured", "photo", "source_league_id", "source_season", "fetched_at",
)


def fetch_profiles(api_get=matchdays.api_get):
    """Read all pages for each league and season, keeping one player row."""
    profiles = {}
    fetched_at = datetime.now(timezone.utc).isoformat()
    for season in matchdays.SEASONS:
        for league_id in matchdays.LEAGUES:
            print(f"Fetching profiles for league {league_id}, season {season}", flush=True)
            page = 1
            while True:
                try:
                    payload = api_get("/players", {"league": league_id, "season": season, "page": page})
                except Exception as exc:
                    raise RuntimeError(
                        f"Profile fetch failed for league {league_id}, season {season}, page {page}"
                    ) from exc
                paging = payload.get("paging") or {}
                current = int(paging.get("current", page))
                total = int(paging.get("total", 1))
                if current != page or total < page:
                    raise ValueError(f"Invalid /players paging for league {league_id}, season {season}")
                if page == 1 and not payload.get("response"):
                    raise ValueError(f"No players for league {league_id}, season {season}")
                for item in payload["response"]:
                    player = item["player"]
                    player_id = player["id"]
                    birth = player.get("birth") or {}
                    profiles[player_id] = {
                        "player_id": player_id,
                        "name": player.get("name"),
                        "firstname": player.get("firstname"),
                        "lastname": player.get("lastname"),
                        "age": player.get("age"),
                        "birth_date": birth.get("date"),
                        "birth_place": birth.get("place"),
                        "birth_country": birth.get("country"),
                        "nationality": player.get("nationality"),
                        "height": player.get("height"),
                        "weight": player.get("weight"),
                        "injured": player.get("injured"),
                        "photo": player.get("photo"),
                        "source_league_id": league_id,
                        "source_season": season,
                        "fetched_at": fetched_at,
                    }
                if page == total:
                    break
                page += 1
            print(f"  completed {total} pages; {len(profiles)} distinct players", flush=True)
    return profiles


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
    pd.DataFrame(rows, columns=PROFILE_COLUMNS).to_csv(OUTPUT_PATH, index=False)
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
