-- marts 层 · 维度表
-- 依赖 02_facts.sql（dim_customer 建立在 fct_order 之上），因此文件名顺序即依赖顺序。
--   dim_customer 粒度 = 1 行 / customer_unique_id（真实用户，而非订单级 customer_id）
--   dim_product  粒度 = 1 行 / product_id
--   dim_seller   粒度 = 1 行 / seller_id

DROP VIEW IF EXISTS dim_customer;
CREATE VIEW dim_customer AS
SELECT
    f.customer_unique_id,
    MIN(f.customer_state) AS customer_state,
    MIN(f.customer_city)  AS customer_city,
    MIN(f.purchase_ts)    AS first_order_ts,
    MAX(f.purchase_ts)    AS last_order_ts,
    COUNT(DISTINCT f.order_id) AS n_orders,
    SUM(CASE WHEN f.is_valid_order = 1 THEN f.payment_total ELSE 0 END) AS lifetime_revenue,
    SUM(CASE WHEN f.is_valid_order = 1 AND f.product_gmv > 0 THEN 1 ELSE 0 END) AS n_paid_orders
FROM fct_order f
GROUP BY f.customer_unique_id;

DROP VIEW IF EXISTS dim_product;
CREATE VIEW dim_product AS
SELECT
    p.product_id,
    p.category_name_pt,
    p.category_name_en,
    p.product_photos_qty,
    p.product_weight_g,
    p.volume_cm3
FROM stg_products p;

DROP VIEW IF EXISTS dim_seller;
CREATE VIEW dim_seller AS
SELECT
    s.seller_id,
    s.seller_city,
    s.seller_state
FROM stg_sellers s;
