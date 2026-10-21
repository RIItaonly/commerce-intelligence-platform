-- staging 层：类型规范 + 业务清洗 + 派生字段
-- 跨引擎伪函数（由 src/sql_engine.py 适配到 SQLite）：
--   DATE_TRUNC('day'|'month', ts)      天数/月粒度截断
--   DAYS_BETWEEN(later, earlier)       两个时间点相差的天数
--   MONTH_INDEX(ts)                    月份序号（year*12+month），用于计算队列期数
-- 说明：SQLite 不支持 CREATE OR REPLACE VIEW，统一用 DROP VIEW IF EXISTS + CREATE VIEW。

-- ---------------------------------------------------------------- 客户
DROP VIEW IF EXISTS stg_customers;
CREATE VIEW stg_customers AS
SELECT
    c.customer_id,
    c.customer_unique_id,
    c.customer_zip_code_prefix,
    LOWER(TRIM(c.customer_city))  AS customer_city,
    UPPER(TRIM(c.customer_state)) AS customer_state
FROM raw_customers c
WHERE c.customer_id IS NOT NULL
  AND c.customer_unique_id IS NOT NULL;

-- ---------------------------------------------------------------- 订单
DROP VIEW IF EXISTS stg_orders;
CREATE VIEW stg_orders AS
SELECT
    o.order_id,
    o.customer_id,
    o.order_status,
    o.order_purchase_timestamp      AS purchase_ts,
    o.order_approved_at             AS approved_ts,
    o.order_delivered_carrier_date  AS delivered_carrier_ts,
    o.order_delivered_customer_date AS delivered_ts,
    o.order_estimated_delivery_date AS estimated_ts,
    DATE_TRUNC('day',   o.order_purchase_timestamp) AS order_date,
    DATE_TRUNC('month', o.order_purchase_timestamp) AS order_month,
    CASE WHEN o.order_status NOT IN ('canceled', 'unavailable') THEN 1 ELSE 0 END AS is_valid_order,
    CASE WHEN o.order_delivered_customer_date IS NOT NULL THEN 1 ELSE 0 END        AS is_delivered,
    DAYS_BETWEEN(o.order_delivered_customer_date, o.order_purchase_timestamp) AS delivery_days,
    DAYS_BETWEEN(o.order_estimated_delivery_date, o.order_purchase_timestamp) AS estimated_days,
    DAYS_BETWEEN(o.order_delivered_customer_date, o.order_estimated_delivery_date) AS delay_days,
    CASE WHEN o.order_delivered_customer_date IS NOT NULL
              AND o.order_delivered_customer_date > o.order_estimated_delivery_date
         THEN 1 ELSE 0 END AS is_late_delivery
FROM raw_orders o
WHERE o.order_id IS NOT NULL
  AND o.customer_id IS NOT NULL;

-- ---------------------------------------------------------------- 订单商品明细
DROP VIEW IF EXISTS stg_order_items;
CREATE VIEW stg_order_items AS
SELECT
    oi.order_id,
    oi.order_item_id,
    oi.product_id,
    oi.seller_id,
    oi.shipping_limit_date,
    oi.price,
    oi.freight_value,
    (oi.price + COALESCE(oi.freight_value, 0)) AS item_total_value
FROM raw_order_items oi
WHERE oi.order_id IS NOT NULL
  AND oi.price IS NOT NULL;

-- ---------------------------------------------------------------- 支付
DROP VIEW IF EXISTS stg_payments;
CREATE VIEW stg_payments AS
SELECT
    p.order_id,
    p.payment_sequential,
    LOWER(TRIM(p.payment_type)) AS payment_type,
    p.payment_installments,
    p.payment_value
FROM raw_order_payments p
WHERE p.order_id IS NOT NULL
  AND p.payment_value IS NOT NULL;

-- ---------------------------------------------------------------- 评价
-- 个别订单存在多条评价：按「最新回答时间」保留 1 条，保证订单粒度聚合不产生 fan-out
DROP VIEW IF EXISTS stg_reviews;
CREATE VIEW stg_reviews AS
WITH ranked AS (
    SELECT
        r.review_id,
        r.order_id,
        r.review_score,
        r.review_comment_title,
        r.review_comment_message,
        r.review_creation_date    AS review_created_ts,
        r.review_answer_timestamp AS review_answered_ts,
        CASE WHEN r.review_score <= 2 THEN 1 ELSE 0 END AS is_bad_review,
        ROW_NUMBER() OVER (
            PARTITION BY r.order_id
            ORDER BY r.review_answer_timestamp DESC, r.review_id DESC
        ) AS review_rank
    FROM raw_order_reviews r
    WHERE r.order_id IS NOT NULL
)
SELECT review_id, order_id, review_score, review_comment_title, review_comment_message,
       review_created_ts, review_answered_ts, is_bad_review, review_rank
FROM ranked
WHERE review_rank = 1;

-- ---------------------------------------------------------------- 商品
DROP VIEW IF EXISTS stg_products;
CREATE VIEW stg_products AS
SELECT
    p.product_id,
    COALESCE(p.product_category_name, 'unknown') AS category_name_pt,
    COALESCE(t.product_category_name_english, p.product_category_name, 'unknown') AS category_name_en,
    p.product_name_length,
    p.product_description_length,
    p.product_photos_qty,
    p.product_weight_g,
    (p.product_length_cm * p.product_height_cm * p.product_width_cm) AS volume_cm3
FROM raw_products p
LEFT JOIN raw_category_translation t
       ON t.product_category_name = p.product_category_name
WHERE p.product_id IS NOT NULL;

-- ---------------------------------------------------------------- 商家
DROP VIEW IF EXISTS stg_sellers;
CREATE VIEW stg_sellers AS
SELECT
    s.seller_id,
    LOWER(TRIM(s.seller_city))  AS seller_city,
    UPPER(TRIM(s.seller_state)) AS seller_state
FROM raw_sellers s
WHERE s.seller_id IS NOT NULL;
