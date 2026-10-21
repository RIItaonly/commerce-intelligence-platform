-- analytics 层 · 收入（GMV）变动归因
-- 视图 1：月度 × 品类 GMV 及环比变化（LAG 基于「有销售的月份」，稀疏品类需注意；
--         严格的期间对比用 src/analytics/attribution.py 的 compare_periods，按月补零）
-- 视图 2：月度 × 州 GMV 及环比变化
DROP VIEW IF EXISTS analytics_category_gmv_mom;
CREATE VIEW analytics_category_gmv_mom AS
WITH monthly AS (
    SELECT
        order_month,
        category_name_en AS category,
        SUM(price) AS gmv,
        COUNT(DISTINCT order_id) AS orders
    FROM fct_order_item
    WHERE is_valid_order = 1
    GROUP BY order_month, category_name_en
)
SELECT
    order_month,
    category,
    gmv,
    orders,
    LAG(gmv) OVER (PARTITION BY category ORDER BY order_month)           AS prev_gmv,
    gmv - LAG(gmv) OVER (PARTITION BY category ORDER BY order_month)     AS gmv_delta
FROM monthly;

DROP VIEW IF EXISTS analytics_state_gmv_mom;
CREATE VIEW analytics_state_gmv_mom AS
WITH monthly AS (
    SELECT
        order_month,
        customer_state AS state,
        SUM(product_gmv) AS gmv,
        COUNT(*) AS orders
    FROM fct_order
    WHERE is_valid_order = 1
    GROUP BY order_month, customer_state
)
SELECT
    order_month,
    state,
    gmv,
    orders,
    LAG(gmv) OVER (PARTITION BY state ORDER BY order_month)              AS prev_gmv,
    gmv - LAG(gmv) OVER (PARTITION BY state ORDER BY order_month)        AS gmv_delta
FROM monthly;
