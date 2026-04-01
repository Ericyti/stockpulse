-- ============================================================================
-- StockPulse — Redshift Initial Setup
-- ============================================================================
-- Run this ONCE when setting up your Redshift Serverless instance.
-- It creates the schemas and the raw landing table.
--
-- HOW TO RUN:
--   1. Go to AWS Console -> Redshift -> Query Editor v2
--   2. Connect to your stockpulse workgroup
--   3. Copy and paste this entire file
--   4. Click "Run"
-- ============================================================================

-- Schema for raw data (loaded from S3 via COPY)
CREATE SCHEMA IF NOT EXISTS raw;

-- Schema for dbt-managed analytics tables
-- (dbt creates tables here automatically when you run 'dbt run')
CREATE SCHEMA IF NOT EXISTS analytics;


-- ============================================================================
-- Raw landing table for silver layer data
-- ============================================================================
-- This table receives data from the S3 silver layer via COPY command.
-- dbt reads from this table as a "source" and builds models on top of it.
--
-- REDSHIFT-SPECIFIC OPTIMIZATIONS:
--
-- DISTSTYLE KEY / DISTKEY (ticker):
--   Redshift distributes rows across nodes. With DISTKEY on ticker,
--   all rows for the same stock land on the same node. This means
--   queries like "WHERE ticker = 'AAPL'" hit one node instead of all.
--
-- COMPOUND SORTKEY (ticker, trade_date):
--   Redshift stores data on disk in this order. Queries that filter
--   by ticker first, then scan a date range, can skip huge chunks
--   of data (zone-map pruning). This is the most common query pattern.
--
-- ENCODE (compression):
--   Each column uses the best compression algorithm for its data type.
--   - delta: great for dates (each value = small offset from previous)
--   - az64: Redshift's proprietary algo, great for numbers
--   - lzo: good general-purpose for strings

CREATE TABLE IF NOT EXISTS raw.stock_prices (
    ticker          VARCHAR(10)     NOT NULL ENCODE lzo,
    trade_date      DATE            NOT NULL ENCODE delta,
    open_price      DECIMAL(12,4)   ENCODE az64,
    high_price      DECIMAL(12,4)   ENCODE az64,
    low_price       DECIMAL(12,4)   ENCODE az64,
    close_price     DECIMAL(12,4)   ENCODE az64,
    volume          BIGINT          ENCODE az64,
    source          VARCHAR(50)     ENCODE lzo,
    ingested_at     TIMESTAMP       ENCODE az64,
    processed_at    TIMESTAMP       ENCODE az64,

    PRIMARY KEY (ticker, trade_date)
)
DISTSTYLE KEY
DISTKEY (ticker)
COMPOUND SORTKEY (ticker, trade_date);


-- ============================================================================
-- Grant permissions to dbt user (if using a separate dbt role)
-- ============================================================================
-- Uncomment and modify if you create a dedicated dbt user:
--
-- CREATE USER dbt_user PASSWORD 'change_me';
-- GRANT USAGE ON SCHEMA raw TO dbt_user;
-- GRANT SELECT ON ALL TABLES IN SCHEMA raw TO dbt_user;
-- GRANT ALL ON SCHEMA analytics TO dbt_user;
