SELECT o.order_date, o.country, COUNT(DISTINCT o.order_id) AS order_count,
       SUM(i.quantity * i.unit_price_cents) AS revenue_cents
FROM orders o JOIN order_items i ON i.order_id = o.order_id
WHERE o.order_date >= '2026-09-01'
GROUP BY o.order_date, o.country;
