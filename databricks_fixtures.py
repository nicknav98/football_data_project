"""Load fixture context (kickoff, teams, score) into a dedicated bronze Delta table."""

from pyspark.sql.types import IntegerType, StringType, StructField, StructType


FIXTURE_SCHEMA = StructType([
    StructField("league_id", IntegerType(), False),
    StructField("season", IntegerType(), False),
    StructField("round", StringType()),
    StructField("fixture_id", IntegerType(), False),
    StructField("kickoff_utc", StringType()),
    StructField("status", StringType()),
    StructField("referee", StringType()),
    StructField("venue_id", IntegerType()),
    StructField("venue_name", StringType()),
    StructField("venue_city", StringType()),
    StructField("home_team_id", IntegerType()),
    StructField("home_team_name", StringType()),
    StructField("away_team_id", IntegerType()),
    StructField("away_team_name", StringType()),
    StructField("home_goals", IntegerType()),
    StructField("away_goals", IntegerType()),
    StructField("halftime_home_goals", IntegerType()),
    StructField("halftime_away_goals", IntegerType()),
])

MERGE_KEYS = ("league_id", "season", "fixture_id")


def write_fixtures_stream(spark, source_path, schema_location,
                          checkpoint_path, target_table):
    """Upsert the fixture CSV stream by league, season, and fixture ID."""
    from delta.tables import DeltaTable

    stream = (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "csv")
        .option("cloudFiles.schemaLocation", schema_location)
        .option("cloudFiles.inferColumnTypes", "true")
        .option("cloudFiles.schemaHints", ", ".join(
            f"{field.name} {field.dataType.simpleString()}" for field in FIXTURE_SCHEMA.fields
        ))
        # sync_matchday_stats.py rewrites a league-season file whenever a
        # fixture is played, rescheduled, or corrected.
        .option("cloudFiles.allowOverwrites", "true")
        .option("header", "true")
        .load(source_path.rstrip('/'))
    )

    def upsert_batch(batch, batch_id):
        from pyspark.sql.functions import current_timestamp

        batch = batch.dropDuplicates(list(MERGE_KEYS)).withColumn("ingestion_time", current_timestamp())
        if not batch.head(1):
            return
        if not spark.catalog.tableExists(target_table):
            batch.write.format("delta").saveAsTable(target_table)
            return
        (
            DeltaTable.forName(spark, target_table).alias("target")
            .merge(batch.alias("source"),
                   " AND ".join(f"target.{key} = source.{key}" for key in MERGE_KEYS))
            .whenMatchedUpdateAll()
            .whenNotMatchedInsertAll()
            .execute()
        )

    return (
        stream.writeStream.foreachBatch(upsert_batch)
        .option("checkpointLocation", checkpoint_path)
        .trigger(availableNow=True)
        .start()
    )


if __name__ == "__main__":
    query = write_fixtures_stream(
        spark,
        "/Volumes/workspace/football_data_project/fixtures_data",
        "/Volumes/workspace/football_data_project/_schemas/fixtures",
        "/Volumes/workspace/football_data_project/_checkpoints/fixtures",
        "workspace.football_data_project.bronze_fixtures",
    )
    query.awaitTermination()
