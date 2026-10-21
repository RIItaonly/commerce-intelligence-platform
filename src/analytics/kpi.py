"""经营总览指标：月度 KPI、头部品类 / 地区 / 商家。

数据来源：sql/analytics/01_monthly_kpi.sql、02_category_performance.sql、
03_state_performance.sql、04_seller_performance.sql。
"""
from __future__ import annotations

from typing import Dict

import pandas as pd

from src import config, sql_engine


def _month_window() -> tuple:
    """把配置的日期窗换算成 order_month（YYYY-MM-01）的闭区间。"""
    start = config.ANALYSIS_START_DATE[:7] + "-01"
    end = config.ANALYSIS_END_DATE[:7] + "-01"
    return start, end


def monthly_kpi(full_range: bool = False) -> pd.DataFrame:
    """月度经营 KPI。默认按分析时间窗过滤（剔除不完整月份）。"""
    df = sql_engine.read_sql("SELECT * FROM analytics_monthly_kpi ORDER BY order_month")
    if not full_range:
        start, end = _month_window()
        df = df[(df["order_month"] >= start) & (df["order_month"] <= end)].reset_index(drop=True)
    df["revenue_mom"] = df["revenue"].pct_change()
    return df


def headline() -> Dict[str, float]:
    """分析时间窗内的整体指标（直接在 fct_order 上聚合，保证口径精确）。"""
    start, end = _month_window()
    row = sql_engine.read_sql(
        """
        SELECT
            COUNT(*)                                                        AS orders_total,
            SUM(is_valid_order)                                             AS orders_valid,
            SUM(CASE WHEN is_valid_order = 1 THEN payment_total ELSE 0 END) AS revenue,
            SUM(CASE WHEN is_valid_order = 1 THEN product_gmv ELSE 0 END)   AS gmv,
            SUM(CASE WHEN is_valid_order = 1 THEN freight_total ELSE 0 END) AS freight,
            SUM(CASE WHEN is_valid_order = 1 THEN item_count ELSE 0 END)    AS items_sold,
            COUNT(DISTINCT customer_unique_id)                              AS customers,
            SUM(is_delivered)                                               AS orders_delivered,
            SUM(CASE WHEN is_delivered = 1 AND is_late_delivery = 1 THEN 1 ELSE 0 END) AS orders_late,
            AVG(CASE WHEN is_delivered = 1 THEN delivery_days END)          AS avg_delivery_days,
            AVG(review_score)                                               AS avg_review_score,
            SUM(CASE WHEN review_score IS NOT NULL THEN 1 ELSE 0 END)       AS reviews,
            SUM(COALESCE(is_bad_review, 0))                                 AS bad_reviews
        FROM fct_order
        WHERE order_month BETWEEN ? AND ?
        """,
        params=[start, end],
    ).iloc[0]

    result = {k: (float(v) if v is not None else 0.0) for k, v in row.items()}
    result["aov"] = result["revenue"] / result["orders_valid"] if result["orders_valid"] else 0.0
    result["late_delivery_rate"] = (
        result["orders_late"] / result["orders_delivered"] if result["orders_delivered"] else 0.0
    )
    result["bad_review_rate"] = result["bad_reviews"] / result["reviews"] if result["reviews"] else 0.0

    monthly = monthly_kpi()
    if not monthly.empty:
        best = monthly.loc[monthly["revenue"].idxmax()]
        result["best_month"] = str(best["order_month"])[:7]
        result["best_month_revenue"] = float(best["revenue"])
        result["last_month"] = str(monthly["order_month"].iloc[-1])[:7]
        last_mom = monthly["revenue_mom"].iloc[-1]
        result["last_month_mom"] = float(last_mom) if pd.notna(last_mom) else 0.0
        result["avg_monthly_revenue"] = float(monthly["revenue"].mean())
        result["n_months"] = int(len(monthly))
    return result


def top_categories(n: int = 10, by: str = "gmv") -> pd.DataFrame:
    """头部品类（默认按 GMV 排序），附 GMV 占比。"""
    df = sql_engine.read_sql("SELECT * FROM analytics_category_performance")
    total = df["gmv"].sum()
    df["gmv_share"] = df["gmv"] / total
    return df.sort_values(by, ascending=False).head(n).reset_index(drop=True)


def top_states(n: int = 10, by: str = "revenue") -> pd.DataFrame:
    """头部买家州（默认按实收收入排序），附收入占比。"""
    df = sql_engine.read_sql("SELECT * FROM analytics_state_performance")
    total = df["revenue"].sum()
    df["revenue_share"] = df["revenue"] / total
    return df.sort_values(by, ascending=False).head(n).reset_index(drop=True)


def top_sellers(n: int = 10, by: str = "gmv") -> pd.DataFrame:
    """头部商家（默认按 GMV 排序），附 GMV 占比与集中度参考。"""
    df = sql_engine.read_sql("SELECT * FROM analytics_seller_performance")
    total = df["gmv"].sum()
    df["gmv_share"] = df["gmv"] / total
    return df.sort_values(by, ascending=False).head(n).reset_index(drop=True)


def seller_concentration() -> Dict[str, float]:
    """商家集中度：Top 10 / Top 100 商家的 GMV 占比。"""
    df = sql_engine.read_sql("SELECT gmv FROM analytics_seller_performance ORDER BY gmv DESC")
    total = df["gmv"].sum()
    return {
        "n_sellers": int(len(df)),
        "top10_share": float(df["gmv"].head(10).sum() / total),
        "top100_share": float(df["gmv"].head(100).sum() / total),
    }
