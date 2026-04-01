/*
stg_stock_prices.sql
====================
STAGING MODEL — the first dbt transformation layer.

PURPOSE:
    Staging models are a 1:1 mirror of the source table with:
    - Consistent column naming conventions
    - Basic type casting
    - Light cleaning (trim, lowercase)

    They do NOT contain business logic — that goes in intermediate/marts.

WHY A SEPARATE STAGING LAYER?
    If the source schema ever changes (Alpha Vantage renames a field,
    or we switch to a different API), we only update THIS file.
    All downstream models reference stg_stock_prices, not the raw table.
    This is a dbt best practice called "source abstraction."

MATERIALIZED AS: view (defined in dbt_project.yml)
    Views are free — they don't store data, just a SQL query definition.
    Every time a downstream model queries this, it runs the SQL live.
*/

with source as (

    select * from {{ source('raw_stockpulse', 'stock_prices') }}

),

renamed as (

    select
        -- Identifiers
        upper(trim(ticker))                     as ticker,
        trade_date,

        -- Price data (OHLCV)
        round(open_price::numeric, 4)           as open_price,
        round(high_price::numeric, 4)           as high_price,
        round(low_price::numeric, 4)            as low_price,
        round(close_price::numeric, 4)          as close_price,
        volume,

        -- Derived: daily price range
        round((high_price - low_price)::numeric, 4)  as daily_range,

        -- Metadata
        source                                  as data_source,
        ingested_at,
        processed_at

    from source

    -- Safety: only include valid rows
    where trade_date is not null
      and close_price is not null
      and close_price > 0

)

select * from renamed
