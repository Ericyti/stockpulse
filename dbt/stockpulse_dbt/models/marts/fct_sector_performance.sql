/*
fct_sector_performance.sql
==========================
MART — sector-level daily aggregations.

Aggregates individual stock metrics up to the sector level.
Used for the "Sector Heatmap" and "Sector Comparison" dashboards.

DEMONSTRATES:
    - GROUP BY aggregations
    - Conditional aggregation with CASE/SUM
    - Advance/decline breadth calculation
*/

with daily_trading as (

    select * from {{ ref('fct_daily_trading') }}
    where daily_return is not null

),

sector_agg as (

    select
        sector,
        trade_date,

        -- Return metrics
        round(avg(daily_return)::numeric, 6)   as avg_daily_return,
        round(max(daily_return)::numeric, 6)   as best_return,
        round(min(daily_return)::numeric, 6)   as worst_return,

        -- Volume
        sum(volume)                             as total_volume,
        round(avg(volume)::numeric, 0)          as avg_volume,

        -- Volatility
        round(avg(volatility_20d)::numeric, 6)  as avg_volatility,

        -- Breadth: how many stocks are up vs down
        count(ticker)                           as stock_count,

        sum(case when daily_return > 0 then 1 else 0 end)
            as advancing_stocks,

        sum(case when daily_return < 0 then 1 else 0 end)
            as declining_stocks,

        -- Signal counts
        sum(case when sma_crossover then 1 else 0 end)
            as bullish_crossover_count,

        current_timestamp as dbt_processed_at

    from daily_trading
    group by sector, trade_date

)

select
    *,

    -- Advance/decline ratio: >0.5 means more stocks are up than down
    case
        when stock_count > 0
        then round((advancing_stocks::numeric / stock_count), 4)
        else null
    end as advance_decline_ratio

from sector_agg
