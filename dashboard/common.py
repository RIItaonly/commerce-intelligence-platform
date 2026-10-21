"""看板公共层：项目路径引导 + 带缓存的数据加载。

所有页面通过这里取数，保证看板与报告 / SQL 视图使用同一套口径。
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (str(HERE), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import json

import pandas as pd
import streamlit as st

from src import config
from src.analytics import attribution, fulfillment, funnel, kpi, retention, rfm  # noqa: F401

MONTH = lambda m: str(m)[:7]  # noqa: E731


@st.cache_data(ttl=600, show_spinner="加载数据中…")
def headline() -> dict:
    return kpi.headline()


@st.cache_data(ttl=600, show_spinner="加载数据中…")
def monthly() -> pd.DataFrame:
    df = kpi.monthly_kpi()
    df["month"] = df["order_month"].astype(str).str[:7]
    return df


@st.cache_data(ttl=600, show_spinner="加载数据中…")
def top_categories(n: int = 15) -> pd.DataFrame:
    return kpi.top_categories(n)


@st.cache_data(ttl=600, show_spinner="加载数据中…")
def top_states(n: int = 10) -> pd.DataFrame:
    return kpi.top_states(n)


@st.cache_data(ttl=600, show_spinner="加载数据中…")
def seller_concentration() -> dict:
    return kpi.seller_concentration()


@st.cache_data(ttl=600, show_spinner="加载数据中…")
def funnel_data() -> pd.DataFrame:
    return funnel.order_funnel()


@st.cache_data(ttl=600, show_spinner="加载数据中…")
def repeat_summary() -> dict:
    return retention.repeat_summary()


@st.cache_data(ttl=600, show_spinner="加载数据中…")
def cohort_data() -> tuple:
    rates, sizes = retention.cohort_matrix(max_period=8, min_cohort_size=50)
    return rates, sizes


@st.cache_data(ttl=600, show_spinner="加载数据中…")
def new_vs_returning() -> pd.DataFrame:
    df = retention.new_vs_returning()
    df["month"] = df["order_month"].astype(str).str[:7]
    return df


@st.cache_data(ttl=600, show_spinner="加载数据中…")
def rfm_segments() -> pd.DataFrame:
    return rfm.segment_summary()


@st.cache_data(ttl=600, show_spinner="加载数据中…")
def rfm_overview() -> dict:
    return rfm.rfm_overview()


@st.cache_data(ttl=600, show_spinner="加载数据中…")
def delivery_buckets() -> pd.DataFrame:
    return fulfillment.delivery_buckets()


@st.cache_data(ttl=600, show_spinner="加载数据中…")
def late_review() -> dict:
    return fulfillment.late_review()


@st.cache_data(ttl=600, show_spinner="加载数据中…")
def category_control() -> pd.DataFrame:
    return fulfillment.category_control()


@st.cache_data(ttl=600, show_spinner="加载数据中…")
def delivery_stats() -> dict:
    return fulfillment.delivery_stats()


@st.cache_data(ttl=600, show_spinner="加载数据中…")
def state_delivery() -> pd.DataFrame:
    return fulfillment.state_delivery()


@st.cache_data(ttl=600, show_spinner="加载数据中…")
def delivery_correlation() -> dict:
    return fulfillment.delivery_review_correlation()


@st.cache_data(ttl=600, show_spinner="加载数据中…")
def delivery_sample(n: int = 6000) -> pd.DataFrame:
    from src import sql_engine

    return sql_engine.read_sql(
        "SELECT delivery_days, review_score, is_late_delivery "
        "FROM fct_order WHERE is_delivered = 1 AND review_score IS NOT NULL "
        "ORDER BY RANDOM() LIMIT ?",
        params=[n],
    )


@st.cache_data(ttl=600, show_spinner="加载数据中…")
def growth_attribution() -> dict:
    return attribution.window_growth_analysis()


@st.cache_data(ttl=600, show_spinner="加载数据中…")
def peak_attribution() -> dict:
    return attribution.peak_month_analysis()


def fmt_money(v: float) -> str:
    return "R$ {:,.0f}".format(float(v))


def fmt_pct(v: float) -> str:
    return "{:.1f}%".format(float(v) * 100)


def fmt_num(v: float) -> str:
    return "{:,.0f}".format(float(v))


# ---------------------------------------------------------------- 阶段 3 模型产物
def _read_json(name: str) -> dict:
    return json.loads((config.MODEL_DIR / name).read_text(encoding="utf-8"))


@st.cache_data(ttl=600, show_spinner="加载模型结果中…")
def churn_metrics() -> dict:
    return _read_json("churn_metrics.json")


@st.cache_data(ttl=600, show_spinner="加载模型结果中…")
def churn_scores() -> pd.DataFrame:
    return pd.read_csv(config.MODEL_DIR / "churn_scores.csv")


@st.cache_data(ttl=600, show_spinner="加载模型结果中…")
def churn_comparison() -> pd.DataFrame:
    return pd.read_csv(config.MODEL_DIR / "churn_model_comparison.csv")


@st.cache_data(ttl=600, show_spinner="加载模型结果中…")
def churn_importance() -> pd.DataFrame:
    return pd.read_csv(config.MODEL_DIR / "churn_feature_importance.csv")


@st.cache_data(ttl=600, show_spinner="加载模型结果中…")
def churn_calibration() -> pd.DataFrame:
    return pd.read_csv(config.MODEL_DIR / "churn_calibration.csv")


@st.cache_data(ttl=600, show_spinner="加载模型结果中…")
def segmentation_profiles() -> pd.DataFrame:
    return pd.read_csv(config.MODEL_DIR / "segmentation_profiles.csv")


@st.cache_data(ttl=600, show_spinner="加载模型结果中…")
def segmentation_metrics() -> dict:
    return _read_json("segmentation_metrics.json")


@st.cache_data(ttl=600, show_spinner="加载模型结果中…")
def forecast_orders() -> pd.DataFrame:
    return pd.read_csv(config.MODEL_DIR / "forecast_orders.csv", parse_dates=["date"])


@st.cache_data(ttl=600, show_spinner="加载模型结果中…")
def forecast_revenue() -> pd.DataFrame:
    return pd.read_csv(config.MODEL_DIR / "forecast_revenue.csv", parse_dates=["date"])


@st.cache_data(ttl=600, show_spinner="加载模型结果中…")
def forecast_history() -> pd.DataFrame:
    return pd.read_csv(config.MODEL_DIR / "forecast_history.csv", parse_dates=["date"])


@st.cache_data(ttl=600, show_spinner="加载模型结果中…")
def forecast_metrics() -> dict:
    return _read_json("forecast_metrics.json")


@st.cache_data(ttl=600, show_spinner="加载模型结果中…")
def recommendation_metrics() -> dict:
    return _read_json("recommendation_metrics.json")


@st.cache_data(ttl=600, show_spinner="加载模型结果中…")
def recommendation_examples() -> pd.DataFrame:
    return pd.read_csv(config.MODEL_DIR / "recommendation_examples.csv")


@st.cache_data(ttl=600, show_spinner="加载模型结果中…")
def popular_items() -> pd.DataFrame:
    return pd.read_csv(config.MODEL_DIR / "recommendation_popular_items.csv")


@st.cache_data(ttl=600, show_spinner="加载模型结果中…")
def experiment_summary() -> dict:
    return _read_json("experiment_summary.json")
