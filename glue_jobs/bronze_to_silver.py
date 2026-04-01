"""
StockPulse — Glue PySpark Job: Bronze -> Silver
================================================
This is the batch ETL step. It reads raw JSON from the bronze layer,
cleans and normalizes the data, and writes Parquet to the silver layer.

WHY PYSPARK FOR THIS STEP?
    The Alpha Vantage JSON is deeply nested and has string-typed numbers.
    PySpark is excellent for:
    - Flattening nested JSON (explode, struct access)
    - Type-casting strings to floats/dates at scale
    - Writing partitioned Parquet files efficiently
    SQL would be painful for this — try writing a SQL query to flatten
    a JSON map with dynamic keys. PySpark makes it straightforward.

WHY NOT DBT FOR THIS STEP?
    dbt operates on data already in a warehouse (Redshift). This step
    processes files on S3 — there's no SQL engine involved yet.

INPUT:
    s3://bucket/bronze/stocks/year=YYYY/month=MM/day=DD/*.json

OUTPUT:
    s3://bucket/silver/stocks/ticker=AAPL/*.parquet
    s3://bucket/silver/stocks/ticker=MSFT/*.parquet
    ...

SCHEDULING:
    Triggered by Airflow after Lambda ingestion completes.
    Runs as a Glue job with 2 DPUs (the minimum — keeps costs low).
"""

import sys
from datetime import datetime

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, LongType

# ---------------------------------------------------------------------------
# Glue Job Boilerplate
# ---------------------------------------------------------------------------
# Every Glue job needs this setup. getResolvedOptions reads command-line
# arguments that Airflow passes when triggering the job.

args = getResolvedOptions(sys.argv, [
    "JOB_NAME",
    "S3_BUCKET",
    "PROCESSING_DATE",  # Format: YYYY-MM-DD
])

sc = SparkContext()
glue_context = GlueContext(sc)
spark = glue_context.spark_session
job = Job(glue_context)
job.init(args["JOB_NAME"], args)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
S3_BUCKET = args["S3_BUCKET"]
PROCESSING_DATE = args["PROCESSING_DATE"]

proc_date = datetime.strptime(PROCESSING_DATE, "%Y-%m-%d")
BRONZE_PATH = (
    f"s3://{S3_BUCKET}/bronze/stocks/"
    f"year={proc_date.strftime('%Y')}/"
    f"month={proc_date.strftime('%m')}/"
    f"day={proc_date.strftime('%d')}/"
)
SILVER_PATH = f"s3://{S3_BUCKET}/silver/stocks/"

print(f"Reading from:  {BRONZE_PATH}")
print(f"Writing to:    {SILVER_PATH}")


# ---------------------------------------------------------------------------
# Step 1: Read raw JSON
# ---------------------------------------------------------------------------
def read_bronze_data(path: str) -> DataFrame:
    """Read all JSON files from today's bronze partition."""
    print("Reading bronze layer...")

    # multiline=true because each file is a single JSON object, not JSONL
    raw_df = spark.read.option("multiline", "true").json(path)

    print("Bronze schema:")
    raw_df.printSchema()
    print(f"Found {raw_df.count()} raw files")

    return raw_df


# ---------------------------------------------------------------------------
# Step 2: Flatten and transform
# ---------------------------------------------------------------------------
def transform_to_silver(raw_df: DataFrame) -> DataFrame:
    """
    Flatten the nested Alpha Vantage JSON into a clean tabular format.

    THE KEY PYSPARK CONCEPT HERE: explode()
    ----------------------------------------
    The "Time Series (Daily)" field is a MAP — each key is a date string,
    each value is a struct with OHLCV prices. We use explode() to turn
    each key-value pair into its own row:

    BEFORE explode:
        ticker  |  time_series
        AAPL    |  {"2025-06-15": {...}, "2025-06-14": {...}, ...}

    AFTER explode:
        ticker  |  trade_date_str  |  daily_data
        AAPL    |  2025-06-15      |  {open: "229", high: "231", ...}
        AAPL    |  2025-06-14      |  {open: "228", high: "230", ...}

    Then we extract each field from the struct and cast types.
    """
    print("Transforming bronze -> silver...")

    # Step 2a: Pull out the ticker from metadata and the time series data
    df_with_ticker = raw_df.select(
        F.col("metadata.ticker").alias("ticker"),
        F.col("metadata.ingestion_timestamp").alias("ingestion_timestamp"),
        F.col("metadata.source").alias("source"),
        F.col("raw_data.`Time Series (Daily)`").alias("time_series"),
    )

    # Step 2b: Explode the map into rows
    # Each (date_string, ohlcv_struct) pair becomes its own row
    exploded_df = df_with_ticker.select(
        "ticker",
        "ingestion_timestamp",
        "source",
        F.explode(F.col("time_series")).alias("trade_date_str", "daily_data"),
    )

    # Step 2c: Extract and cast fields
    # Alpha Vantage returns everything as strings ("229.00"), so we cast
    # to proper numeric types for downstream analytics
    silver_df = exploded_df.select(
        F.col("ticker"),
        F.to_date(F.col("trade_date_str"), "yyyy-MM-dd").alias("trade_date"),
        F.col("daily_data.`1. open`").cast(DoubleType()).alias("open_price"),
        F.col("daily_data.`2. high`").cast(DoubleType()).alias("high_price"),
        F.col("daily_data.`3. low`").cast(DoubleType()).alias("low_price"),
        F.col("daily_data.`4. close`").cast(DoubleType()).alias("close_price"),
        F.col("daily_data.`5. volume`").cast(LongType()).alias("volume"),
        F.col("source"),
        F.to_timestamp(F.col("ingestion_timestamp")).alias("ingested_at"),
        F.current_timestamp().alias("processed_at"),
    )

    return silver_df


# ---------------------------------------------------------------------------
# Step 3: Data quality checks
# ---------------------------------------------------------------------------
def apply_quality_checks(df: DataFrame) -> DataFrame:
    """
    Remove bad data before writing to silver.

    Quality rules:
    - No null trade dates or closing prices (critical fields)
    - No negative or zero prices (data corruption indicator)
    - Deduplicate: if the same ticker+date appears twice, keep one
    """
    print("Running quality checks...")

    initial_count = df.count()

    # Remove nulls in critical columns
    cleaned_df = df.filter(
        F.col("trade_date").isNotNull()
        & F.col("close_price").isNotNull()
        & F.col("ticker").isNotNull()
    )

    # Remove impossible values
    cleaned_df = cleaned_df.filter(
        (F.col("open_price") > 0)
        & (F.col("high_price") > 0)
        & (F.col("low_price") > 0)
        & (F.col("close_price") > 0)
        & (F.col("volume") >= 0)
    )

    # Deduplicate on (ticker, trade_date)
    cleaned_df = cleaned_df.dropDuplicates(["ticker", "trade_date"])

    final_count = cleaned_df.count()
    print(f"Quality check: {initial_count} -> {final_count} ({initial_count - final_count} dropped)")

    return cleaned_df


# ---------------------------------------------------------------------------
# Step 4: Write to silver layer as Parquet
# ---------------------------------------------------------------------------
def write_silver_data(df: DataFrame, path: str):
    """
    Write cleaned data to silver layer.

    WHY PARQUET?
        Parquet is a columnar storage format. Benefits:
        - 10-50x smaller than JSON (columnar compression)
        - Schema embedded in the file (self-describing)
        - Athena, Glue, and Redshift read it natively
        - Column pruning: queries that only need 'close_price' skip
          all other columns entirely

    WHY PARTITION BY TICKER?
        When you query "WHERE ticker = 'AAPL'", Spark/Athena only reads
        files in the ticker=AAPL/ folder. With 10 tickers, that means
        reading 1/10th of the data.
    """
    print(f"Writing silver data to {path}...")

    df.write \
        .mode("append") \
        .partitionBy("ticker") \
        .parquet(path)

    print("Silver layer write complete")


# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------
try:
    raw_df = read_bronze_data(BRONZE_PATH)
    silver_df = transform_to_silver(raw_df)
    clean_df = apply_quality_checks(silver_df)

    # Show a sample for verification in CloudWatch logs
    print("\nSample silver records:")
    clean_df.show(5, truncate=False)

    write_silver_data(clean_df, SILVER_PATH)
    print(f"\nBronze -> Silver complete for {PROCESSING_DATE}")

except Exception as e:
    print(f"Job failed: {e}")
    raise

finally:
    job.commit()
