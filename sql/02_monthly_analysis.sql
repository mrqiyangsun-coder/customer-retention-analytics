-- Calendar spine prevents absent purchase months from vanishing from comparisons.
WITH RECURSIVE
bounds AS (
    SELECT date(json_extract(value, '$.start')) AS first_date,
           date(json_extract(value, '$.end')) AS last_date
    FROM pipeline_metadata WHERE key = 'source_date_range'
),
calendar(month_start) AS (
    SELECT date(first_date, 'start of month') FROM bounds
    UNION ALL
    SELECT date(month_start, '+1 month') FROM calendar, bounds
    WHERE month_start < date(last_date, 'start of month')
),
base AS (
    SELECT strftime('%Y-%m', m.month_start) AS month,
           COUNT(o.invoice_no) AS orders,
           COALESCE(SUM(o.order_value), 0.0) AS positive_sales_value,
           COUNT(DISTINCT o.customer_id) AS identified_active_customers,
           COUNT(DISTINCT CASE WHEN substr(c.first_observed_order, 1, 7) = strftime('%Y-%m', m.month_start)
                               THEN o.customer_id END) AS first_observed_customers,
           COUNT(DISTINCT CASE WHEN substr(c.first_observed_order, 1, 7) < strftime('%Y-%m', m.month_start)
                               THEN o.customer_id END) AS previously_observed_customers,
           COALESCE(SUM(CASE WHEN substr(c.first_observed_order, 1, 7) = strftime('%Y-%m', m.month_start)
                             THEN o.order_value ELSE 0 END), 0.0) AS first_observed_month_value,
           COALESCE(SUM(CASE WHEN substr(c.first_observed_order, 1, 7) < strftime('%Y-%m', m.month_start)
                             THEN o.order_value ELSE 0 END), 0.0) AS previously_observed_value,
           COALESCE(SUM(CASE WHEN o.customer_id IS NULL THEN o.order_value ELSE 0 END), 0.0) AS anonymous_value,
           CASE WHEN m.month_start >= b.first_date
                     AND date(m.month_start, '+1 month', '-1 day') <= b.last_date
                THEN 1 ELSE 0 END AS is_complete_month
    FROM calendar AS m CROSS JOIN bounds AS b
    LEFT JOIN orders AS o ON substr(o.order_date, 1, 7) = strftime('%Y-%m', m.month_start)
    LEFT JOIN customers AS c ON c.customer_id = o.customer_id
    GROUP BY m.month_start
),
comparisons AS (
    SELECT *, LAG(positive_sales_value) OVER (ORDER BY month) AS previous_month_value,
           LAG(is_complete_month) OVER (ORDER BY month) AS previous_month_complete,
           LAG(positive_sales_value, 12) OVER (ORDER BY month) AS previous_year_value,
           LAG(is_complete_month, 12) OVER (ORDER BY month) AS previous_year_complete
    FROM base
)
SELECT month, orders, positive_sales_value,
       positive_sales_value / NULLIF(orders, 0) AS average_order_value,
       identified_active_customers, first_observed_customers, previously_observed_customers,
       first_observed_month_value, previously_observed_value, anonymous_value, is_complete_month,
       CASE WHEN is_complete_month = 1 AND previous_month_complete = 1 AND previous_month_value > 0
            THEN positive_sales_value / previous_month_value - 1.0 END AS mom_sales_change,
       CASE WHEN is_complete_month = 1 AND previous_year_complete = 1 AND previous_year_value > 0
            THEN positive_sales_value / previous_year_value - 1.0 END AS yoy_sales_change
FROM comparisons ORDER BY month;

