-- Run against data/processed/retail.sqlite. Counts are lines unless labeled orders.
SELECT 'retained_lines' AS metric, COUNT(*) AS value FROM transactions
UNION ALL
SELECT 'export_copies_excluded', COUNT(*) FROM export_exclusions
UNION ALL
SELECT 'qualifying_orders', COUNT(*) FROM orders
UNION ALL
SELECT 'identified_customer_orders', COUNT(*) FROM customer_orders
UNION ALL
SELECT 'observed_customers', COUNT(*) FROM customers;

-- These two values must match within GBP 0.01 aggregation tolerance.
SELECT (SELECT SUM(line_value) FROM purchase_lines) AS purchase_line_value,
       (SELECT SUM(order_value) FROM orders) AS order_value;

SELECT line_type, COUNT(*) AS lines FROM transactions GROUP BY line_type;
SELECT month, orders, positive_sales_value, is_complete_month FROM monthly_sales ORDER BY month;
