#!/usr/bin/env python3
"""Sync matchday player statistics for Europe's five major leagues to S3."""
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "state" / "processed_fixtures.json"
OUTPUT_DIR = ROOT / "output"

BASE_URL = "https://v3.football.api-sports.io"
FINISHED_STATUSES = {"FT", "AET", "PEN"}
STABILITY_WINDOW = timedelta(hours=12)
MIN_INTERVAL = 60 / 300  # seconds -> Pro plan's 300 req/min cap
LEAGUES = {
    39: ("ENG", "PREMIER_LEAGUE"),
    140: ("ESP", "LA_LIGA"),
    78: ("GER", "BUNDESLIGA"),
    135: ("ITA", "SERIE_A"),
    61: ("FRA", "LIGUE_1"),
}


def load_env(path=ROOT / ".env"):
    if not Path(path).exists():
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


load_env()

SEASON = int(os.environ.get("FOOTBALL_SEASON", 2026))
API_KEY = os.environ["FOOTBALL_API_KEY"]
AWS_S3_BUCKET = os.environ["AWS_S3_BUCKET"]
AWS_S3_PREFIX = os.environ.get("AWS_S3_PREFIX", "").strip("/")
AWS_REGION = os.environ.get("AWS_REGION")  # optional - falls back to the default provider chain

http_session = requests.Session()
http_session.headers.update({"x-apisports-key": API_KEY})
_last_request_time = 0.0


def api_get(path, params=None, max_retries=3):
    """GET with request pacing + 429 backoff, paced to the Pro plan's 300 req/min cap."""
    global _last_request_time
    for attempt in range(max_retries + 1):
        wait = MIN_INTERVAL - (time.monotonic() - _last_request_time)
        if wait > 0:
            time.sleep(wait)

        r = http_session.get(f"{BASE_URL}{path}", params=params, timeout=30)
        _last_request_time = time.monotonic()

        if r.status_code == 429:
            retry_after = int(r.headers.get("Retry-After", MIN_INTERVAL * 2))
            print(f"429 rate limited, backing off {retry_after}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(retry_after)
            continue

        r.raise_for_status()
        payload = r.json()
        if payload.get("errors"):
            raise ValueError(f"API-Football error on {path}: {payload['errors']}")
        return payload

    r.raise_for_status()  # retries exhausted, surface the last error


def get_fixtures(league_id):
    return api_get("/fixtures", params={"league": league_id, "season": SEASON})["response"]


def get_fixture_player_stats(fixture_id):
    """Raw per-player statistics for both teams in a single fixture."""
    return api_get("/fixtures/players", params={"fixture": fixture_id})


def flatten_fixture_players(fixture_id, round_name, payload):
    """One row per player per match, nested stat groups flattened to columns."""
    rows = []
    for team_block in payload["response"]:
        team = team_block["team"]
        for player_block in team_block["players"]:
            player = player_block["player"]
            for stats in player_block["statistics"]:
                flat = pd.json_normalize(stats, sep="_").iloc[0].to_dict()
                rows.append(
                    {
                        "round": round_name,
                        "fixture_id": fixture_id,
                        "team_id": team["id"],
                        "team_name": team["name"],
                        "player_id": player["id"],
                        "player_name": player["name"],
                        **flat,
                    }
                )
    return rows


def fixture_identity(league_id, fixture_id):
    return f"{league_id}:{SEASON}:{fixture_id}"


def matchday_path(league_id, round_name):
    match = re.search(r"(?:^|\s-\s)(\d+)\s*$", round_name)
    if not match:
        raise ValueError(f"Cannot determine matchday number from {round_name!r}")
    country, league_name = LEAGUES[league_id]
    filename = f"{country}_{league_name}_MATCHDAY_{int(match.group(1)):02d}.csv"
    return f"league_{league_id}/season_{SEASON}/{filename}"


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    pending = STATE_PATH.with_suffix(".tmp")
    pending.write_text(json.dumps(state, indent=2))
    pending.replace(STATE_PATH)


def fixture_needs_processing(league_id, fixture, state):
    """Fetch new fixtures and recheck fixtures within the correction window."""
    fixture_id = fixture["fixture"]["id"]
    previous = state.get(fixture_identity(league_id, fixture_id))
    if not previous or previous.get("output_format") != "matchday":
        return True
    if previous.get("round") != fixture["league"]["round"]:
        return True

    now = datetime.now(timezone.utc)
    kickoff = datetime.fromisoformat(fixture["fixture"]["date"])
    return now - kickoff < STABILITY_WINDOW


def build_s3_client():
    """Credentials come from boto3's default provider chain (env vars,
    ~/.aws/credentials, an instance/task IAM role, etc.) - nothing to manage
    here. AWS_REGION is optional and only needed if it's not already set via
    that chain (e.g. ~/.aws/config or AWS_DEFAULT_REGION)."""
    kwargs = {}
    if AWS_REGION:
        kwargs["region_name"] = AWS_REGION
    return boto3.client("s3", **kwargs)


def upload_to_s3(s3, local_path, key):
    """Upsert a matchday file at its stable league/season/matchday key."""
    s3.upload_file(str(local_path), AWS_S3_BUCKET, key, ExtraArgs={"ContentType": "text/csv"})
    uri = f"s3://{AWS_S3_BUCKET}/{key}"
    print(f"  uploaded to {uri}")
    return uri


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    s3 = build_s3_client()

    any_synced = False
    for league_id in LEAGUES:
        fixtures = get_fixtures(league_id)
        print(f"{len(fixtures)} fixtures found for league {league_id} season {SEASON}")
        rounds = defaultdict(list)
        for fixture in fixtures:
            if fixture["league"]["id"] != league_id or fixture["league"]["season"] != SEASON:
                raise ValueError(f"Fixture {fixture['fixture']['id']} does not match league {league_id}, season {SEASON}")
            if fixture["fixture"]["status"]["short"] in FINISHED_STATUSES:
                rounds[fixture["league"]["round"]].append(fixture)

        paths = [matchday_path(league_id, round_name) for round_name in rounds]
        if len(paths) != len(set(paths)):
            raise ValueError(f"League {league_id} has round names that map to the same matchday file")

        for round_name, finished in rounds.items():
            if not any(fixture_needs_processing(league_id, f, state) for f in finished):
                continue

            # A matchday file is replaced as a unit. Fetch every finished fixture
            # in the round so postponed matches and corrections remain together.
            rows = []
            for fixture in finished:
                fixture_id = fixture["fixture"]["id"]
                print(f"league {league_id}, fixture {fixture_id}: fetching player stats")
                payload = get_fixture_player_stats(fixture_id)
                fixture_rows = flatten_fixture_players(fixture_id, round_name, payload)
                if not fixture_rows:
                    raise ValueError(f"Fixture {fixture_id} returned no player statistics; leaving state unchanged")
                rows.extend(fixture_rows)

            df = pd.DataFrame(rows)
            df.insert(0, "season", SEASON)
            df.insert(0, "league_id", league_id)

            relative_path = matchday_path(league_id, round_name)
            local_path = OUTPUT_DIR / relative_path
            local_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(local_path, index=False)
            print(f"  wrote {len(df)} rows x {len(df.columns)} cols to {local_path}")

            key = f"{AWS_S3_PREFIX}/{relative_path}" if AWS_S3_PREFIX else relative_path
            s3_uri = upload_to_s3(s3, local_path, key)

            synced_at = datetime.now(timezone.utc).isoformat()
            for fixture in finished:
                fixture_id = fixture["fixture"]["id"]
                state[fixture_identity(league_id, fixture_id)] = {
                    "league_id": league_id,
                    "season": SEASON,
                    "fixture_id": fixture_id,
                    "round": round_name,
                    "output_format": "matchday",
                    "last_synced": synced_at,
                    "s3_uri": s3_uri,
                }
            save_state(state)
            any_synced = True

    if not any_synced:
        print("No matchdays needed syncing.")


if __name__ == "__main__":
    main()
