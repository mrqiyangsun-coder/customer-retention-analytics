CREATE UNIQUE INDEX transactions_source_key ON transactions(source_sheet, source_row);
CREATE INDEX transactions_invoice ON transactions(invoice_no);
CREATE UNIQUE INDEX orders_invoice ON orders(invoice_no);
CREATE INDEX orders_customer_date ON orders(customer_id, order_date);
CREATE UNIQUE INDEX customers_id ON customers(customer_id);

CREATE VIEW purchase_lines AS
SELECT * FROM transactions WHERE line_type = 'purchase';

CREATE VIEW customer_orders AS
SELECT * FROM orders WHERE customer_id IS NOT NULL AND customer_id_conflict = 0;

