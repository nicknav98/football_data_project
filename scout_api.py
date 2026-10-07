"""HTTP serving point for gold player data and scouting questions."""

from __future__ import annotations

from functools import lru_cache
import logging
import os
from pathlib import Path
import secrets
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

from scout_backend import (
    GoldRepository, LeaderboardArgs, MODEL_REQUEST_TIMEOUT_SECONDS, RANK_METRICS, ROLE_PROFILES,
    ScoutAssistant, ShortlistArgs,
)


# Shared by the API and Streamlit chat; deployed environment variables take precedence.
load_dotenv(Path(__file__).resolve().with_name(".env"), override=False)

# Timestamped lines on stderr, which the Databricks App "Logs" tab shows. Without
# this the assistant's warnings have no time and its info lines are dropped.
# Other libraries stay at warnings so their request logs do not bury ours.
logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("scout_backend").setLevel(logging.INFO)

app = FastAPI(title="Football scout API", version="1.0.0")


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ScoutQuestion(BaseModel):
    question: str = Field(min_length=8, max_length=600)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)

    @field_validator("question")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 8:
            raise ValueError("question must contain at least eight characters")
        return value


@lru_cache
def repository() -> GoldRepository:
    return GoldRepository()


@lru_cache
def assistant() -> ScoutAssistant:
    from openai import OpenAI

    model = os.getenv("OPENAI_MODEL")
    if not model or not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Set OPENAI_MODEL and OPENAI_API_KEY")
    client = OpenAI(timeout=httpx.Timeout(MODEL_REQUEST_TIMEOUT_SECONDS, connect=10),
                    max_retries=0)
    return ScoutAssistant(repository(), client, model)


def require_scout_key(x_scout_api_key: str | None = Header(default=None)) -> None:
    expected = os.getenv("SCOUT_API_KEY")
    if not expected:
        raise HTTPException(status_code=503, detail="Scout API key is not configured")
    if not x_scout_api_key or not secrets.compare_digest(x_scout_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid scout API key")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> dict[str, list[str]]:
    return {"ranking_metrics": sorted(RANK_METRICS), "roles": sorted(ROLE_PROFILES)}


@app.get("/players")
def search_players(
    name: str = Query(min_length=2, max_length=80),
    limit: int = Query(default=10, ge=1, le=10),
    store: GoldRepository = Depends(repository),
) -> dict:
    if len(name.strip()) < 2:
        raise HTTPException(status_code=422, detail="name must contain at least two characters")
    try:
        return {"players": store.search_players(name, limit)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Player data is unavailable") from exc


@app.get("/players/{player_id}/seasons")
def player_seasons(player_id: int, store: GoldRepository = Depends(repository)) -> dict:
    if player_id <= 0:
        raise HTTPException(status_code=422, detail="player_id must be positive")
    try:
        rows = store.player_seasons(player_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Player data is unavailable") from exc
    if not rows:
        raise HTTPException(status_code=404, detail="Player not found in gold data")
    return {"seasons": rows}


@app.get("/leaderboard")
def leaderboard(
    metric: str,
    league_id: int | None = None,
    season: int | None = None,
    min_minutes: int = Query(default=450, ge=0, le=10000),
    limit: int = Query(default=10, ge=1, le=10),
    store: GoldRepository = Depends(repository),
) -> dict:
    if metric not in RANK_METRICS:
        raise HTTPException(status_code=422, detail="Unsupported metric")
    try:
        args = LeaderboardArgs(metric=metric, league_id=league_id, season=season,
                               min_minutes=min_minutes, limit=limit)
        return {"players": store.leaderboard(args)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Player data is unavailable") from exc


@app.get("/shortlist")
def shortlist(
    role: str,
    season: int,
    league_id: int | None = None,
    max_age: int | None = Query(default=None, ge=15, le=45),
    min_minutes: int = Query(default=1500, ge=90, le=10000),
    exclude_team: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=10, ge=1, le=10),
    store: GoldRepository = Depends(repository),
) -> dict:
    if role not in ROLE_PROFILES:
        raise HTTPException(status_code=422, detail="Unsupported role")
    try:
        args = ShortlistArgs(role=role, season=season, league_id=league_id,
                             max_age=max_age, min_minutes=min_minutes,
                             exclude_team=exclude_team, limit=limit)
        return {"players": store.shortlist(args)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Player data is unavailable") from exc


@app.post("/scout/ask", dependencies=[Depends(require_scout_key)])
def ask_scout(question: ScoutQuestion) -> dict:
    try:
        previous = [turn.model_dump() for turn in question.history]
        return assistant().ask(question.question, previous)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Scouting assistant is unavailable") from exc
