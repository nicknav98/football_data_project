#!/usr/bin/env python3
"""
Sync per-matchday player stats from api-football to Amazon S3.

Writes one CSV per finished matchday (ENG_Premier_League_Matchday_NN.csv) and
upserts each into an S3 bucket/prefix by filename, so a Databricks
SCD Type 1/2 ingestion job always finds one file per matchday to diff against.

Idempotent and safe to run on a schedule (cron/launchd): a matchday is only
(re)fetched and re-uploaded when its set of finished fixtures has grown, or
when it finished recently enough that api-football might still be correcting
stats (see STABILITY_WINDOW).
"""
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "state" / "processed_rounds.json"
OUTPUT_DIR = ROOT / "output"

BASE_URL = "https://v3.football.api-sports.io"
FINISHED_STATUSES = {"FT", "AET", "PEN"}
STABILITY_WINDOW = timedelta(hours=12)  # re-check matchdays finished more recently than this
MIN_INTERVAL = 60 / 300  # seconds -> Pro plan's 300 req/min cap


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

LEAGUE_ID = int(os.environ.get("FOOTBALL_LEAGUE_ID", 39))  # Premier League
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

        r = http_session.get(f"{BASE_URL}{path}", params=params)
        _last_request_time = time.monotonic()

        if r.status_code == 429:
            retry_after = int(r.headers.get("Retry-After", MIN_INTERVAL * 2))
            print(f"429 rate limited, backing off {retry_after}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(retry_after)
            continue

        r.raise_for_status()
        return r.json()

    r.raise_for_status()  # retries exhausted, surface the last error


def get_rounds():
    """List valid `round` names for the league/season, e.g. 'Regular Season - 5'."""
    return api_get(
        "/fixtures/rounds",
        params={"league": LEAGUE_ID, "season": SEASON, "current": "false"},
    )["response"]


def get_fixtures_for_round(round_name):
    return api_get(
        "/fixtures", params={"league": LEAGUE_ID, "season": SEASON, "round": round_name}
    )["response"]


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


def matchday_number(round_name):
    """'Regular Season - 5' -> 5. Falls back to a filesystem-safe slug for
    round names that don't end in a number (e.g. cup rounds)."""
    m = re.search(r"(\d+)\s*$", round_name)
    if m:
        return int(m.group(1))
    return re.sub(r"[^A-Za-z0-9]+", "_", round_name).strip("_")


def matchday_filename(round_name):
    md = matchday_number(round_name)
    suffix = f"{md:02d}" if isinstance(md, int) else md
    return f"ENG_Premier_League_Matchday_{suffix}.csv"


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def round_needs_processing(round_name, finished_fixtures, state):
    """Reprocess if we've never synced this round, if its set of finished
    fixtures has grown since last sync, or if any finished fixture is recent
    enough that api-football might still be correcting its stats."""
    prev = state.get(round_name)
    finished_ids = sorted(f["fixture"]["id"] for f in finished_fixtures)

    if prev is None or sorted(prev.get("finished_fixture_ids", [])) != finished_ids:
        return True

    now = datetime.now(timezone.utc)
    for f in finished_fixtures:
        kickoff = datetime.fromisoformat(f["fixture"]["date"])
        if now - kickoff < STABILITY_WINDOW:
            return True

    return False


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
    """Upsert by key: uploading to the same key overwrites the existing
    object in place, so re-syncing a matchday updates the same S3 object
    rather than creating duplicates. Returns the s3:// URI."""
    s3.upload_file(str(local_path), AWS_S3_BUCKET, key, ExtraArgs={"ContentType": "text/csv"})
    uri = f"s3://{AWS_S3_BUCKET}/{key}"
    print(f"  uploaded to {uri}")
    return uri


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    s3 = build_s3_client()

    rounds = get_rounds()
    print(f"{len(rounds)} matchdays found for league {LEAGUE_ID} season {SEASON}")

    any_synced = False
    for round_name in rounds:
        fixtures = get_fixtures_for_round(round_name)
        finished = [f for f in fixtures if f["fixture"]["status"]["short"] in FINISHED_STATUSES]

        if not finished:
            print(f"'{round_name}': 0/{len(fixtures)} finished - skipping (not played yet)")
            continue

        if not round_needs_processing(round_name, finished, state):
            print(f"'{round_name}': {len(finished)}/{len(fixtures)} finished - already synced, no changes")
            continue

        print(f"'{round_name}': {len(finished)}/{len(fixtures)} finished - (re)fetching player stats")
        rows = []
        for f in finished:
            fixture_id = f["fixture"]["id"]
            payload = get_fixture_player_stats(fixture_id)
            rows.extend(flatten_fixture_players(fixture_id, round_name, payload))

        df = pd.DataFrame(rows)
        df.insert(0, "season", SEASON)
        df.insert(0, "league_id", LEAGUE_ID)

        filename = matchday_filename(round_name)
        local_path = OUTPUT_DIR / filename
        df.to_csv(local_path, index=False)
        print(f"  wrote {len(df)} rows x {len(df.columns)} cols to {local_path}")

        key = f"{AWS_S3_PREFIX}/{filename}" if AWS_S3_PREFIX else filename
        s3_uri = upload_to_s3(s3, local_path, key)

        state[round_name] = {
            "finished_fixture_ids": sorted(f["fixture"]["id"] for f in finished),
            "last_synced": datetime.now(timezone.utc).isoformat(),
            "s3_uri": s3_uri,
        }
        save_state(state)
        any_synced = True

    if not any_synced:
        print("No matchdays needed syncing.")


if __name__ == "__main__":
    main()
