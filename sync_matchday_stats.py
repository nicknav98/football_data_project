#!/usr/bin/env python3
"""Sync three seasons of matchday player stats and fixtures for five European leagues."""
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

import sportmonks

ROOT =Path(__file__).resolve().parent
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
FIXTURE_COLUMNS = (
    "league_id", "season", "round", "fixture_id", "kickoff_utc", "status",
    "referee", "venue_id", "venue_name", "venue_city",
    "home_team_id", "home_team_name", "away_team_id", "away_team_name",
    "home_goals", "away_goals", "halftime_home_goals", "halftime_away_goals",
)
# Nullable whole numbers; Int64 keeps "2" rather than "2.0" next to blanks.
FIXTURE_INT_COLUMNS = (
    "venue_id", "home_team_id", "away_team_id",
    "home_goals", "away_goals", "halftime_home_goals", "halftime_away_goals",
)
# Matchday columns the bronze loader reads as integers. A substitute who did
# not play has blanks here, which would otherwise turn the column into floats.
MATCHDAY_INT_COLUMNS = (
    "fixture_id", "team_id", "player_id", "games_number", "passes_accuracy", "cards_yellow", "cards_red", "penalty_scored",
)


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
HISTORY_SEASONS = int(os.environ.get("FOOTBALL_HISTORY_SEASONS", 2))
if HISTORY_SEASONS < 0:
    raise ValueError("FOOTBALL_HISTORY_SEASONS must be zero or greater")
SEASONS = tuple(range(SEASON - HISTORY_SEASONS, SEASON + 1))
PROVIDER = os.environ.get("FOOTBALL_DATA_PROVIDER", "api_football")
if PROVIDER not in ("api_football", "sportmonks"):
    raise ValueError("FOOTBALL_DATA_PROVIDER must be api_football or sportmonks")
AWS_S3_BUCKET = os.environ["AWS_S3_BUCKET"]
AWS_REGION = os.environ.get("AWS_REGION")  # optional - falls back to the default provider chain

http_session = requests.Session()
if PROVIDER == "sportmonks":
    # Sportmonks has its own fixture, team, and player IDs. Its files, state,
    # and S3 prefix stay apart from API-Football's so the two never mix in bronze.
    STATE_PATH = ROOT / "state" / "sportmonks" / "processed_fixtures.json"
    OUTPUT_DIR = ROOT / "output" / "sportmonks"
    AWS_S3_PREFIX = os.environ["SPORTMONKS_S3_PREFIX"].strip("/")
else:
    AWS_S3_PREFIX = os.environ.get("AWS_S3_PREFIX", "").strip("/")
    http_session.headers.update({"x-apisports-key": os.environ["FOOTBALL_API_KEY"]})
_last_request_time = 0.0


def api_get(path, params=None, max_retries=3):
    """GET with pacing and bounded retries for transient API failures."""
    global _last_request_time
    for attempt in range(max_retries + 1):
        wait = MIN_INTERVAL - (time.monotonic() - _last_request_time)
        if wait > 0:
            time.sleep(wait)

        try:
            r = http_session.get(f"{BASE_URL}{path}", params=params, timeout=(10, 30))
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            _last_request_time = time.monotonic()
            if attempt == max_retries:
                raise
            backoff = min(2 ** attempt, 30)
            print(f"{path} connection failed ({type(exc).__name__}); retrying in {backoff}s")
            time.sleep(backoff)
            continue
        _last_request_time = time.monotonic()

        if r.status_code == 429 or 500 <= r.status_code < 600:
            if attempt == max_retries:
                r.raise_for_status()
            backoff = min(2 ** attempt, 30)
            if r.status_code == 429:
                try:
                    backoff = max(backoff, float(r.headers.get("Retry-After", 0)))
                except ValueError:
                    pass
            print(f"{path} returned HTTP {r.status_code}; retrying in {backoff:g}s")
            time.sleep(backoff)
            continue

        r.raise_for_status()
        payload = r.json()
        if payload.get("errors"):
            raise ValueError(f"API-Football error on {path}: {payload['errors']}")
        return payload


def get_fixtures(league_id, season):
    if PROVIDER == "sportmonks":
        return sportmonks.get_fixtures(league_id, season)
    return api_get("/fixtures", params={"league": league_id, "season": season})["response"]


def get_fixture_player_stats(fixture_id):
    """Raw per-player statistics for both teams in a single fixture."""
    if PROVIDER == "sportmonks":
        return sportmonks.get_fixture_player_stats(fixture_id)
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


def fixture_identity(league_id, season, fixture_id):
    return f"{league_id}:{season}:{fixture_id}"


def matchday_path(league_id, season, round_name):
    match = re.search(r"(?:^|\s-\s)(\d+)\s*$", round_name)
    suffix = (f"{int(match.group(1)):02d}" if match else
              re.sub(r"[^A-Z0-9]+", "_", round_name.upper()).strip("_"))
    if not suffix:
        raise ValueError("Round name cannot be empty")
    country, league_name = LEAGUES[league_id]
    filename = f"{country}_{league_name}_MATCHDAY_{suffix}.csv"
    return f"league_{league_id}/season_{season}/{filename}"


def fixtures_path(league_id, season):
    return f"reference/fixtures/league_{league_id}_season_{season}.csv"


def flatten_fixture(league_id, season, fixture):
    """One row of match context per fixture, whether or not it has been played."""
    info = fixture["fixture"]
    venue = info.get("venue") or {}
    teams = fixture.get("teams") or {}
    home, away = teams.get("home") or {}, teams.get("away") or {}
    goals = fixture.get("goals") or {}
    halftime = (fixture.get("score") or {}).get("halftime") or {}
    return {
        "league_id": league_id,
        "season": season,
        "round": fixture["league"]["round"],
        "fixture_id": info["id"],
        "kickoff_utc": info.get("date"),
        "status": (info.get("status") or {}).get("short"),
        "referee": info.get("referee"),
        "venue_id": venue.get("id"),
        "venue_name": venue.get("name"),
        "venue_city": venue.get("city"),
        "home_team_id": home.get("id"),
        "home_team_name": home.get("name"),
        "away_team_id": away.get("id"),
        "away_team_name": away.get("name"),
        "home_goals": goals.get("home"),
        "away_goals": goals.get("away"),
        "halftime_home_goals": halftime.get("home"),
        "halftime_away_goals": halftime.get("away"),
    }


def sync_fixtures(league_id, season, fixtures, s3):
    """Upload the league-season fixture list when its content has changed."""
    rows = [flatten_fixture(league_id, season, fixture) for fixture in fixtures]
    df = pd.DataFrame(rows, columns=FIXTURE_COLUMNS).sort_values("fixture_id")
    for column in FIXTURE_INT_COLUMNS:
        df[column] = df[column].astype("Int64")
    content = df.to_csv(index=False).encode("utf-8")

    relative_path = fixtures_path(league_id, season)
    local_path = OUTPUT_DIR / relative_path
    if local_path.exists() and local_path.read_bytes() == content:
        return False

    # The local copy marks a completed upload, so it is replaced only afterwards.
    local_path.parent.mkdir(parents=True, exist_ok=True)
    pending = local_path.with_suffix(".tmp")
    pending.write_bytes(content)
    key = f"{AWS_S3_PREFIX}/{relative_path}" if AWS_S3_PREFIX else relative_path
    upload_to_s3(s3, pending, key)
    pending.replace(local_path)
    print(f"  wrote {len(df)} fixtures to {local_path}")
    return True


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    pending = STATE_PATH.with_suffix(".tmp")
    pending.write_text(json.dumps(state, indent=2))
    pending.replace(STATE_PATH)


def fixture_needs_processing(league_id, season, fixture, state):
    """Fetch new fixtures and recheck fixtures within the correction window."""
    fixture_id = fixture["fixture"]["id"]
    previous = state.get(fixture_identity(league_id, season, fixture_id))
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


def sync_league_season(league_id, season, state, s3):
    fixtures = get_fixtures(league_id, season)
    if not fixtures:
        raise ValueError(f"No fixtures returned for league {league_id}, season {season}")
    print(f"{len(fixtures)} fixtures found for league {league_id} season {season}")
    rounds = defaultdict(list)
    for fixture in fixtures:
        if fixture["league"]["id"] != league_id or fixture["league"]["season"] != season:
            raise ValueError(f"Fixture {fixture['fixture']['id']} does not match league {league_id}, season {season}")
        if fixture["fixture"]["status"]["short"] in FINISHED_STATUSES:
            rounds[fixture["league"]["round"]].append(fixture)

    sync_fixtures(league_id, season, fixtures, s3)

    paths = [matchday_path(league_id, season, round_name) for round_name in rounds]
    if len(paths) != len(set(paths)):
        raise ValueError(f"League {league_id}, season {season} has rounds that map to the same matchday file")

    synced = 0
    for round_name, finished in rounds.items():
        if not any(fixture_needs_processing(league_id, season, f, state) for f in finished):
            continue

        # A matchday file is replaced as a unit. Fetch every finished fixture
        # in the round so postponed matches and corrections remain together.
        rows = []
        for fixture in finished:
            fixture_id = fixture["fixture"]["id"]
            print(f"league {league_id}, season {season}, fixture {fixture_id}: fetching player stats")
            payload = get_fixture_player_stats(fixture_id)
            fixture_rows = flatten_fixture_players(fixture_id, round_name, payload)
            if not fixture_rows:
                raise ValueError(f"Fixture {fixture_id} returned no player statistics; leaving state unchanged")
            rows.extend(fixture_rows)

        df = pd.DataFrame(rows)
        df.insert(0, "season", season)
        df.insert(0, "league_id", league_id)
        for column in MATCHDAY_INT_COLUMNS:
            if column in df:
                df[column] = df[column].astype("Int64")

        relative_path = matchday_path(league_id, season, round_name)
        local_path = OUTPUT_DIR / relative_path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(local_path, index=False)
        print(f"  wrote {len(df)} rows x {len(df.columns)} cols to {local_path}")

        key = f"{AWS_S3_PREFIX}/{relative_path}" if AWS_S3_PREFIX else relative_path
        s3_uri = upload_to_s3(s3, local_path, key)

        synced_at = datetime.now(timezone.utc).isoformat()
        for fixture in finished:
            fixture_id = fixture["fixture"]["id"]
            state[fixture_identity(league_id, season, fixture_id)] = {
                "league_id": league_id,
                "season": season,
                "fixture_id": fixture_id,
                "round": round_name,
                "output_format": "matchday",
                "last_synced": synced_at,
                "s3_uri": s3_uri,
            }
        save_state(state)
        synced += 1
    return synced


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    s3 = build_s3_client()

    synced = 0
    for season in SEASONS:
        for league_id in LEAGUES:
            synced += sync_league_season(league_id, season, state, s3)

    if not synced:
        print("No matchdays needed syncing.")


if __name__ == "__main__":
    main()
