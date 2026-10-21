"""履约与体验：配送时长、迟到率、评分关系（含按品类的分层对照）。

数据来源：sql/analytics/07_fulfillment_experience.sql、03_state_performance.sql，
以及 fct_order / fct_order_item 上的直接查询。

诚实边界：以下是观测数据的相关性分析。「迟到 → 低评分」按品类分层后方向一致，
只能排除一部分品类结构差异的混杂，不能排除商家质量、地区物流等未观测因素，
因此报告中只做相关性陈述，不做因果断言（因果评估见阶段 3 的模拟实验模块）。
"""
from __future__ import annotations

from typing import Dict

import pandas as pd
from scipy import stats

from src import sql_engine


def delivery_buckets() -> pd.DataFrame:
    """配送时长分桶 × 评分/迟到率（已签收订单）。"""
    return sql_engine.read_sql(
        "SELECT * FROM analytics_delivery_review ORDER BY bucket_sort"
    )


def late_review() -> Dict[str, Dict[str, float]]:
    """迟到 vs 准时订单的评分对比（订单粒度，已签收）。"""
    df = sql_engine.read_sql("SELECT * FROM analytics_late_review ORDER BY is_late_delivery")
    result: Dict[str, Dict[str, float]] = {}
    for _, row in df.iterrows():
        key = "late" if int(row["is_late_delivery"]) == 1 else "on_time"
        result[key] = {
            "orders": int(row["orders"]),
            "avg_delivery_days": float(row["avg_delivery_days"]),
            "avg_review_score": float(row["avg_review_score"]),
            "bad_review_rate": float(row["bad_review_rate"]),
            "reviews_1": int(row["reviews_1"]),
            "reviews_2": int(row["reviews_2"]),
            "reviews_3": int(row["reviews_3"]),
            "reviews_4": int(row["reviews_4"]),
            "reviews_5": int(row["reviews_5"]),
        }
    if "late" in result and "on_time" in result:
        result["diff"] = {
            "avg_review_score": result["late"]["avg_review_score"] - result["on_time"]["avg_review_score"],
            "bad_review_rate": result["late"]["bad_review_rate"] - result["on_time"]["bad_review_rate"],
        }
    return result


def category_control(min_items: int = 800, top_n: int = 12) -> pd.DataFrame:
    """按品类分层的「迟到 vs 准时」评分对照（控制品类结构差异）。

    粒度 = 明细行（已签收且有评价、有效订单）；只保留样本量足够的品类。
    """
    df = sql_engine.read_sql(
        """
        SELECT
            category_name_en AS category,
            is_late_delivery,
            COUNT(*) AS items,
            AVG(review_score) AS avg_review
        FROM fct_order_item
        WHERE is_valid_order = 1
          AND is_delivered = 1
          AND review_score IS NOT NULL
        GROUP BY category_name_en, is_late_delivery
        """
    )
    enough = df.groupby("category")["items"].sum()
    keep = enough[enough >= min_items].index
    df = df[df["category"].isin(keep)]

    pivot_items = df.pivot(index="category", columns="is_late_delivery", values="items")
    pivot_review = df.pivot(index="category", columns="is_late_delivery", values="avg_review")
    out = pd.DataFrame(
        {
            "items_on_time": pivot_items.get(0),
            "items_late": pivot_items.get(1),
            "review_on_time": pivot_review.get(0),
            "review_late": pivot_review.get(1),
        }
    ).dropna()
    out["review_diff"] = out["review_late"] - out["review_on_time"]
    out["items_total"] = out["items_on_time"] + out["items_late"]
    return out.sort_values("items_total", ascending=False).head(top_n).reset_index()


def delivery_review_correlation() -> Dict[str, float]:
    """配送时长 / 迟到天数与评分的相关系数（已签收且有评价的订单）。"""
    df = sql_engine.read_sql(
        """
        SELECT delivery_days, delay_days, review_score
        FROM fct_order
        WHERE is_delivered = 1 AND review_score IS NOT NULL
        """
    )
    pearson_r, pearson_p = stats.pearsonr(df["delivery_days"], df["review_score"])
    spearman_r, spearman_p = stats.spearmanr(df["delivery_days"], df["review_score"])
    delay_r, delay_p = stats.pearsonr(df["delay_days"], df["review_score"])
    return {
        "n": int(len(df)),
        "pearson_delivery_days": float(pearson_r),
        "pearson_delivery_days_p": float(pearson_p),
        "spearman_delivery_days": float(spearman_r),
        "spearman_delivery_days_p": float(spearman_p),
        "pearson_delay_days": float(delay_r),
        "pearson_delay_days_p": float(delay_p),
    }


def state_delivery() -> pd.DataFrame:
    """各州履约与体验（配送时长、迟到率、评分），按单量排序。"""
    return sql_engine.read_sql(
        "SELECT * FROM analytics_state_performance ORDER BY orders DESC"
    )


def delivery_stats() -> Dict[str, float]:
    """配送时长分布要点（已签收订单）。"""
    df = sql_engine.read_sql(
        """
        SELECT delivery_days, estimated_days, delay_days
        FROM fct_order
        WHERE is_delivered = 1
        """
    )
    return {
        "n": int(len(df)),
        "avg_delivery_days": float(df["delivery_days"].mean()),
        "median_delivery_days": float(df["delivery_days"].median()),
        "p90_delivery_days": float(df["delivery_days"].quantile(0.9)),
        "avg_estimated_days": float(df["estimated_days"].mean()),
        "avg_delay_days_when_late": float(df.loc[df["delay_days"] > 0, "delay_days"].mean()),
    }
