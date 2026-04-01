/*
calculate_sma.sql
=================
CUSTOM MACRO — generates a Simple Moving Average window function.

WHAT ARE dbt MACROS?
    Macros are reusable SQL snippets. Instead of copy-pasting the same
    window function everywhere, you call {{ calculate_sma(...) }} and
    dbt generates the SQL for you.

USAGE:
    {{ calculate_sma('close_price', 'ticker', 'trade_date', 20) }}

    Generates:
    ROUND(AVG(close_price) OVER (
        PARTITION BY ticker ORDER BY trade_date
        ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
    )::numeric, 4)
*/

{% macro calculate_sma(column, partition_col, order_col, window_size) %}
    round(
        avg({{ column }}) over (
            partition by {{ partition_col }}
            order by {{ order_col }}
            rows between {{ window_size - 1 }} preceding and current row
        )::numeric,
        4
    )
{% endmacro %}
