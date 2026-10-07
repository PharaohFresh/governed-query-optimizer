-- The same order-date cohort and frozen source. No filter on item creation time.
WITH items AS (
  SELECT order_id,
         SUM(CAST(ROUND(CAST(sale_price AS NUMERIC) * 100) AS INT64)) AS revenue_cents
  FROM `bigquery-public-data.thelook_ecommerce.order_items` FOR SYSTEM_TIME AS OF @snapshot_time
  GROUP BY order_id
)
SELECT o.order_id AS order_id, o.user_id AS customer_id, i.revenue_cents
FROM `bigquery-public-data.thelook_ecommerce.orders` AS o FOR SYSTEM_TIME AS OF @snapshot_time
LEFT JOIN items AS i ON o.order_id = i.order_id
WHERE DATE(o.created_at) >= DATE '2026-02-01' AND DATE(o.created_at) < DATE '2026-05-01'
