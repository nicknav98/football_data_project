"""HTTP serving point for gold player data and scouting questions."""

from __future__ import annotations

from functools import lru_cache
import os
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from scout_backend import GoldRepository, LeaderboardArgs, RANK_METRICS, ScoutAssistant


app = FastAPI(title="Football scout API", version="1.0.0")


class ScoutQuestion(BaseModel):
    question: str = Field(min_length=8, max_length=600)

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
    return ScoutAssistant(repository(), OpenAI(timeout=30, max_retries=1), model)


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
    return {"ranking_metrics": sorted(RANK_METRICS)}


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


@app.post("/scout/ask", dependencies=[Depends(require_scout_key)])
def ask_scout(question: ScoutQuestion) -> dict:
    try:
        return assistant().ask(question.question)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Scouting assistant is unavailable") from exc
