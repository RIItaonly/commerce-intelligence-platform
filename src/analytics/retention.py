"""用户生命周期：留存队列、复购、新客 vs 老客。

数据来源：sql/analytics/05_retention_cohort.sql → analytics_cohort_retention，
以及 fct_order 上的用户粒度聚合查询。
"""
from __future__ import annotations

from typing import Dict, Tuple

import pandas as pd

from src import config, sql_engine


def cohort_retention() -> pd.DataFrame:
    """原始队列表：cohort_month × period_index × active_customers。"""
    return sql_engine.read_sql(
        "SELECT * FROM analytics_cohort_retention ORDER BY cohort_month, period_index"
    )


def cohort_matrix(max_period: int = 12, min_cohort_size: int = 50) -> Tuple[pd.DataFrame, pd.Series]:
    """留存率矩阵（cohort_month × period），返回 (矩阵, 各队列首月人数)。"""
    df = cohort_retention()
    sizes = (
        df[df["period_index"] == 0]
        .set_index("cohort_month")["active_customers"]
    )
    sizes = sizes[sizes >= min_cohort_size]
    df = df[df["cohort_month"].isin(sizes.index) & (df["period_index"] <= max_period)]
    matrix = (
        df.pivot(index="cohort_month", columns="period_index", values="active_customers")
        .reindex(index=sizes.index)
    )
    rates = matrix.divide(sizes, axis=0)
    rates.index = [str(m)[:7] for m in rates.index]
    sizes.index = rates.index  # 与矩阵索引保持一致（字符串月份），便于后续按行对齐
    return rates, sizes


def cohort_average_retention(periods=(1, 2, 3, 6)) -> Dict[int, float]:
    """各期数的平均留存率（按队列人数加权），用于报告引用。"""
    rates, sizes = cohort_matrix()
    result: Dict[int, float] = {}
    for period in periods:
        if period not in rates.columns:
            continue
        mask = rates[period].notna()
        if mask.any():
            result[period] = float(
                (rates.loc[mask, period] * sizes[mask]).sum() / sizes[mask].sum()
            )
    return result


def repeat_summary() -> Dict[str, float]:
    """复购概览：单客/多客占比、客均订单数、复购客收入贡献。"""
    row = sql_engine.read_sql(
        """
        WITH agg AS (
            SELECT
                customer_unique_id,
                COUNT(DISTINCT CASE WHEN is_valid_order = 1 THEN order_id END) AS n_orders,
                SUM(CASE WHEN is_valid_order = 1 THEN payment_total ELSE 0 END) AS revenue
            FROM fct_order
            GROUP BY customer_unique_id
        )
        SELECT
            COUNT(*)                                AS customers,
            SUM(CASE WHEN n_orders >= 2 THEN 1 ELSE 0 END) AS repeat_customers,
            AVG(n_orders * 1.0)                     AS avg_orders_per_customer,
            SUM(revenue)                            AS total_revenue,
            SUM(CASE WHEN n_orders >= 2 THEN revenue ELSE 0 END) AS repeat_revenue
        FROM agg
        """
    ).iloc[0]
    result = {k: float(v) for k, v in row.items()}
    result["repeat_customer_share"] = result["repeat_customers"] / result["customers"]
    result["repeat_revenue_share"] = result["repeat_revenue"] / result["total_revenue"]
    return result


def new_vs_returning() -> pd.DataFrame:
    """月度新客 vs 老客（按首个有效订单月份划分），含收入拆分。"""
    start = config.ANALYSIS_START_DATE[:7] + "-01"
    end = config.ANALYSIS_END_DATE[:7] + "-01"
    df = sql_engine.read_sql(
        """
        WITH first_order AS (
            SELECT customer_unique_id, MIN(order_month) AS first_month
            FROM fct_order
            WHERE is_valid_order = 1
            GROUP BY customer_unique_id
        )
        SELECT
            f.order_month,
            COUNT(DISTINCT CASE WHEN fo.first_month = f.order_month THEN f.customer_unique_id END) AS new_customers,
            COUNT(DISTINCT CASE WHEN fo.first_month < f.order_month THEN f.customer_unique_id END)  AS returning_customers,
            SUM(CASE WHEN fo.first_month = f.order_month THEN f.payment_total ELSE 0 END)           AS new_revenue,
            SUM(CASE WHEN fo.first_month < f.order_month THEN f.payment_total ELSE 0 END)           AS returning_revenue
        FROM fct_order f
        JOIN first_order fo ON fo.customer_unique_id = f.customer_unique_id
        WHERE f.is_valid_order = 1
          AND f.order_month BETWEEN ? AND ?
        GROUP BY f.order_month
        ORDER BY f.order_month
        """,
        params=[start, end],
    )
    df["returning_customer_share"] = df["returning_customers"] / (
        df["new_customers"] + df["returning_customers"]
    )
    return df
