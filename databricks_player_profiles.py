"""Load player profile fields into a dedicated bronze Delta table."""

from pyspark.sql.types import BooleanType, IntegerType, StringType, StructField, StructType


PROFILE_SCHEMA = StructType([
    StructField("player_id", IntegerType(), False),
    StructField("name", StringType()),
    StructField("firstname", StringType()),
    StructField("lastname", StringType()),
    StructField("age", IntegerType()),
    StructField("birth_date", StringType()),
    StructField("birth_place", StringType()),
    StructField("birth_country", StringType()),
    StructField("nationality", StringType()),
    StructField("height", StringType()),
    StructField("weight", StringType()),
    StructField("injured", BooleanType()),
    StructField("photo", StringType()),
    StructField("source_league_id", IntegerType()),
    StructField("source_season", IntegerType()),
    StructField("fetched_at", StringType()),
])


def write_player_profiles_stream(spark, source_path, schema_location,
                                 checkpoint_path, target_table):
    """Upsert the profile CSV stream by player ID."""
    from delta.tables import DeltaTable

    stream = (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "csv")
        .option("cloudFiles.schemaLocation", schema_location)
        .option("cloudFiles.inferColumnTypes", "true")
        .option("cloudFiles.schemaHints", ", ".join(
            f"{field.name} {field.dataType.simpleString()}" for field in PROFILE_SCHEMA.fields
        ))
        .option("cloudFiles.allowOverwrites", "true")
        .option("header", "true")
        .load(f"{source_path.rstrip('/')}/reference/player_profiles")
    )

    def upsert_batch(batch, batch_id):
        from pyspark.sql.functions import current_timestamp

        batch = batch.dropDuplicates(["player_id"]).withColumn("ingestion_time", current_timestamp())
        if not batch.head(1):
            return
        if not spark.catalog.tableExists(target_table):
            batch.write.format("delta").saveAsTable(target_table)
            return
        (
            DeltaTable.forName(spark, target_table).alias("target")
            .merge(batch.alias("source"), "target.player_id = source.player_id")
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
    query = write_player_profiles_stream(
        spark,
        "/Volumes/workspace/football_data_project/football_data/",
        "/Volumes/workspace/football_data_project/_schemas/player_profiles",
        "/Volumes/workspace/football_data_project/_checkpoints/player_profiles",
        "workspace.football_data_project.bronze_player_profiles",
    )
    query.awaitTermination()
