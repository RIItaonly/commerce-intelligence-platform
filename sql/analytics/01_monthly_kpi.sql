-- analytics 层 · 月度经营 KPI（粒度 = 1 行 / order_month）
-- 口径：GMV = 商品金额合计（不含运费）；实收收入 = 支付金额合计（含运费）；仅统计有效订单。
-- 注意：2016-09/10/12 与 2018-09 之后为不完整月份，趋势分析请在 Python 层按
--       config.ANALYSIS_START_DATE / ANALYSIS_END_DATE 过滤（单一事实来源在配置里）。
DROP VIEW IF EXISTS analytics_monthly_kpi;
CREATE VIEW analytics_monthly_kpi AS
SELECT
    order_month,
    COUNT(*)                                                          AS orders_total,
    SUM(is_valid_order)                                               AS orders_valid,
    SUM(is_delivered)                                                 AS orders_delivered,
    SUM(CASE WHEN order_status = 'canceled' THEN 1 ELSE 0 END)        AS orders_canceled,
    SUM(CASE WHEN order_status = 'unavailable' THEN 1 ELSE 0 END)     AS orders_unavailable,
    SUM(CASE WHEN is_valid_order = 1 THEN product_gmv ELSE 0 END)     AS gmv,
    SUM(CASE WHEN is_valid_order = 1 THEN payment_total ELSE 0 END)   AS revenue,
    SUM(CASE WHEN is_valid_order = 1 THEN freight_total ELSE 0 END)   AS freight,
    SUM(CASE WHEN is_valid_order = 1 THEN item_count ELSE 0 END)      AS items_sold,
    SUM(CASE WHEN is_valid_order = 1 THEN payment_total ELSE 0 END)
        / NULLIF(SUM(is_valid_order), 0)                              AS aov,
    AVG(CASE WHEN is_delivered = 1 THEN delivery_days END)            AS avg_delivery_days,
    SUM(CASE WHEN is_delivered = 1 AND is_late_delivery = 1 THEN 1 ELSE 0 END) AS orders_late,
    SUM(CASE WHEN is_delivered = 1 AND is_late_delivery = 1 THEN 1 ELSE 0 END) * 1.0
        / NULLIF(SUM(is_delivered), 0)                                AS late_delivery_rate,
    AVG(review_score)                                                 AS avg_review_score,
    SUM(COALESCE(is_bad_review, 0))                                   AS bad_reviews
FROM fct_order
GROUP BY order_month;
