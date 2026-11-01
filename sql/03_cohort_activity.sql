-- Distinct monthly purchasers; two orders by the same customer count once.
WITH sizes AS (
    SELECT substr(first_observed_order, 1, 7) AS cohort_month, COUNT(*) AS cohort_size
    FROM customers GROUP BY cohort_month
), activity AS (
    SELECT substr(c.first_observed_order, 1, 7) AS cohort_month,
           substr(o.order_date, 1, 7) AS activity_month,
           COUNT(DISTINCT o.customer_id) AS active_customers
    FROM customer_orders AS o JOIN customers AS c ON c.customer_id = o.customer_id
    GROUP BY cohort_month, activity_month
)
SELECT a.cohort_month, a.activity_month, a.active_customers, s.cohort_size
FROM activity AS a JOIN sizes AS s ON s.cohort_month = a.cohort_month
ORDER BY a.cohort_month, a.activity_month;

