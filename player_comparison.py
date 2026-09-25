"""Load matchday CSVs from S3 and aggregate player statistics."""

from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import re

import boto3
import pandas as pd
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
IDENTITY_COLUMNS = {"league_id", "season", "fixture_id", "team_id", "player_id", "games_number"}
AVERAGE_METRICS = {"games_rating", "passes_accuracy"}
EXCLUDED_METRICS = IDENTITY_COLUMNS | {"games_minutes", "games_captain", "games_substitute"}
MATCHDAY_KEY = re.compile(r"(?:^|/)league_(\d+)/season_(\d+)/[A-Z]{3}_[A-Z0-9_]+_MATCHDAY_\d+\.csv$")
ROW_KEY = ["league_id", "season", "fixture_id", "team_id", "player_id"]


def configure_environment() -> tuple[str, str]:
    """Use shell variables first, then .env and .dotenv in the project root."""
    for filename in (".env", ".dotenv"):
        load_dotenv(ROOT / filename, override=False)
    bucket = os.getenv("AWS_S3_BUCKET", "").strip()
    if not bucket:
        raise ValueError("Set AWS_S3_BUCKET in .env, .dotenv, or the shell.")
    return bucket, os.getenv("AWS_S3_PREFIX", "").strip("/")


def read_matchdays() -> tuple[pd.DataFrame, int]:
    """Read matchday CSVs under the configured S3 prefix, including paginated keys."""
    bucket, prefix = configure_environment()
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    s3 = boto3.client("s3", region_name=region) if region else boto3.client("s3")
    listing_prefix = f"{prefix}/" if prefix else ""
    frames = []
    count = 0
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=listing_prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            match = MATCHDAY_KEY.search(key)
            if not match:
                continue
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            frame = pd.read_csv(BytesIO(body), low_memory=False)
            expected = tuple(map(int, match.groups()))
            for column, value in zip(("league_id", "season"), expected):
                if column not in frame or not frame[column].eq(value).all():
                    raise ValueError(f"{key} has an invalid {column}")
            frames.append(frame)
            count += 1
    if not frames:
        raise ValueError(f"No matchday CSV files found in s3://{bucket}/{listing_prefix}")

    data = pd.concat(frames, ignore_index=True)
    required = set(ROW_KEY) | {"player_name", "team_name"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"S3 CSV files are missing required columns: {', '.join(sorted(missing))}")
    data = data.drop_duplicates(ROW_KEY, keep="last")
    return data, count


def metric_columns(data: pd.DataFrame) -> list[str]:
    """Select numeric stats while excluding identifiers and categorical flags."""
    result = []
    for column in data.columns:
        if column in EXCLUDED_METRICS:
            continue
        numeric = pd.to_numeric(data[column], errors="coerce")
        if numeric.notna().any():
            result.append(column)
    return result


def compare_players(
    data: pd.DataFrame, player_ids: list[int], metrics: list[str], per_90: bool
) -> pd.DataFrame:
    """Aggregate selected players over filtered fixtures, with optional per-90 counts."""
    rows = []
    selected = data[data["player_id"].isin(player_ids)].copy()
    for player_id in player_ids:
        player = selected[selected["player_id"] == player_id]
        if player.empty:
            continue
        minutes = pd.to_numeric(player.get("games_minutes", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()
        row = {"player_id": player_id, "matches": len(player), "minutes": int(minutes)}
        for metric in metrics:
            values = pd.to_numeric(player[metric], errors="coerce")
            if metric == "games_rating":
                row[metric] = values.mean()
            elif metric == "passes_accuracy" and "passes_total" in player:
                weights = pd.to_numeric(player["passes_total"], errors="coerce").fillna(0)
                valid = values.notna() & (weights > 0)
                row[metric] = (values[valid] * weights[valid]).sum() / weights[valid].sum() if valid.any() else values.mean()
            elif metric in AVERAGE_METRICS:
                row[metric] = values.mean()
            else:
                total = values.sum(min_count=1)
                row[metric] = total * 90 / minutes if per_90 and minutes > 0 else (float("nan") if per_90 else total)
        rows.append(row)
    return pd.DataFrame(rows).set_index("player_id") if rows else pd.DataFrame()
