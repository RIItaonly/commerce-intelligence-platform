"""收入（GMV）变动归因：把两个期间的 GMV 差额分解到品类 / 地区。

数据来源：sql/analytics/08_revenue_attribution.sql（环比视图，用于看连续月份）；
compare_periods 用「按月补零」的严格期间对比（品类某月无销售时按 0 处理），
避免环比视图中 LAG 跨过空月份造成的口径问题。
"""
from __future__ import annotations

from typing import Dict

import pandas as pd

from src import config, sql_engine


def category_mom() -> pd.DataFrame:
    """月度 × 品类 GMV 环比（LAG 基于有销售的月份，稀疏品类注意口径）。"""
    return sql_engine.read_sql("SELECT * FROM analytics_category_gmv_mom")


def state_mom() -> pd.DataFrame:
    """月度 × 州 GMV 环比。"""
    return sql_engine.read_sql("SELECT * FROM analytics_state_gmv_mom")


def compare_periods(
    current_start: str,
    current_end: str,
    previous_start: str,
    previous_end: str,
    dim: str = "category",
) -> pd.DataFrame:
    """对比两个期间（月份闭区间，格式 YYYY-MM-01）的 GMV，按品类或州分解差额。

    返回列：key / prev_gmv / cur_gmv / delta / contribution_share（delta 占总差额的比例）。
    """
    if dim == "category":
        sql = (
            "SELECT category_name_en AS key, SUM(price) AS gmv "
            "FROM fct_order_item WHERE is_valid_order = 1 AND order_month BETWEEN ? AND ? "
            "GROUP BY category_name_en"
        )
    else:
        sql = (
            "SELECT customer_state AS key, SUM(product_gmv) AS gmv "
            "FROM fct_order WHERE is_valid_order = 1 AND order_month BETWEEN ? AND ? "
            "GROUP BY customer_state"
        )
    cur = sql_engine.read_sql(sql, params=[current_start, current_end]).rename(columns={"gmv": "cur_gmv"})
    prev = sql_engine.read_sql(sql, params=[previous_start, previous_end]).rename(columns={"gmv": "prev_gmv"})

    merged = pd.merge(cur, prev, on="key", how="outer").fillna(0.0)
    merged["delta"] = merged["cur_gmv"] - merged["prev_gmv"]
    total_delta = merged["delta"].sum()
    merged["contribution_share"] = merged["delta"] / total_delta if total_delta else 0.0
    return merged.sort_values("delta", ascending=False).reset_index(drop=True)


def peak_month_analysis() -> Dict[str, object]:
    """峰值月归因：找分析窗内 GMV 最高月，对比其上一月，给出品类/州贡献 Top 名单。"""
    from src.analytics import kpi

    monthly = kpi.monthly_kpi()
    idx = monthly["gmv"].idxmax()
    peak_month = monthly.loc[idx, "order_month"]
    peak_pos = monthly.index.get_loc(idx)
    if peak_pos == 0:
        raise ValueError("峰值月是窗口第一个月，无法做环比")
    prev_month = monthly["order_month"].iloc[peak_pos - 1]

    return {
        "peak_month": str(peak_month)[:7],
        "prev_month": str(prev_month)[:7],
        "peak_gmv": float(monthly.loc[idx, "gmv"]),
        "prev_gmv": float(monthly["gmv"].iloc[peak_pos - 1]),
        "by_category": compare_periods(peak_month, peak_month, prev_month, prev_month, dim="category"),
        "by_state": compare_periods(peak_month, peak_month, prev_month, prev_month, dim="state"),
    }


def window_growth_analysis() -> Dict[str, object]:
    """窗口增长归因：2018 上半年（1-8 月）对比 2017 同期，分品类/州。"""
    return {
        "current": "2018-01 ~ 2018-08",
        "previous": "2017-01 ~ 2017-08",
        "by_category": compare_periods("2018-01-01", "2018-08-01", "2017-01-01", "2017-08-01", dim="category"),
        "by_state": compare_periods("2018-01-01", "2018-08-01", "2017-01-01", "2017-08-01", dim="state"),
    }
