-- analytics 层 · 地区（买家州）表现（粒度 = 1 行 / customer_state；仅有效订单）
DROP VIEW IF EXISTS analytics_state_performance;
CREATE VIEW analytics_state_performance AS
SELECT
    customer_state                                                  AS state,
    COUNT(*)                                                        AS orders,
    COUNT(DISTINCT customer_unique_id)                              AS customers,
    SUM(product_gmv)                                                AS gmv,
    SUM(payment_total)                                              AS revenue,
    AVG(payment_total)                                              AS aov,
    AVG(freight_total)                                              AS avg_freight,
    AVG(CASE WHEN is_delivered = 1 THEN delivery_days END)          AS avg_delivery_days,
    SUM(CASE WHEN is_delivered = 1 AND is_late_delivery = 1 THEN 1 ELSE 0 END) * 1.0
        / NULLIF(SUM(is_delivered), 0)                              AS late_delivery_rate,
    AVG(review_score)                                               AS avg_review_score
FROM fct_order
WHERE is_valid_order = 1
GROUP BY customer_state;
