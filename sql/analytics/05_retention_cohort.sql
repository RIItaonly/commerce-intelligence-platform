-- analytics 层 · 留存队列（粒度 = 1 行 / cohort_month × period_index）
-- cohort_month = 该真实用户（customer_unique_id）首个有效订单所在月份；
-- period_index = 活跃月份与首购月份相差的月数（MONTH_INDEX 由 sql_engine 适配）。
-- 留存率 = active_customers / 该 cohort 的 period 0 人数，在 Python 层计算。
DROP VIEW IF EXISTS analytics_cohort_retention;
CREATE VIEW analytics_cohort_retention AS
WITH first_order AS (
    SELECT
        customer_unique_id,
        MIN(order_month) AS cohort_month
    FROM fct_order
    WHERE is_valid_order = 1
    GROUP BY customer_unique_id
),
activity AS (
    SELECT DISTINCT
        f.customer_unique_id,
        fo.cohort_month,
        f.order_month
    FROM fct_order f
    JOIN first_order fo ON fo.customer_unique_id = f.customer_unique_id
    WHERE f.is_valid_order = 1
)
SELECT
    cohort_month,
    MONTH_INDEX(order_month) - MONTH_INDEX(cohort_month) AS period_index,
    COUNT(DISTINCT customer_unique_id) AS active_customers
FROM activity
GROUP BY cohort_month, period_index;
