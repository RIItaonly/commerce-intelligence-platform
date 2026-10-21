-- analytics 层 · 订单履约漏斗（单行汇总，Python 层转置成长表画图）
-- 说明：Olist 只有订单状态时间戳，没有曝光/点击/加购日志，漏斗只能从「下单」开始；
--       各阶段按时间戳是否存在判定，已取消订单也可能到达过某些阶段，解释时注意。
DROP VIEW IF EXISTS analytics_order_funnel;
CREATE VIEW analytics_order_funnel AS
WITH pay AS (
    SELECT DISTINCT order_id FROM stg_payments
)
SELECT
    COUNT(*)                                                            AS orders_total,
    SUM(CASE WHEN o.approved_ts IS NOT NULL THEN 1 ELSE 0 END)          AS orders_approved,
    SUM(CASE WHEN p.order_id IS NOT NULL THEN 1 ELSE 0 END)             AS orders_paid,
    SUM(CASE WHEN o.delivered_carrier_ts IS NOT NULL THEN 1 ELSE 0 END) AS orders_shipped,
    SUM(CASE WHEN o.delivered_ts IS NOT NULL THEN 1 ELSE 0 END)         AS orders_delivered,
    SUM(CASE WHEN r.order_id IS NOT NULL THEN 1 ELSE 0 END)             AS orders_reviewed,
    SUM(CASE WHEN o.order_status = 'canceled' THEN 1 ELSE 0 END)        AS orders_canceled,
    SUM(CASE WHEN o.order_status = 'unavailable' THEN 1 ELSE 0 END)     AS orders_unavailable
FROM stg_orders o
LEFT JOIN pay p        ON p.order_id = o.order_id
LEFT JOIN stg_reviews r ON r.order_id = o.order_id;
