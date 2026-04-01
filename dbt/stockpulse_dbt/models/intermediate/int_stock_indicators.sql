/*
int_stock_indicators.sql
========================
INTERMEDIATE MODEL — computes technical indicators per stock.

THIS IS THE CORE SQL THAT DEMONSTRATES YOUR SKILLS:
    - Window functions (LAG, AVG OVER, STDDEV OVER)
    - Rolling calculations with ROWS BETWEEN
    - CASE expressions for trading signals
    - CTEs for clean, readable transformations

WHAT IT COMPUTES:
    1. Daily return: percentage change from previous close
    2. SMA 20: 20-day Simple Moving Average (short-term trend)
    3. SMA 50: 50-day Simple Moving Average (long-term trend)
    4. Volatility: 20-day rolling standard deviation of returns
    5. SMA crossover: bullish signal when SMA20 > SMA50
    6. Relative volume: today's volume vs 20-day average

WHY WINDOW FUNCTIONS?
    Window functions let you compute across rows WITHOUT collapsing
    them with GROUP BY. LAG() looks at the previous row. AVG() OVER
    computes a running average. This is the bread and butter of
    financial analytics SQL.
*/

with stock_prices as (

    select * from {{ ref('stg_stock_prices') }}

),

-- Step 1: Add previous day's close price using LAG()
with_previous_close as (

    select
        *,
        lag(close_price, 1) over (
            partition by ticker
            order by trade_date
        ) as prev_close_price

    from stock_prices

),

-- Step 2: Compute daily return
with_daily_return as (

    select
        *,
        case
            when prev_close_price is not null and prev_close_price > 0
            then round(
                ((close_price - prev_close_price) / prev_close_price)::numeric,
                6
            )
            else null
        end as daily_return

    from with_previous_close

),

-- Step 3: Add moving averages and volatility
with_indicators as (

    select
        -- Core fields
        ticker,
        trade_date,
        open_price,
        high_price,
        low_price,
        close_price,
        volume,
        daily_range,

        -- Daily return
        daily_return,

        -- 20-day Simple Moving Average
        round(
            avg(close_price) over (
                partition by ticker
                order by trade_date
                rows between 19 preceding and current row
            )::numeric,
            4
        ) as sma_20,

        -- 50-day Simple Moving Average
        round(
            avg(close_price) over (
                partition by ticker
                order by trade_date
                rows between 49 preceding and current row
            )::numeric,
            4
        ) as sma_50,

        -- 20-day rolling volatility (std dev of daily returns)
        round(
            stddev(daily_return) over (
                partition by ticker
                order by trade_date
                rows between 19 preceding and current row
            )::numeric,
            6
        ) as volatility_20d,

        -- 20-day average volume
        round(
            avg(volume) over (
                partition by ticker
                order by trade_date
                rows between 19 preceding and current row
            )::numeric,
            0
        ) as volume_sma_20,

        -- Metadata
        data_source,
        ingested_at,
        processed_at

    from with_daily_return

)

select
    *,

    -- SMA crossover signal: bullish when short-term > long-term
    case
        when sma_20 > sma_50 then true
        else false
    end as sma_crossover,

    -- Relative volume: how today's volume compares to recent average
    case
        when volume_sma_20 > 0
        then round((volume::numeric / volume_sma_20), 4)
        else null
    end as relative_volume,

    -- Timestamp when this model was built
    current_timestamp as dbt_processed_at

from with_indicators
