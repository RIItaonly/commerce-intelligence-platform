-- marts 层 · 事实表
-- 关键设计：所有事实表都先「预聚合到目标粒度」再 JOIN，避免 Olist 中
-- 「一单多商品 / 多支付 / 多评价」造成的 fan-out 与重复计算。
--   fct_order     粒度 = 1 行 / order_id
--   fct_order_item 粒度 = 1 行 / (order_id, order_item_id)
--   fct_payment   粒度 = 1 行 / (order_id, payment_sequential)

-- ---------------------------------------------------------------- 订单事实表（订单粒度）
DROP VIEW IF EXISTS fct_order;
CREATE VIEW fct_order AS
WITH item_agg AS (
    SELECT
        oi.order_id,
        COUNT(*)                    AS item_count,
        COUNT(DISTINCT oi.product_id) AS product_count,
        COUNT(DISTINCT oi.seller_id)  AS seller_count,
        SUM(oi.price)               AS product_gmv,
        SUM(COALESCE(oi.freight_value, 0)) AS freight_total
    FROM stg_order_items oi
    GROUP BY oi.order_id
),
pay_agg AS (
    SELECT
        p.order_id,
        SUM(p.payment_value)        AS payment_total,
        COUNT(*)                    AS payment_records,
        MAX(p.payment_installments) AS max_installments
    FROM stg_payments p
    GROUP BY p.order_id
)
SELECT
    o.order_id,
    c.customer_unique_id,
    c.customer_state,
    c.customer_city,
    o.order_status,
    o.purchase_ts,
    o.order_date,
    o.order_month,
    o.delivered_ts,
    o.estimated_ts,
    COALESCE(i.item_count, 0)      AS item_count,
    COALESCE(i.product_count, 0)   AS product_count,
    COALESCE(i.seller_count, 0)    AS seller_count,
    COALESCE(i.product_gmv, 0)     AS product_gmv,
    COALESCE(i.freight_total, 0)   AS freight_total,
    COALESCE(p.payment_total, 0)   AS payment_total,
    COALESCE(p.payment_records, 0) AS payment_records,
    p.max_installments,
    r.review_score                 AS review_score,
    r.is_bad_review                AS is_bad_review,
    o.delivery_days,
    o.estimated_days,
    o.delay_days,
    o.is_late_delivery,
    o.is_valid_order,
    o.is_delivered
FROM stg_orders o
JOIN stg_customers c ON c.customer_id = o.customer_id
LEFT JOIN item_agg i ON i.order_id = o.order_id
LEFT JOIN pay_agg  p ON p.order_id = o.order_id
LEFT JOIN stg_reviews r ON r.order_id = o.order_id;

-- ---------------------------------------------------------------- 订单商品事实表（明细粒度）
DROP VIEW IF EXISTS fct_order_item;
CREATE VIEW fct_order_item AS
SELECT
    oi.order_id,
    oi.order_item_id,
    oi.product_id,
    oi.seller_id,
    o.order_status,
    o.order_month,
    o.purchase_ts,
    c.customer_unique_id,
    c.customer_state,
    c.customer_city,
    p.category_name_pt,
    p.category_name_en,
    s.seller_state,
    oi.price,
    COALESCE(oi.freight_value, 0) AS freight_value,
    oi.item_total_value,
    r.review_score,
    r.is_bad_review,
    o.is_valid_order,
    o.is_late_delivery,
    o.is_delivered,
    o.delivery_days
FROM stg_order_items oi
JOIN stg_orders o        ON o.order_id = oi.order_id
JOIN stg_customers c     ON c.customer_id = o.customer_id
LEFT JOIN stg_products p ON p.product_id = oi.product_id
LEFT JOIN stg_sellers  s ON s.seller_id = oi.seller_id
LEFT JOIN stg_reviews  r ON r.order_id = oi.order_id;

-- ---------------------------------------------------------------- 支付事实表（支付明细粒度）
DROP VIEW IF EXISTS fct_payment;
CREATE VIEW fct_payment AS
SELECT
    p.order_id,
    p.payment_sequential,
    p.payment_type,
    p.payment_installments,
    p.payment_value,
    o.order_month,
    o.order_status,
    o.is_valid_order
FROM stg_payments p
JOIN stg_orders o ON o.order_id = p.order_id;
