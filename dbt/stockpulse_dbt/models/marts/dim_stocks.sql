/*
dim_stocks.sql
==============
DIMENSION TABLE — static reference data about each stock.

This table enriches fact tables with descriptive attributes
(company name, sector) that don't change day to day.

Built from the seed CSV file (seeds/seed_stock_tickers.csv).
Seeds are small reference datasets checked into version control.

DIMENSION TABLE DESIGN:
    - One row per entity (one row per stock)
    - Contains descriptive attributes, not measures
    - Slowly changing — only updates when we add/remove tickers
*/

with seed_data as (

    select * from {{ ref('seed_stock_tickers') }}

),

final as (

    select
        ticker,
        company_name,
        sector,
        market_cap_category,
        current_timestamp as dbt_loaded_at

    from seed_data

)

select * from final
