-- analytics 层 · 品类表现（粒度 = 1 行 / 品类；基于商品明细，仅有效订单）
-- 迟到率按「已签收明细行」加权，解释时需注意：同一订单多商品会被多次计数。
DROP VIEW IF EXISTS analytics_category_performance;
CREATE VIEW analytics_category_performance AS
SELECT
    category_name_en                                                AS category,
    COUNT(DISTINCT order_id)                                        AS orders,
    COUNT(*)                                                        AS items_sold,
    COUNT(DISTINCT product_id)                                      AS products,
    COUNT(DISTINCT seller_id)                                       AS sellers,
    SUM(price)                                                      AS gmv,
    SUM(item_total_value)                                           AS gmv_with_freight,
    AVG(price)                                                      AS avg_price,
    AVG(freight_value)                                              AS avg_freight,
    AVG(CASE WHEN is_delivered = 1 THEN delivery_days END)          AS avg_delivery_days,
    SUM(CASE WHEN is_delivered = 1 AND is_late_delivery = 1 THEN 1 ELSE 0 END) * 1.0
        / NULLIF(SUM(is_delivered), 0)                              AS late_delivery_rate,
    AVG(review_score)                                               AS avg_review_score
FROM fct_order_item
WHERE is_valid_order = 1
GROUP BY category_name_en;
