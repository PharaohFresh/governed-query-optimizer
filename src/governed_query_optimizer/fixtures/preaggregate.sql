WITH item_totals AS (
 SELECT order_id, SUM(quantity * unit_price_cents) AS revenue_cents
 FROM order_items GROUP BY order_id
)
SELECT o.order_date, o.country, COUNT(*) AS order_count,
       SUM(i.revenue_cents) AS revenue_cents
FROM orders o JOIN item_totals i ON i.order_id = o.order_id
GROUP BY o.order_date, o.country;
