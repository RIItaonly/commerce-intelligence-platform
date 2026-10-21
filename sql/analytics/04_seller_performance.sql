-- analytics 层 · 商家表现（粒度 = 1 行 / seller_id；基于商品明细，仅有效订单）
DROP VIEW IF EXISTS analytics_seller_performance;
CREATE VIEW analytics_seller_performance AS
SELECT
    seller_id,
    MIN(seller_state)                                               AS seller_state,
    COUNT(DISTINCT order_id)                                        AS orders,
    COUNT(*)                                                        AS items_sold,
    COUNT(DISTINCT product_id)                                      AS products,
    COUNT(DISTINCT category_name_en)                                AS categories,
    COUNT(DISTINCT order_month)                                     AS active_months,
    SUM(price)                                                      AS gmv,
    SUM(item_total_value)                                           AS gmv_with_freight,
    AVG(CASE WHEN is_delivered = 1 THEN delivery_days END)          AS avg_delivery_days,
    SUM(CASE WHEN is_delivered = 1 AND is_late_delivery = 1 THEN 1 ELSE 0 END) * 1.0
        / NULLIF(SUM(is_delivered), 0)                              AS late_delivery_rate,
    AVG(review_score)                                               AS avg_review_score
FROM fct_order_item
WHERE is_valid_order = 1
GROUP BY seller_id;
