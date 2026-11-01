-- Denominator is identified-customer positive value, over observed histories.
WITH ranked AS (
    SELECT customer_id, positive_order_value AS customer_value,
           ROW_NUMBER() OVER (ORDER BY positive_order_value DESC, customer_id) AS customer_rank,
           COUNT(*) OVER () AS total_customers,
           SUM(positive_order_value) OVER () AS identified_value,
           SUM(positive_order_value) OVER (
               ORDER BY positive_order_value DESC, customer_id
               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
           ) AS cumulative_value
    FROM customers
)
SELECT customer_id, customer_value, customer_rank, total_customers,
       1.0 * customer_rank / NULLIF(total_customers, 0) AS customer_share,
       cumulative_value / NULLIF(identified_value, 0) AS cumulative_value_share
FROM ranked ORDER BY customer_rank;

