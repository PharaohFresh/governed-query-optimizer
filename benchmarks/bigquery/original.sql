-- Frozen public cohort. Itemless orders retain a NULL value, rather than disappearing.
SELECT o.id AS order_id, o.user_id AS customer_id,
       SUM(CAST(ROUND(CAST(i.sale_price AS NUMERIC) * 100) AS INT64)) AS revenue_cents
FROM `bigquery-public-data.thelook_ecommerce.orders` FOR SYSTEM_TIME AS OF @snapshot_time AS o
LEFT JOIN `bigquery-public-data.thelook_ecommerce.order_items` FOR SYSTEM_TIME AS OF @snapshot_time AS i
  ON o.id = i.order_id
WHERE DATE(o.created_at) >= DATE '2026-02-01' AND DATE(o.created_at) < DATE '2026-05-01'
GROUP BY o.id, o.user_id
