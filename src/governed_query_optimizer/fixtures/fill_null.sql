SELECT item_id, COALESCE(promotion, 'UNKNOWN') AS promotion FROM order_items;
