"""Copy new or changed S3 CSVs into the volumes the bronze loaders read.

sync_matchday_stats.py and sync_player_profiles.py upload to S3 with keys like:
  football-matchday-stats/league_39/season_2025/ENG_PREMIER_LEAGUE_MATCHDAY_01.csv
  football-matchday-stats/reference/fixtures/league_39_season_2025.csv
  football-matchday-stats/reference/player_profiles/player_profiles.csv

Each file goes to the volume its loader reads:
  matchday files  -> football_data/<YYYY>/     (databricks_matchday_stream.py)
  fixture files   -> football_data/fixtures/   (databricks_fixtures.py)
  everything else -> player_profiles_data/     (databricks_player_profiles.py)

Fixture files share the football_data volume with matchday files. The matchday
Auto Loader selects files by name, so it does not read the fixtures folder.

S3 reports an ETag for every object, which changes when its content does. The
ETag of each copied file is kept in a manifest, and a file is downloaded again
only when its ETag differs or its copy is missing from the volume. The first
run with an empty manifest copies everything.
"""
import json
import os
import re

VOLUME_ROOT = "/Volumes/workspace/football_data_project"


def volume_paths(root):
    """Destination volumes and manifest path under a schema's volume root."""
    volumes = {
        "matchdays": f"{root}/football_data",
        "fixtures": f"{root}/football_data/fixtures",
        "profiles": f"{root}/player_profiles_data",
    }
    # Kept outside the source volumes so no Auto Loader stream reads it.
    return volumes, f"{root}/_checkpoints/s3_volume_sync/copied_etags.json"


VOLUMES, MANIFEST_PATH = volume_paths(VOLUME_ROOT)
SEASON = re.compile(r"season_(\d{4})")


def destination(key, volumes=VOLUMES):
    """Volume path for an S3 key."""
    filename = os.path.basename(key)
    if "/reference/fixtures/" in f"/{key}":
        return f"{volumes['fixtures']}/{filename}"
    season = SEASON.search(key)
    if season:
        return f"{volumes['matchdays']}/{season.group(1)}/{filename}"
    return f"{volumes['profiles']}/{filename}"


def sync_s3_to_volumes(s3, bucket, prefix, volumes=VOLUMES, manifest_path=MANIFEST_PATH):
    """Download objects that are new or changed since the last run.

    Returns the downloaded keys and the number of unchanged files skipped.
    """
    copied = {}
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            copied = json.load(f)

    downloaded, skipped = [], 0
    try:
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith("/"):
                    continue
                target = destination(key, volumes)
                if copied.get(key) == obj["ETag"] and os.path.exists(target):
                    skipped += 1
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                s3.download_file(bucket, key, target)
                copied[key] = obj["ETag"]
                downloaded.append(key)
    finally:
        # Saved even after a failure so completed downloads are not repeated.
        if downloaded:
            os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
            with open(manifest_path, "w") as f:
                json.dump(copied, f, indent=2)
    return downloaded, skipped


if __name__ == "__main__":
    import argparse

    import boto3

    # The job passes --catalog and --schema; the defaults are the production schema.
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default="workspace")
    parser.add_argument("--schema", default="football_data_project")
    args, _ = parser.parse_known_args()
    volume_root = f"/Volumes/{args.catalog}/{args.schema}"
    volumes, manifest_path = volume_paths(volume_root)

    scope_name = "football-project-keys"
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=dbutils.secrets.get(scope=scope_name, key="aws-access-key"),
        aws_secret_access_key=dbutils.secrets.get(scope=scope_name, key="aws-secret-key"),
    )
    bucket_name = "football-data-project-nicknav98"
    s3_prefix = "football-matchday-stats/"

    print(f"Syncing s3://{bucket_name}/{s3_prefix} into {volume_root}...")
    downloaded, skipped = sync_s3_to_volumes(s3_client, bucket_name, s3_prefix, volumes, manifest_path)
    for key in downloaded:
        print(f"  downloaded {key} -> {destination(key, volumes)}")
    print(f"\n{len(downloaded)} files downloaded, {skipped} unchanged files skipped.")
