"""Sportmonks v3 client that returns data in the shapes the sync scripts already use.

Fixtures and player statistics are converted to the API-Football layout, so
sync_matchday_stats.py writes the same CSV columns for either provider.
Fixture, team, and player IDs are Sportmonks IDs. League IDs and seasons stay
as the project has always written them (39 for the Premier League, 2025 for
2025/26), because paths, silver, gold, and the scout API are keyed on them.
"""
import os
import time
from datetime import date, datetime, timezone

import requests

BASE_URL = "https://api.sportmonks.com/v3/football"
MIN_INTERVAL = 0.2  # seconds between requests
# Project league ID -> Sportmonks league ID.
LEAGUE_IDS = {39: 8, 140: 564, 78: 82, 135: 384, 61: 301}
# Sportmonks state -> the finished statuses the pipeline checks for. Other
# states pass through under their Sportmonks name.
STATUSES = {"FT": "FT", "AET": "AET", "FT_PEN": "PEN"}
POSITIONS = {24: "G", 25: "D", 26: "M", 27: "F"}
BENCH = 12  # lineup type of a player named as a substitute
MAIN_REFEREE = 6
FIXTURE_INCLUDES = "round;state;venue;participants;scores;referees.referee"
LINEUP_INCLUDES = "participants;lineups.details.type;lineups.detailedPosition"
SQUAD_INCLUDES = "player.nationality;player.position;player.detailedPosition"

# CSV column -> Sportmonks statistic code, for whole-number counts.
COUNTS = {
    "offsides": "offsides",
    "shots_total": "shots-total",
    "shots_on": "shots-on-target",
    "goals_total": "goals",
    "goals_conceded": "goals-conceded",
    "goals_assists": "assists",
    "goals_saves": "saves",
    "passes_total": "passes",
    "passes_key": "key-passes",
    "passes_accuracy": "accurate-passes",  # a count, as in API-Football
    "tackles_total": "tackles",
    "tackles_blocks": "blocked-shots",
    "tackles_interceptions": "interceptions",
    "duels_total": "total-duels",
    "duels_won": "duels-won",
    "dribbles_attempts": "dribble-attempts",
    "dribbles_success": "successful-dribbles",
    "dribbles_past": "dribbled-past",
    "fouls_drawn": "fouls-drawn",
    "fouls_committed": "fouls",
    "cards_yellow": "yellowcards",
    "cards_red": "redcards",
    "penalty_won": "penalties-won",
    "penalty_commited": "penalties-committed",
    "penalty_scored": "penalties-scored",
    "penalty_missed": "penalties-missed",
    "penalty_saved": "penalties-saved",
}
GOALKEEPER_ONLY = {"goals_saves", "penalty_saved"}

_session = requests.Session()
_last_request_time = 0.0
_season_ids = {}


def api_get(path, params=None, max_retries=3):
    """GET with pacing, bounded retries, and a wait when the hourly limit runs out."""
    global _last_request_time
    _session.headers["Authorization"] = os.environ["SPORTMONKS_API_TOKEN"]
    for attempt in range(max_retries + 1):
        wait = MIN_INTERVAL - (time.monotonic() - _last_request_time)
        if wait > 0:
            time.sleep(wait)

        try:
            r = _session.get(f"{BASE_URL}{path}", params=params, timeout=(10, 60))
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
                backoff = max(backoff, _seconds_until_reset(r))
            print(f"{path} returned HTTP {r.status_code}; retrying in {backoff:g}s")
            time.sleep(backoff)
            continue

        r.raise_for_status()
        payload = r.json()
        if "data" not in payload:
            raise ValueError(f"Sportmonks error on {path}: {payload.get('message', payload)}")
        # Each entity has its own hourly allowance. Wait out the hour here
        # so a long backfill resumes by itself.
        limit = payload.get("rate_limit") or {}
        if limit.get("remaining") == 0:
            pause = limit.get("resets_in_seconds", 0)
            print(f"Sportmonks {limit.get('requested_entity')} limit reached; waiting {pause}s")
            time.sleep(pause)
        return payload


def _seconds_until_reset(response):
    try:
        return float((response.json().get("rate_limit") or {}).get("resets_in_seconds", 0))
    except ValueError:
        return 0.0


def get_pages(path, params):
    rows, page = [], 1
    while True:
        payload = api_get(path, {**params, "per_page": 50, "page": page})
        rows.extend(payload["data"])
        if not (payload.get("pagination") or {}).get("has_more"):
            return rows
        page += 1


def season_id(league_id, season):
    """Sportmonks season ID for a project league and starting year."""
    if league_id not in _season_ids:
        league = api_get(f"/leagues/{LEAGUE_IDS[league_id]}", {"include": "seasons"})["data"]
        _season_ids[league_id] = {int(s["name"][:4]): s["id"] for s in league["seasons"]}
    if season not in _season_ids[league_id]:
        raise ValueError(f"Sportmonks has no season {season} for league {league_id}")
    return _season_ids[league_id][season]


def get_fixtures(league_id, season):
    rows = get_pages("/fixtures", {
        "filters": f"fixtureSeasons:{season_id(league_id, season)}",
        "include": FIXTURE_INCLUDES,
    })
    return [to_fixture(league_id, season, row) for row in rows]


def to_fixture(league_id, season, row):
    """One Sportmonks fixture in the API-Football /fixtures layout."""
    sides = {p["meta"]["location"]: p for p in row.get("participants") or []}

    def goals(description):
        found = {s["score"]["participant"]: s["score"]["goals"]
                 for s in row.get("scores") or [] if s["description"] == description}
        return {"home": found.get("home"), "away": found.get("away")}

    # Sportmonks names league rounds "1" to "38"; keep the wording the
    # pipeline has always stored.
    round_name = str((row.get("round") or {}).get("name") or "").strip()
    if round_name.isdigit():
        round_name = f"Regular Season - {int(round_name)}"
    state = (row.get("state") or {}).get("developer_name")
    venue = row.get("venue") or {}
    referee = next((r["referee"]["name"] for r in row.get("referees") or []
                    if r["type_id"] == MAIN_REFEREE and r.get("referee")), None)
    return {
        "fixture": {
            "id": row["id"],
            "date": row["starting_at"].replace(" ", "T") + "+00:00",
            "status": {"short": STATUSES.get(state, state)},
            "referee": referee,
            "venue": {"id": venue.get("id"), "name": venue.get("name"), "city": venue.get("city_name")},
        },
        "league": {"id": league_id, "season": season, "round": round_name or "No Round"},
        "teams": {side: {"id": team["id"], "name": team["name"]} for side, team in sides.items()},
        "goals": goals("CURRENT"),
        "score": {"halftime": goals("1ST_HALF")},
    }


def get_fixture_player_stats(fixture_id):
    row = api_get(f"/fixtures/{fixture_id}", {"include": LINEUP_INCLUDES})["data"]
    return to_player_stats(row)


def to_player_stats(row):
    """One fixture's lineups in the API-Football /fixtures/players layout."""
    lineups = row.get("lineups") or []
    values = [{d["type"]["code"]: d["data"].get("value") for d in entry.get("details") or []}
              for entry in lineups]
    # Sportmonks leaves a statistic out when it is zero. When the fixture has
    # detailed statistics, a count missing for a player who played is zero.
    detailed = any("passes" in stats for stats in values)
    teams = {team["id"]: {"team": {"id": team["id"], "name": team["name"]}, "players": []}
             for team in row.get("participants") or []}
    for entry, stats in zip(lineups, values):
        position = POSITIONS.get(entry.get("position_id"))
        played = (stats.get("minutes-played") or 0) > 0
        flat = {
            "games_minutes": stats.get("minutes-played"),
            "games_number": entry.get("jersey_number"),
            "games_position": position,
            # The slot in the starting formation. Substitutes have none.
            "games_detailed_position": (entry.get("detailedposition") or {}).get("name"),
            "games_formation_field": entry.get("formation_field"),
            "games_rating": stats.get("rating"),
            "games_captain": bool(stats.get("captain")),
            "games_substitute": entry.get("type_id") == BENCH,
        }
        for column, code in COUNTS.items():
            value = stats.get(code)
            if (value is None and played and detailed
                    and (column not in GOALKEEPER_ONLY or position == "G")):
                value = 0
            flat[column] = value
        # A second yellow is a sending off.
        if stats.get("yellowred-cards"):
            flat["cards_red"] = (flat["cards_red"] or 0) + stats["yellowred-cards"]
        teams[entry["team_id"]]["players"].append({
            "player": {"id": entry["player_id"], "name": entry["player_name"].strip()},
            "statistics": [flat],
        })
    return {"response": list(teams.values())}


def fetch_profiles(leagues, seasons):
    """One profile per player from every team's squad in each league season."""
    profiles = {}
    today = date.today()
    fetched_at = datetime.now(timezone.utc).isoformat()
    for season in seasons:
        for league_id in leagues:
            print(f"Fetching profiles for league {league_id}, season {season}", flush=True)
            sportmonks_season = season_id(league_id, season)
            teams = api_get(f"/teams/seasons/{sportmonks_season}")["data"]
            if not teams:
                raise ValueError(f"No teams for league {league_id}, season {season}")
            for team in teams:
                squad = api_get(f"/squads/seasons/{sportmonks_season}/teams/{team['id']}",
                                {"include": SQUAD_INCLUDES})["data"]
                for member in squad:
                    player = member.get("player")
                    if player:
                        profiles[player["id"]] = to_profile(player, league_id, season, today, fetched_at)
            print(f"  completed {len(teams)} squads; {len(profiles)} distinct players", flush=True)
    return profiles


def to_profile(player, league_id, season, today, fetched_at):
    born = player.get("date_of_birth")
    age = None
    if born:
        birth = date.fromisoformat(born)
        age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))

    def named(key):
        return (player.get(key) or {}).get("name")

    def measured(key, unit):
        return f"{player[key]} {unit}" if player.get(key) else None

    return {
        "player_id": player["id"],
        "name": (player.get("display_name") or player.get("name") or "").strip() or None,
        "firstname": player.get("firstname"),
        "lastname": player.get("lastname"),
        "age": age,
        "birth_date": born,
        "birth_place": None,
        "birth_country": None,
        "nationality": named("nationality"),
        "height": measured("height", "cm"),
        "weight": measured("weight", "kg"),
        "injured": None,
        "photo": player.get("image_path"),
        "position": named("position"),
        "detailed_position": named("detailedposition"),
        "source_league_id": league_id,
        "source_season": season,
        "fetched_at": fetched_at,
    }
