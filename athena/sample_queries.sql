-- ============================================================================
-- StockPulse — Athena Sample Queries
-- ============================================================================
-- Athena lets you run SQL directly on S3 files WITHOUT loading into Redshift.
-- You pay $5 per TB scanned — with our small dataset, each query costs <$0.01.
--
-- WHY USE ATHENA WHEN WE HAVE REDSHIFT?
--   1. Cost: Athena is cheaper for infrequent, ad-hoc exploration
--   2. Speed: No need to wait for COPY into Redshift
--   3. Access: Query any S3 layer (bronze, silver) — not just loaded data
--   4. Sharing: Anyone with AWS access can query without Redshift credentials
--
-- PREREQUISITES:
--   1. Glue Data Catalog must have the tables registered (Terraform does this)
--   2. Go to AWS Console -> Athena -> Query Editor
--   3. Set your results bucket: s3://stockpulse-data-ACCOUNT_ID/athena-results/
-- ============================================================================


-- ============================================================================
-- Create external table pointing to silver Parquet files
-- ============================================================================
-- This tells Athena "there are Parquet files at this S3 path, here's the schema."
-- The Glue Crawler can also do this automatically, but manual is more explicit.

CREATE EXTERNAL TABLE IF NOT EXISTS stockpulse_catalog.silver_stock_prices (
    trade_date      DATE,
    open_price      DOUBLE,
    high_price      DOUBLE,
    low_price       DOUBLE,
    close_price     DOUBLE,
    volume          BIGINT,
    source          STRING,
    ingested_at     TIMESTAMP,
    processed_at    TIMESTAMP
)
PARTITIONED BY (ticker STRING)
STORED AS PARQUET
LOCATION 's3://stockpulse-data-YOUR_ACCOUNT_ID/silver/stocks/'
TBLPROPERTIES ('classification' = 'parquet');

-- After creating the table, load partitions:
MSCK REPAIR TABLE stockpulse_catalog.silver_stock_prices;


-- ============================================================================
-- Query 1: Latest prices for all stocks
-- ============================================================================
-- Simple query to verify data is loading correctly.

SELECT
    ticker,
    trade_date,
    open_price,
    close_price,
    volume
FROM stockpulse_catalog.silver_stock_prices
WHERE trade_date = (
    SELECT MAX(trade_date)
    FROM stockpulse_catalog.silver_stock_prices
)
ORDER BY ticker;


-- ============================================================================
-- Query 2: Top movers today (biggest daily price change)
-- ============================================================================
-- Find which stocks moved the most on the latest trading day.

WITH latest_prices AS (
    SELECT
        ticker,
        trade_date,
        close_price,
        LAG(close_price) OVER (PARTITION BY ticker ORDER BY trade_date) AS prev_close
    FROM stockpulse_catalog.silver_stock_prices
)
SELECT
    ticker,
    trade_date,
    close_price,
    prev_close,
    ROUND((close_price - prev_close) / prev_close * 100, 2) AS pct_change
FROM latest_prices
WHERE trade_date = (SELECT MAX(trade_date) FROM latest_prices)
  AND prev_close IS NOT NULL
ORDER BY ABS((close_price - prev_close) / prev_close) DESC;


-- ============================================================================
-- Query 3: 20-day price history for a specific stock
-- ============================================================================
-- Useful for quick spot-checks when building dashboards.

SELECT
    ticker,
    trade_date,
    open_price,
    high_price,
    low_price,
    close_price,
    volume
FROM stockpulse_catalog.silver_stock_prices
WHERE ticker = 'AAPL'
ORDER BY trade_date DESC
LIMIT 20;


-- ============================================================================
-- Query 4: Volume spike detection
-- ============================================================================
-- Finds days where volume was more than 2x the 20-day average.
-- High relative volume often indicates significant news or events.

WITH volume_analysis AS (
    SELECT
        ticker,
        trade_date,
        volume,
        AVG(volume) OVER (
            PARTITION BY ticker
            ORDER BY trade_date
            ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS avg_volume_20d
    FROM stockpulse_catalog.silver_stock_prices
)
SELECT
    ticker,
    trade_date,
    volume,
    CAST(avg_volume_20d AS BIGINT) AS avg_volume_20d,
    ROUND(CAST(volume AS DOUBLE) / avg_volume_20d, 2) AS relative_volume
FROM volume_analysis
WHERE avg_volume_20d > 0
  AND CAST(volume AS DOUBLE) / avg_volume_20d > 2.0
ORDER BY trade_date DESC, relative_volume DESC;


-- ============================================================================
-- Query 5: Monthly average close by stock
-- ============================================================================
-- Good for trend analysis over longer periods.

SELECT
    ticker,
    DATE_TRUNC('month', trade_date) AS month,
    ROUND(AVG(close_price), 2) AS avg_close,
    ROUND(AVG(volume), 0) AS avg_volume,
    COUNT(*) AS trading_days
FROM stockpulse_catalog.silver_stock_prices
GROUP BY ticker, DATE_TRUNC('month', trade_date)
ORDER BY ticker, month DESC;
