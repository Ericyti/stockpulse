/*
fct_daily_trading.sql
=====================
MART (FACT TABLE) — the final analytics-ready table.

This is what Power BI connects to. It joins stock indicators with
the dimension table (dim_stocks) to add sector and company name,
making it ready for dashboards without additional joins.

FACT TABLE DESIGN:
    - One row per ticker per trading day
    - Contains all measures: prices, returns, indicators, signals
    - Joined with dim_stocks for sector/company context
    - This is a "wide" fact table — common in analytics engineering
*/

with indicators as (

    select * from {{ ref('int_stock_indicators') }}

),

stocks as (

    select * from {{ ref('dim_stocks') }}

),

final as (

    select
        -- Dimensions (for grouping and filtering)
        i.ticker,
        s.company_name,
        s.sector,
        i.trade_date,

        -- Measures: Price data
        i.open_price,
        i.high_price,
        i.low_price,
        i.close_price,
        i.volume,
        i.daily_range,

        -- Measures: Computed indicators
        i.daily_return,
        i.sma_20,
        i.sma_50,
        i.volatility_20d,
        i.volume_sma_20,
        i.relative_volume,

        -- Signals
        i.sma_crossover,

        -- Useful for time-based filtering in dashboards
        extract(year from i.trade_date)  as trade_year,
        extract(month from i.trade_date) as trade_month,
        extract(dow from i.trade_date)   as day_of_week,

        -- Metadata
        i.dbt_processed_at

    from indicators i
    left join stocks s
        on i.ticker = s.ticker

)

select * from final
