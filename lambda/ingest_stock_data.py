"""
StockPulse — Lambda Ingestion Function
=======================================
This is the FIRST step in the pipeline. It runs as an AWS Lambda function
and pulls daily stock price data from the Alpha Vantage API.

HOW IT WORKS:
    1. EventBridge triggers this function daily at 6:30 PM ET
    2. The function calls Alpha Vantage for each ticker (AAPL, MSFT, etc.)
    3. Raw JSON responses are saved to S3 in the "bronze" layer
    4. Files are partitioned by date: bronze/stocks/year=2025/month=06/day=15/

WHY LAMBDA?
    Lambda is serverless — you don't manage any servers. It runs your code
    when triggered, then shuts down. Perfect for a daily batch job that
    takes a few minutes.

RATE LIMITING:
    Alpha Vantage free tier allows 25 requests/day and 5 requests/minute.
    We wait 15 seconds between calls to stay well within limits.
    With 10 tickers, a full run takes about 2.5 minutes.
"""

import json
import os
import time
from datetime import datetime, timezone

import boto3
import urllib3

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_BASE_URL = "https://www.alphavantage.co/query"

# These are the tickers we track — 10 stocks across 5 sectors
DEFAULT_TICKERS = "AAPL,MSFT,GOOGL,JPM,BAC,JNJ,UNH,XOM,CVX,PG"

# Wait 15 seconds between API calls to respect rate limits
RATE_LIMIT_DELAY = 15

# ---------------------------------------------------------------------------
# AWS Clients (created once, reused across invocations)
# ---------------------------------------------------------------------------
s3_client = boto3.client("s3")
secrets_client = boto3.client("secretsmanager")
http = urllib3.PoolManager()


def get_api_key() -> str:
    """
    Retrieve the Alpha Vantage API key.

    In production, the key lives in AWS Secrets Manager (secure).
    For local testing, you can set the ALPHA_VANTAGE_API_KEY env var.
    """
    # Check environment variable first (useful for local testing)
    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if api_key:
        return api_key

    # In production, retrieve from Secrets Manager
    try:
        response = secrets_client.get_secret_value(
            SecretId="stockpulse/alpha-vantage-api-key"
        )
        secret = json.loads(response["SecretString"])
        return secret["api_key"]
    except Exception as e:
        raise RuntimeError(f"Failed to retrieve API key: {e}")


def fetch_daily_prices(ticker: str, api_key: str) -> dict:
    """
    Call Alpha Vantage API for one ticker's daily price data.

    The API returns a JSON object with this structure:
    {
        "Meta Data": {
            "1. Information": "Daily Prices",
            "2. Symbol": "AAPL",
            ...
        },
        "Time Series (Daily)": {
            "2025-06-15": {
                "1. open": "229.00",
                "2. high": "231.50",
                "3. low": "228.00",
                "4. close": "230.75",
                "5. volume": "45000000"
            },
            "2025-06-14": { ... },
            ...
        }
    }

    "compact" output returns the last 100 trading days (~5 months).
    """
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": ticker,
        "apikey": api_key,
        "outputsize": "compact",
        "datatype": "json",
    }

    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{API_BASE_URL}?{query_string}"

    response = http.request("GET", url)

    if response.status != 200:
        raise Exception(f"HTTP {response.status} for {ticker}")

    data = json.loads(response.data.decode("utf-8"))

    # Alpha Vantage returns error messages in the JSON body
    if "Error Message" in data:
        raise Exception(f"API error for {ticker}: {data['Error Message']}")

    # Rate limit warning — they return a "Note" field when you're too fast
    if "Note" in data:
        raise Exception(f"Rate limited for {ticker}: {data['Note']}")

    return data


def upload_to_s3(data: dict, ticker: str, bucket: str, timestamp: datetime) -> str:
    """
    Save the raw API response to S3 in the bronze layer.

    We wrap the raw data in a metadata envelope so we always know
    where the data came from and when it was ingested.

    S3 KEY FORMAT (Hive-style partitioning):
        bronze/stocks/year=2025/month=06/day=15/AAPL_20250615_180000.json

    WHY PARTITIONING?
        Athena and Glue can skip irrelevant partitions when querying,
        which makes queries faster and cheaper. If you query "WHERE year=2025
        AND month=06", AWS only reads files in that folder — not the entire
        dataset.
    """
    # Build the partition path
    partition_path = (
        f"bronze/stocks/"
        f"year={timestamp.strftime('%Y')}/"
        f"month={timestamp.strftime('%m')}/"
        f"day={timestamp.strftime('%d')}"
    )
    file_name = f"{ticker}_{timestamp.strftime('%Y%m%d_%H%M%S')}.json"
    s3_key = f"{partition_path}/{file_name}"

    # Wrap raw API response with metadata
    envelope = {
        "metadata": {
            "ticker": ticker,
            "source": "alpha_vantage",
            "api_function": "TIME_SERIES_DAILY",
            "ingestion_timestamp": timestamp.isoformat(),
            "pipeline": "stockpulse",
        },
        "raw_data": data,
    }

    s3_client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=json.dumps(envelope, indent=2),
        ContentType="application/json",
    )

    print(f"Uploaded {ticker} -> s3://{bucket}/{s3_key}")
    return s3_key


def lambda_handler(event, context):
    """
    Main Lambda entry point. AWS calls this function automatically.

    PARAMETERS:
        event   — the trigger payload. EventBridge sends {}, but you can
                  also invoke manually with {"tickers": ["AAPL", "MSFT"]}
        context — AWS Lambda context object (runtime info)

    RETURNS:
        A JSON response with success/failure counts.
    """
    print("StockPulse ingestion starting...")

    api_key = get_api_key()
    bucket = os.environ.get("S3_BUCKET", "stockpulse-data")

    # Allow overriding tickers via the event payload (useful for testing)
    if event and "tickers" in event:
        tickers = event["tickers"]
    else:
        tickers = os.environ.get("TICKERS", DEFAULT_TICKERS).split(",")

    tickers = [t.strip().upper() for t in tickers]
    timestamp = datetime.now(timezone.utc)

    print(f"Fetching {len(tickers)} tickers: {tickers}")

    results = {"success": [], "failed": []}

    for i, ticker in enumerate(tickers):
        try:
            print(f"  [{i+1}/{len(tickers)}] Fetching {ticker}...")

            data = fetch_daily_prices(ticker, api_key)
            s3_key = upload_to_s3(data, ticker, bucket, timestamp)

            results["success"].append({"ticker": ticker, "s3_key": s3_key})

        except Exception as e:
            print(f"  FAILED {ticker}: {e}")
            results["failed"].append({"ticker": ticker, "error": str(e)})

        # Rate limiting: wait between calls (skip after the last one)
        if i < len(tickers) - 1:
            print(f"  Waiting {RATE_LIMIT_DELAY}s (rate limit)...")
            time.sleep(RATE_LIMIT_DELAY)

    # Log summary
    print(f"\nCompleted: {len(results['success'])}/{len(tickers)} succeeded")
    if results["failed"]:
        print(f"Failed: {[f['ticker'] for f in results['failed']]}")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Ingestion complete",
            "timestamp": timestamp.isoformat(),
            "results": results,
        }),
    }


# ---------------------------------------------------------------------------
# Local testing
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # To test locally:
    #   export ALPHA_VANTAGE_API_KEY="your_key"
    #   export S3_BUCKET="stockpulse-data-123456789"
    #   python ingest_stock_data.py
    test_event = {"tickers": ["AAPL", "MSFT"]}
    result = lambda_handler(test_event, None)
    print(json.dumps(json.loads(result["body"]), indent=2))
