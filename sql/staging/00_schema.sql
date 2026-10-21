-- 原始层 raw_* 表结构
-- 目标方言：PostgreSQL（SQLite 由 src/sql_engine.py 做少量适配，类型名两边都接受）
-- 原则：raw 层只做「列改名 + 类型规范」，不做业务规则清洗；业务规则统一放在 staging 视图。

-- 订单主表：粒度 1 行 / order_id
CREATE TABLE IF NOT EXISTS raw_orders (
    order_id                        TEXT PRIMARY KEY,
    customer_id                     TEXT,
    order_status                    TEXT,
    order_purchase_timestamp        TIMESTAMP,
    order_approved_at               TIMESTAMP,
    order_delivered_carrier_date    TIMESTAMP,
    order_delivered_customer_date   TIMESTAMP,
    order_estimated_delivery_date   TIMESTAMP
);

-- 订单商品明细：粒度 1 行 / (order_id, order_item_id)
CREATE TABLE IF NOT EXISTS raw_order_items (
    order_id            TEXT,
    order_item_id       INTEGER,
    product_id          TEXT,
    seller_id           TEXT,
    shipping_limit_date TIMESTAMP,
    price               NUMERIC(12, 2),
    freight_value       NUMERIC(12, 2),
    PRIMARY KEY (order_id, order_item_id)
);

-- 支付记录：粒度 1 行 / (order_id, payment_sequential)
CREATE TABLE IF NOT EXISTS raw_order_payments (
    order_id              TEXT,
    payment_sequential    INTEGER,
    payment_type          TEXT,
    payment_installments  INTEGER,
    payment_value         NUMERIC(12, 2),
    PRIMARY KEY (order_id, payment_sequential)
);

-- 评价：粒度 1 行 / review_id（个别订单存在多条评价，见 staging 去重逻辑）
CREATE TABLE IF NOT EXISTS raw_order_reviews (
    review_id               TEXT PRIMARY KEY,
    order_id                TEXT,
    review_score            INTEGER,
    review_comment_title    TEXT,
    review_comment_message  TEXT,
    review_creation_date    TIMESTAMP,
    review_answer_timestamp TIMESTAMP
);

-- 客户：粒度 1 行 / customer_id（注意 customer_id 是订单级标识，跨订单识别同一人要用 customer_unique_id）
CREATE TABLE IF NOT EXISTS raw_customers (
    customer_id                 TEXT PRIMARY KEY,
    customer_unique_id          TEXT,
    customer_zip_code_prefix    INTEGER,
    customer_city               TEXT,
    customer_state              TEXT
);

-- 商品：粒度 1 行 / product_id
CREATE TABLE IF NOT EXISTS raw_products (
    product_id                  TEXT PRIMARY KEY,
    product_category_name       TEXT,
    product_name_length         INTEGER,
    product_description_length  INTEGER,
    product_photos_qty          INTEGER,
    product_weight_g            INTEGER,
    product_length_cm           INTEGER,
    product_height_cm           INTEGER,
    product_width_cm            INTEGER
);

-- 商家：粒度 1 行 / seller_id
CREATE TABLE IF NOT EXISTS raw_sellers (
    seller_id               TEXT PRIMARY KEY,
    seller_zip_code_prefix  INTEGER,
    seller_city             TEXT,
    seller_state            TEXT
);

-- 地理：粒度 1 行 / (zip_code_prefix, lat, lng)，存在大量重复邮编，默认不导入
CREATE TABLE IF NOT EXISTS raw_geolocation (
    geolocation_zip_code_prefix INTEGER,
    geolocation_lat             REAL,
    geolocation_lng             REAL,
    geolocation_city            TEXT,
    geolocation_state           TEXT
);

-- 品类名翻译：粒度 1 行 / product_category_name
CREATE TABLE IF NOT EXISTS raw_category_translation (
    product_category_name           TEXT PRIMARY KEY,
    product_category_name_english   TEXT
);

-- 索引：覆盖所有下游 JOIN / GROUP BY 用到的键
CREATE INDEX IF NOT EXISTS idx_orders_customer ON raw_orders (customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_purchase ON raw_orders (order_purchase_timestamp);
CREATE INDEX IF NOT EXISTS idx_orders_status ON raw_orders (order_status);
CREATE INDEX IF NOT EXISTS idx_items_order ON raw_order_items (order_id);
CREATE INDEX IF NOT EXISTS idx_items_product ON raw_order_items (product_id);
CREATE INDEX IF NOT EXISTS idx_items_seller ON raw_order_items (seller_id);
CREATE INDEX IF NOT EXISTS idx_payments_order ON raw_order_payments (order_id);
CREATE INDEX IF NOT EXISTS idx_reviews_order ON raw_order_reviews (order_id);
CREATE INDEX IF NOT EXISTS idx_customers_unique ON raw_customers (customer_unique_id);
