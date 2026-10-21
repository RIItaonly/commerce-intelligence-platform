"""RFM 客户分群（规则版；K-Means 版本在阶段 3 的建模模块中对比）。

数据来源：sql/analytics/06_rfm.sql → analytics_rfm。

为什么用规则而不是直接用 SQL 里的 NTILE 分数：
Olist 约 97% 客户只有 1 单，frequency 严重并列，NTILE(5) 在 F 维度退化。
因此这里用「业务可解释的阈值规则」分群，NTILE 分数仅作为参考列保留。
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from src import sql_engine

SEGMENT_ORDER = [
    "忠诚客户（3 单以上）",
    "复购客户（2 单）",
    "近期活跃（90 天内首单）",
    "活跃客户（180 天内有购买）",
    "流失风险（180-365 天未购）",
    "沉睡客户（超过 365 天未购）",
]


def load_rfm() -> pd.DataFrame:
    return sql_engine.read_sql("SELECT * FROM analytics_rfm")


def add_segments(df: pd.DataFrame) -> pd.DataFrame:
    """按业务规则打客户分群标签 + 高价值标记（monetary 前 20%）。"""
    df = df.copy()
    conditions = [
        df["frequency"] >= 3,
        df["frequency"] == 2,
        (df["frequency"] == 1) & (df["recency_days"] <= 90),
        df["recency_days"] <= 180,
        df["recency_days"] <= 365,
    ]
    choices = SEGMENT_ORDER[:5]
    df["segment"] = np.select(conditions, choices, default=SEGMENT_ORDER[5])
    threshold = df["monetary"].quantile(0.8)
    df["is_high_value"] = (df["monetary"] >= threshold).astype(int)
    return df


def segment_summary() -> pd.DataFrame:
    """各分群的人数、收入贡献与 R/F/M 均值。"""
    df = add_segments(load_rfm())
    total_revenue = df["monetary"].sum()
    summary = (
        df.groupby("segment")
        .agg(
            customers=("customer_unique_id", "count"),
            revenue=("monetary", "sum"),
            avg_recency_days=("recency_days", "mean"),
            avg_frequency=("frequency", "mean"),
            avg_monetary=("monetary", "mean"),
        )
        .reindex(SEGMENT_ORDER)
        .dropna(how="all")
        .reset_index()
    )
    summary["revenue_share"] = summary["revenue"] / total_revenue
    summary["customer_share"] = summary["customers"] / summary["customers"].sum()
    return summary


def rfm_overview() -> Dict[str, float]:
    """RFM 全局概览：客户数、R/F/M 中位数、高价值客户占比。"""
    df = load_rfm()
    threshold = df["monetary"].quantile(0.8)
    return {
        "customers": int(len(df)),
        "median_recency_days": float(df["recency_days"].median()),
        "median_frequency": float(df["frequency"].median()),
        "median_monetary": float(df["monetary"].median()),
        "high_value_threshold": float(threshold),
        "high_value_share": float((df["monetary"] >= threshold).mean()),
        "single_order_share": float((df["frequency"] == 1).mean()),
    }
