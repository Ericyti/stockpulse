"""
StockPulse — Glue PySpark Job: Bronze -> Silver (Fixed)
========================================================
Reads raw JSON from bronze, cleans it, writes Parquet to silver.

FIX: Alpha Vantage JSON has dynamic date keys in "Time Series (Daily)".
Spark infers these as a struct (one field per date) instead of a map.
Solution: Read JSON as raw text, parse with Python's json module,
and build rows manually.
"""

import json
import sys
from datetime import datetime

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql import Row
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
)

# ---------------------------------------------------------------------------
# Glue Job Setup
# ---------------------------------------------------------------------------
args = getResolvedOptions(sys.argv, [
    "JOB_NAME",
    "S3_BUCKET",
    "PROCESSING_DATE",
])

sc = SparkContext()
glue_context = GlueContext(sc)
spark = glue_context.spark_session
job = Job(glue_context)
job.init(args["JOB_NAME"], args)

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
# Define the output schema
# ---------------------------------------------------------------------------
silver_schema = StructType([
    StructField("ticker", StringType(), False),
    StructField("trade_date", StringType(), False),
    StructField("open_price", DoubleType(), True),
    StructField("high_price", DoubleType(), True),
    StructField("low_price", DoubleType(), True),
    StructField("close_price", DoubleType(), True),
    StructField("volume", LongType(), True),
    StructField("source", StringType(), True),
    StructField("ingested_at", StringType(), True),
    StructField("processed_at", StringType(), True),
])

# ---------------------------------------------------------------------------
# Read JSON as raw text and parse manually
# ---------------------------------------------------------------------------
print("Reading bronze layer as raw text...")

raw_text_df = spark.read.text(BRONZE_PATH, wholetext=True)
print(f"Found {raw_text_df.count()} raw files")

raw_texts = raw_text_df.collect()

all_rows = []
parse_errors = 0

for text_row in raw_texts:
    try:
        data = json.loads(text_row["value"])

        metadata = data.get("metadata", {})
        ticker = metadata.get("ticker", "UNKNOWN")
        source = metadata.get("source", "alpha_vantage")
        ingestion_timestamp = metadata.get("ingestion_timestamp", "")

        raw_data = data.get("raw_data", {})
        time_series = raw_data.get("Time Series (Daily)", {})

        if not time_series:
            print(f"  Warning: No time series data for {ticker}")
            continue

        for date_str, ohlcv in time_series.items():
            try:
                row = Row(
                    ticker=ticker.upper().strip(),
                    trade_date=date_str,
                    open_price=float(ohlcv.get("1. open", 0)),
                    high_price=float(ohlcv.get("2. high", 0)),
                    low_price=float(ohlcv.get("3. low", 0)),
                    close_price=float(ohlcv.get("4. close", 0)),
                    volume=int(ohlcv.get("5. volume", 0)),
                    source=source,
                    ingested_at=ingestion_timestamp,
                    processed_at=datetime.utcnow().isoformat(),
                )
                all_rows.append(row)
            except (ValueError, TypeError):
                parse_errors += 1
                continue

    except json.JSONDecodeError as e:
        parse_errors += 1
        print(f"  Error parsing JSON: {e}")
        continue

print(f"Parsed {len(all_rows)} rows ({parse_errors} errors)")

# ---------------------------------------------------------------------------
# Create DataFrame and apply quality checks
# ---------------------------------------------------------------------------
if len(all_rows) == 0:
    print("No rows parsed - exiting")
    job.commit()
    sys.exit(0)

silver_df = spark.createDataFrame(all_rows, schema=silver_schema)

silver_df = silver_df.withColumn(
    "trade_date", F.to_date(F.col("trade_date"), "yyyy-MM-dd")
)
silver_df = silver_df.withColumn(
    "ingested_at", F.to_timestamp(F.col("ingested_at"))
)
silver_df = silver_df.withColumn(
    "processed_at", F.to_timestamp(F.col("processed_at"))
)

initial_count = silver_df.count()

silver_df = silver_df.filter(
    (F.col("trade_date").isNotNull())
    & (F.col("close_price").isNotNull())
    & (F.col("close_price") > 0)
    & (F.col("open_price") > 0)
    & (F.col("high_price") > 0)
    & (F.col("low_price") > 0)
    & (F.col("volume") >= 0)
)

silver_df = silver_df.dropDuplicates(["ticker", "trade_date"])

final_count = silver_df.count()
print(f"Quality check: {initial_count} -> {final_count} ({initial_count - final_count} dropped)")

print("\nSample silver records:")
silver_df.show(5, truncate=False)

# ---------------------------------------------------------------------------
# Write to silver layer as Parquet
# ---------------------------------------------------------------------------
print(f"Writing {final_count} rows to {SILVER_PATH}...")

silver_df.write \
    .mode("overwrite") \
    .parquet(SILVER_PATH)

print(f"Bronze -> Silver complete for {PROCESSING_DATE}")

job.commit()