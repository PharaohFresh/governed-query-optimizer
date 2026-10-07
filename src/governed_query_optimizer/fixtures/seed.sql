-- Invented data. Two identical prices are intentional: DISTINCT loses multiplicity.
CREATE TABLE orders(order_id INTEGER PRIMARY KEY, order_date TEXT NOT NULL, country TEXT NOT NULL);
CREATE TABLE order_items(item_id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL,
                        quantity INTEGER NOT NULL, unit_price_cents INTEGER NOT NULL, promotion TEXT);
INSERT INTO orders VALUES
 (1,'2026-01-03','US'),(2,'2026-09-01','US'),(3,'2026-09-02','CA'),
 (4,'2026-09-02','US'),(5,'2026-09-03','CA'),(6,'2026-09-03','US');
INSERT INTO order_items VALUES
 (1,1,1,2500,NULL),(2,1,1,2500,NULL),(3,2,2,1800,'AUTUMN'),
 (4,3,1,4000,NULL),(5,3,3,1250,'AUTUMN'),(6,4,2,2100,NULL),
 (7,5,1,5500,NULL),(8,5,1,900,'AUTUMN');
