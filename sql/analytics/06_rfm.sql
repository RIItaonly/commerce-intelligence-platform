-- analytics 层 · RFM（粒度 = 1 行 / customer_unique_id）
-- recency_days = 距数据集中最后一笔订单日的天数；frequency = 有效订单数；monetary = 实收金额合计。
-- 注意：Olist 约 97% 用户只有 1 单，f_score 的 NTILE(5) 会退化（大量并列），
--       业务分群规则在 Python 层（src/analytics/rfm.py）完成，不直接依赖 f_score。
DROP VIEW IF EXISTS analytics_rfm;
CREATE VIEW analytics_rfm AS
WITH ref AS (
    SELECT MAX(purchase_ts) AS ref_ts FROM fct_order
),
agg AS (
    SELECT
        customer_unique_id,
        MIN(purchase_ts) AS first_purchase_ts,
        MAX(purchase_ts) AS last_purchase_ts,
        COUNT(DISTINCT CASE WHEN is_valid_order = 1 THEN order_id END) AS frequency,
        SUM(CASE WHEN is_valid_order = 1 THEN payment_total ELSE 0 END) AS monetary
    FROM fct_order
    GROUP BY customer_unique_id
),
rfm AS (
    SELECT
        a.customer_unique_id,
        a.first_purchase_ts,
        a.last_purchase_ts,
        DAYS_BETWEEN(ref.ref_ts, a.last_purchase_ts) AS recency_days,
        a.frequency,
        a.monetary
    FROM agg a
    CROSS JOIN ref
)
SELECT
    customer_unique_id,
    first_purchase_ts,
    last_purchase_ts,
    recency_days,
    frequency,
    monetary,
    NTILE(5) OVER (ORDER BY recency_days DESC) AS r_score,
    NTILE(5) OVER (ORDER BY frequency)         AS f_score,
    NTILE(5) OVER (ORDER BY monetary)          AS m_score
FROM rfm;
