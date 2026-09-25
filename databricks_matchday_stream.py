"""
Databricks Auto Loader (cloudFiles) ingestion for the matchday player-stats
CSVs produced by sync_matchday_stats.py (one file per matchday, uploaded to an S3 bucket that's
mounted/synced into a Databricks Volume, e.g.
/Volumes/workspace/football_data_project/football_data/).

Schema below matches the actual CSV columns/types as written by pandas'
DataFrame.to_csv (see output/league_*/season_*/*_MATCHDAY_*.csv): any stat
column that can be missing for a player comes out as a float column
("1.0", "" for null) because of how pandas upcasts int64 -> float64 in the
presence of NaN, even though the values are conceptually whole numbers.
Columns that are always present stay as plain ints/bools.

cloudFiles.inferColumnTypes is left on (schema inference ON) so any new
column api-football adds later is picked up automatically. SCHEMA acts as
schemaHints so the columns we already know about are typed exactly as
above instead of being (re-)guessed from the first batch of files.
"""
from pyspark.sql.types import (
    BooleanType,
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

SCHEMA = StructType(
    [
        StructField("league_id", IntegerType(), nullable=False),
        StructField("season", IntegerType(), nullable=False),
        StructField("round", StringType(), nullable=False),
        StructField("fixture_id", IntegerType(), nullable=False),
        StructField("team_id", IntegerType(), nullable=False),
        StructField("team_name", StringType(), nullable=False),
        StructField("player_id", IntegerType(), nullable=False),
        StructField("player_name", StringType(), nullable=False),
        StructField("offsides", DoubleType(), nullable=True),
        StructField("games_minutes", DoubleType(), nullable=True),
        StructField("games_number", IntegerType(), nullable=True),
        StructField("games_position", StringType(), nullable=True),
        StructField("games_rating", DoubleType(), nullable=True),
        StructField("games_captain", BooleanType(), nullable=True),
        StructField("games_substitute", BooleanType(), nullable=True),
        StructField("shots_total", DoubleType(), nullable=True),
        StructField("shots_on", DoubleType(), nullable=True),
        StructField("goals_total", DoubleType(), nullable=True),
        StructField("goals_conceded", DoubleType(), nullable=True),
        StructField("goals_assists", DoubleType(), nullable=True),
        StructField("goals_saves", DoubleType(), nullable=True),
        StructField("passes_total", DoubleType(), nullable=True),
        StructField("passes_key", DoubleType(), nullable=True),
        StructField("passes_accuracy", IntegerType(), nullable=True),
        StructField("tackles_total", DoubleType(), nullable=True),
        StructField("tackles_blocks", DoubleType(), nullable=True),
        StructField("tackles_interceptions", DoubleType(), nullable=True),
        StructField("duels_total", DoubleType(), nullable=True),
        StructField("duels_won", DoubleType(), nullable=True),
        StructField("dribbles_attempts", DoubleType(), nullable=True),
        StructField("dribbles_success", DoubleType(), nullable=True),
        StructField("dribbles_past", DoubleType(), nullable=True),
        StructField("fouls_drawn", DoubleType(), nullable=True),
        StructField("fouls_committed", DoubleType(), nullable=True),
        StructField("cards_yellow", IntegerType(), nullable=True),
        StructField("cards_red", IntegerType(), nullable=True),
        StructField("penalty_won", DoubleType(), nullable=True),
        StructField("penalty_commited", DoubleType(), nullable=True),
        StructField("penalty_scored", IntegerType(), nullable=True),
        StructField("penalty_missed", DoubleType(), nullable=True),
        StructField("penalty_saved", DoubleType(), nullable=True),
    ]
)


def read_matchday_stream(spark, source_path, schema_location):
    """Auto Loader stream over the matchday CSVs.

    source_path:     e.g. "/Volumes/main/football/raw" (wherever
                      the S3-synced CSVs land in Databricks).
    schema_location:  e.g. "/Volumes/main/football/_schemas/matchday_stats" -
                      Auto Loader persists/evolves the inferred schema here
                      across stream restarts; give each source its own path.
    """
    stream = (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "csv")
        .option("cloudFiles.schemaLocation", schema_location)
        .option("cloudFiles.inferColumnTypes", "true")
        .option("cloudFiles.schemaHints", SCHEMA.simpleString())
        .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
        # sync_matchday_stats.py re-uploads a matchday's CSV to the same
        # S3 key when api-football corrects stats within STABILITY_WINDOW.
        # Without this, Auto Loader ignores a file it has already seen even
        # if its content changed, and the correction would never arrive.
        .option("cloudFiles.allowOverwrites", "true")
        .option("header", "true")
        .load(source_path)
    )
    # The existing source may still hold legacy or per-fixture CSVs. Only
    # ingest files from the current league/season/matchday layout.
    return stream.filter(
        stream["_metadata.file_path"].rlike(
            r"/league_\d+/season_\d+/[A-Z]{3}_[A-Z0-9_]+_MATCHDAY_\d+\.csv$"
        )
    )


# A row is uniquely identified by league, season, fixture, team, and player.
MERGE_KEYS = ("league_id", "season", "fixture_id", "team_id", "player_id")


def write_bronze_stream(spark, source_path, schema_location, checkpoint_path, target_table):
    """Stream matchday CSVs straight into a bronze Delta table, merging each
    micro-batch on MERGE_KEYS so a corrected/re-uploaded matchday file
    updates existing rows instead of duplicating them.

    checkpoint_path: e.g. "/Volumes/workspace/football_data_project/_checkpoints/bronze_matchday_stats" -
                     tracks which files/offsets this stream has already
                     processed; give this stream its own path.
    target_table:    e.g. "workspace.football_data_project.bronze_matchday_stats"

    Uses trigger(availableNow=True): processes everything currently sitting
    in source_path then stops, matching the existing "run sync_matchday_stats.py
    on a schedule" pattern rather than running as an always-on stream.
    """
    from delta.tables import DeltaTable

    def upsert_batch(micro_batch_df, batch_id):
        if not spark.catalog.tableExists(target_table):
            micro_batch_df.write.format("delta").saveAsTable(target_table)
            return

        target = DeltaTable.forName(spark, target_table)
        condition = " AND ".join(f"target.{k} = source.{k}" for k in MERGE_KEYS)
        (
            target.alias("target")
            .merge(micro_batch_df.alias("source"), condition)
            .whenMatchedUpdateAll()
            .whenNotMatchedInsertAll()
            .execute()
        )

    stream_df = read_matchday_stream(spark, source_path, schema_location)
    return (
        stream_df.writeStream.foreachBatch(upsert_batch)
        .option("checkpointLocation", checkpoint_path)
        .trigger(availableNow=True)
        .start()
    )


if __name__ == "__main__":
    # Paste-into-a-Databricks-notebook usage, mirroring the original
    # read-CSV-then-overwrite-table cell this replaces.
    source_path = "/Volumes/workspace/football_data_project/football_data/"
    target_table = "workspace.football_data_project.bronze_matchday_stats"
    schema_location = "/Volumes/workspace/football_data_project/_schemas/bronze_matchday_stats"
    checkpoint_path = "/Volumes/workspace/football_data_project/_checkpoints/bronze_matchday_stats"

    query = write_bronze_stream(spark, source_path, schema_location, checkpoint_path, target_table)
    query.awaitTermination()

    count = spark.table(target_table).count()
    print(f"✓ Successfully streamed into {target_table} ({count} rows total)")
