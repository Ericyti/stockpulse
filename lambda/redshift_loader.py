"""
StockPulse — Redshift Loader Lambda
=====================================
Runs SQL commands against Redshift Serverless via the Data API.
Used by Step Functions to load silver data and run transforms.

Supports two actions:
    1. "copy"      — COPY silver Parquet from S3 into raw.stock_prices
    2. "transform" — Run the dbt-equivalent SQL transforms in Redshift
"""

import json
import os
import time

import boto3

redshift_data = boto3.client("redshift-data")

WORKGROUP = os.environ.get("REDSHIFT_WORKGROUP", "stockpulse-workgroup")
DATABASE = os.environ.get("REDSHIFT_DATABASE", "stockpulse")
S3_BUCKET = os.environ.get("S3_BUCKET", "stockpulse-data-773802564138")
REDSHIFT_ROLE_ARN = os.environ.get("REDSHIFT_ROLE_ARN", "")


def run_sql(sql: str, description: str) -> dict:
    """Execute a SQL statement and wait for completion."""
    print(f"  Running: {description}")

    response = redshift_data.execute_statement(
        WorkgroupName=WORKGROUP,
        Database=DATABASE,
        Sql=sql,
    )
    statement_id = response["Id"]

    # Poll until complete
    while True:
        status = redshift_data.describe_statement(Id=statement_id)
        state = status["Status"]

        if state == "FINISHED":
            print(f"  Completed: {description}")
            return {"status": "success", "description": description}
        elif state == "FAILED":
            error = status.get("Error", "Unknown error")
            print(f"  FAILED: {description} — {error}")
            raise Exception(f"SQL failed ({description}): {error}")
        else:
            time.sleep(2)


def handle_copy(event):
    """Truncate and reload raw.stock_prices from S3 silver layer."""
    print("Starting COPY from S3...")

    run_sql(
        'TRUNCATE TABLE "raw".stock_prices;',
        "Truncate raw.stock_prices"
    )

    run_sql(
        f"""COPY "raw".stock_prices
        FROM 's3://{S3_BUCKET}/silver/stocks/'
        IAM_ROLE '{REDSHIFT_ROLE_ARN}'
        FORMAT AS PARQUET;""",
        "COPY silver Parquet into Redshift"
    )

    return {"status": "success", "action": "copy"}


def handle_transform(event):
    """Run SQL transforms equivalent to dbt models."""
    print("Starting SQL transforms...")

    # Recreate seed table
    run_sql("""
        DROP TABLE IF EXISTS analytics.seed_stock_tickers;
        CREATE TABLE analytics.seed_stock_tickers (
            ticker VARCHAR(10),
            company_name VARCHAR(100),
            sector VARCHAR(50),
            market_cap_category VARCHAR(20)
        );
        INSERT INTO analytics.seed_stock_tickers VALUES
        ('AAPL','Apple Inc','Technology','Large Cap'),
        ('MSFT','Microsoft Corporation','Technology','Large Cap'),
        ('GOOGL','Alphabet Inc','Technology','Large Cap'),
        ('JPM','JPMorgan Chase & Co','Financials','Large Cap'),
        ('BAC','Bank of America Corporation','Financials','Large Cap'),
        ('JNJ','Johnson & Johnson','Healthcare','Large Cap'),
        ('UNH','UnitedHealth Group Incorporated','Healthcare','Large Cap'),
        ('XOM','Exxon Mobil Corporation','Energy','Large Cap'),
        ('CVX','Chevron Corporation','Energy','Large Cap'),
        ('PG','Procter & Gamble Company','Consumer Staples','Large Cap');
    """, "Load seed data")

    # dim_stocks
    run_sql("""
        DROP TABLE IF EXISTS analytics.dim_stocks;
        CREATE TABLE analytics.dim_stocks AS
        SELECT ticker, company_name, sector, market_cap_category,
               GETDATE() as dbt_loaded_at
        FROM analytics.seed_stock_tickers;
    """, "Build dim_stocks")

    # stg_stock_prices (view)
    run_sql("""
        CREATE OR REPLACE VIEW analytics.stg_stock_prices AS
        SELECT
            upper(trim(ticker)) as ticker,
            trade_date,
            round(open_price::numeric, 4) as open_price,
            round(high_price::numeric, 4) as high_price,
            round(low_price::numeric, 4) as low_price,
            round(close_price::numeric, 4) as close_price,
            volume,
            round((high_price - low_price)::numeric, 4) as daily_range,
            source as data_source,
            ingested_at,
            processed_at
        FROM "raw".stock_prices
        WHERE trade_date IS NOT NULL
          AND close_price IS NOT NULL
          AND close_price > 0;
    """, "Build stg_stock_prices view")

    # int_stock_indicators
    run_sql("""
        DROP TABLE IF EXISTS analytics.int_stock_indicators;
        CREATE TABLE analytics.int_stock_indicators AS
        WITH with_prev AS (
            SELECT *,
                lag(close_price, 1) OVER (PARTITION BY ticker ORDER BY trade_date) as prev_close
            FROM analytics.stg_stock_prices
        ),
        with_return AS (
            SELECT *,
                CASE WHEN prev_close IS NOT NULL AND prev_close > 0
                     THEN round(((close_price - prev_close) / prev_close)::numeric, 6)
                     ELSE NULL END as daily_return
            FROM with_prev
        )
        SELECT
            ticker, trade_date, open_price, high_price, low_price, close_price,
            volume, daily_range, daily_return,
            round(avg(close_price) OVER (PARTITION BY ticker ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)::numeric, 4) as sma_20,
            round(avg(close_price) OVER (PARTITION BY ticker ORDER BY trade_date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW)::numeric, 4) as sma_50,
            round(stddev(daily_return) OVER (PARTITION BY ticker ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)::numeric, 6) as volatility_20d,
            round(avg(volume) OVER (PARTITION BY ticker ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)::numeric, 0) as volume_sma_20,
            data_source, ingested_at, processed_at,
            GETDATE() as dbt_processed_at
        FROM with_return;
    """, "Build int_stock_indicators")

    # Add computed columns
    run_sql("""
        ALTER TABLE analytics.int_stock_indicators ADD COLUMN sma_crossover BOOLEAN DEFAULT FALSE;
        ALTER TABLE analytics.int_stock_indicators ADD COLUMN relative_volume DOUBLE PRECISION;
        UPDATE analytics.int_stock_indicators SET sma_crossover = (sma_20 > sma_50);
        UPDATE analytics.int_stock_indicators SET relative_volume = CASE WHEN volume_sma_20 > 0 THEN round((volume::numeric / volume_sma_20), 4) ELSE NULL END;
    """, "Add indicator columns")

    # fct_daily_trading
    run_sql("""
        DROP TABLE IF EXISTS analytics.fct_daily_trading;
        CREATE TABLE analytics.fct_daily_trading AS
        SELECT
            i.ticker, s.company_name, s.sector, i.trade_date,
            i.open_price, i.high_price, i.low_price, i.close_price,
            i.volume, i.daily_range, i.daily_return,
            i.sma_20, i.sma_50, i.volatility_20d,
            i.volume_sma_20, i.relative_volume, i.sma_crossover,
            extract(year from i.trade_date) as trade_year,
            extract(month from i.trade_date) as trade_month,
            extract(dow from i.trade_date) as day_of_week,
            i.dbt_processed_at
        FROM analytics.int_stock_indicators i
        LEFT JOIN analytics.dim_stocks s ON i.ticker = s.ticker;
    """, "Build fct_daily_trading")

    # fct_sector_performance
    run_sql("""
        DROP TABLE IF EXISTS analytics.fct_sector_performance;
        CREATE TABLE analytics.fct_sector_performance AS
        SELECT
            sector, trade_date,
            round(avg(daily_return)::numeric, 6) as avg_daily_return,
            round(max(daily_return)::numeric, 6) as best_return,
            round(min(daily_return)::numeric, 6) as worst_return,
            sum(volume) as total_volume,
            round(avg(volume)::numeric, 0) as avg_volume,
            round(avg(volatility_20d)::numeric, 6) as avg_volatility,
            count(ticker) as stock_count,
            sum(CASE WHEN daily_return > 0 THEN 1 ELSE 0 END) as advancing_stocks,
            sum(CASE WHEN daily_return < 0 THEN 1 ELSE 0 END) as declining_stocks,
            sum(CASE WHEN sma_crossover THEN 1 ELSE 0 END) as bullish_crossover_count,
            GETDATE() as dbt_processed_at
        FROM analytics.fct_daily_trading
        WHERE daily_return IS NOT NULL
        GROUP BY sector, trade_date;
    """, "Build fct_sector_performance")

    return {"status": "success", "action": "transform"}


def lambda_handler(event, context):
    """Main entry point. Action is passed by Step Functions."""
    action = event.get("action", "copy")
    print(f"StockPulse Redshift Loader — action: {action}")

    if action == "copy":
        return handle_copy(event)
    elif action == "transform":
        return handle_transform(event)
    else:
        raise ValueError(f"Unknown action: {action}")