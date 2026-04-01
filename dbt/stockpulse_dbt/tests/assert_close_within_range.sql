/*
assert_close_within_range.sql
==============================
CUSTOM DATA QUALITY TEST

Checks that no stock has a daily return greater than ±50%.
A move of more than 50% in a single day is extremely rare and
almost certainly indicates bad data.

HOW dbt TESTS WORK:
    - This SQL query should return ZERO rows if the test passes
    - Any rows returned = test failure
    - dbt runs all tests with 'dbt test'
*/

select
    ticker,
    trade_date,
    daily_return
from {{ ref('fct_daily_trading') }}
where daily_return is not null
  and abs(daily_return) > 0.50
