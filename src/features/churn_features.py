"""流失/复购预测的特征构建（严格按时间切分，避免数据泄漏）。

任务定义（与业务对齐）：
    在每个月初的快照上，用**过去 90 天**的交易行为预测该用户**未来 30 天**是否会再次购买。
    预测概率 p(复购) 越高，流失风险越低（risk = 1 - p）。

为什么这样定义：
1. Olist 约 97% 用户只有一单，「未来 30 天是否流失」的正类会占 97%，模型无法提供排序价值；
   「未来 30 天是否复购」是一个稀有事件，更适合评估排序能力（PR-AUC、top-decile lift）。
2. 特征只使用快照之前的数据，标签只使用快照之后 30 天的数据，两者在时间上完全不重叠。

快照选择：
- 2017-04-01 ~ 2018-08-01，每月 1 日一个快照（共 17 个）。
- 训练集：快照 <= 2018-03-01；测试集：快照 >= 2018-04-01（时间外验证）。
- 最后一个快照（2018-08-01）用于给当前用户打分。
"""
from __future__ import annotations

from datetime import timedelta
from typing import List, Tuple

import pandas as pd

from src import sql_engine

LOOKBACK_DAYS = 90
LABEL_DAYS = 30

SNAPSHOT_START = "2017-04-01"
SNAPSHOT_END = "2018-08-01"
TRAIN_LAST_SNAPSHOT = "2018-03-01"
SCORING_SNAPSHOT = "2018-08-01"

NUMERIC_FEATURES = [
    "recency_days",
    "tenure_days",
    "orders_90d",
    "items_90d",
    "revenue_90d",
    "gmv_90d",
    "freight_share_90d",
    "avg_order_value_90d",
    "avg_review_90d",
    "bad_review_rate_90d",
    "review_missing_rate_90d",
    "avg_delivery_days_90d",
    "late_rate_90d",
    "delivered_rate_90d",
    "avg_installments_90d",
    "multi_item_rate_90d",
    "multi_seller_rate_90d",
    "category_breadth_90d",
    "n_sellers_90d",
    "lifetime_orders",
    "lifetime_revenue",
    "repeat_buyer",
]
CATEGORICAL_FEATURES = ["customer_state"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET = "active_30d"


def load_orders() -> pd.DataFrame:
    """加载有效订单（订单粒度，已预聚合，避免 fan-out）。"""
    df = sql_engine.read_sql(
        """
        SELECT
            order_id,
            customer_unique_id,
            customer_state,
            purchase_ts,
            payment_total,
            product_gmv,
            freight_total,
            item_count,
            seller_count,
            review_score,
            is_bad_review,
            delivery_days,
            is_late_delivery,
            is_delivered,
            max_installments
        FROM fct_order
        WHERE is_valid_order = 1 AND purchase_ts IS NOT NULL
        """
    )
    df["purchase_ts"] = pd.to_datetime(df["purchase_ts"])
    return df


def load_order_category_breadth() -> pd.DataFrame:
    """每个订单覆盖的商品类目数（用于特征，不引入明细 fan-out）。"""
    return sql_engine.read_sql(
        """
        SELECT order_id, COUNT(DISTINCT category_name_en) AS n_categories
        FROM fct_order_item
        GROUP BY order_id
        """
    )


def _snapshot_rows(
    snapshot: pd.Timestamp,
    orders: pd.DataFrame,
    category_breadth: pd.DataFrame,
    with_label: bool = True,
) -> pd.DataFrame:
    """构建单个快照的特征（可选标签）。"""
    history_start = snapshot - timedelta(days=LOOKBACK_DAYS)
    history = orders[(orders["purchase_ts"] >= history_start) & (orders["purchase_ts"] < snapshot)].copy()
    if history.empty:
        return pd.DataFrame()

    history = history.merge(category_breadth, on="order_id", how="left")
    history["n_categories"] = history["n_categories"].fillna(1)
    history["is_multi_item"] = (history["item_count"] > 1).astype(int)
    history["is_multi_seller"] = (history["seller_count"] > 1).astype(int)

    grouped = history.groupby("customer_unique_id")
    features = pd.DataFrame(
        {
            "last_purchase_ts": grouped["purchase_ts"].max(),
            "orders_90d": grouped["order_id"].nunique(),
            "items_90d": grouped["item_count"].sum(),
            "revenue_90d": grouped["payment_total"].sum(),
            "gmv_90d": grouped["product_gmv"].sum(),
            "freight_90d": grouped["freight_total"].sum(),
            "avg_review_90d": grouped["review_score"].mean(),
            "bad_review_rate_90d": grouped["is_bad_review"].mean(),
            "reviews_90d": grouped["review_score"].count(),
            "avg_delivery_days_90d": grouped["delivery_days"].mean(),
            "late_rate_90d": grouped["is_late_delivery"].mean(),
            "delivered_rate_90d": grouped["is_delivered"].mean(),
            "avg_installments_90d": grouped["max_installments"].mean(),
            "multi_item_rate_90d": grouped["is_multi_item"].mean(),
            "multi_seller_rate_90d": grouped["is_multi_seller"].mean(),
            "category_breadth_90d": grouped["n_categories"].sum(),
            "n_sellers_90d": grouped["seller_count"].sum(),
            "customer_state": grouped["customer_state"].last(),
        }
    ).reset_index()

    # 按自然日计算，避免用时间戳做差时把「昨天 23:00」算成 0 天
    features["recency_days"] = (
        snapshot.normalize() - features["last_purchase_ts"].dt.normalize()
    ).dt.days
    features["freight_share_90d"] = (
        features["freight_90d"] / features["revenue_90d"].replace(0, pd.NA)
    ).fillna(0.0)
    features["avg_order_value_90d"] = (
        features["revenue_90d"] / features["orders_90d"].replace(0, pd.NA)
    ).fillna(0.0)
    features["review_missing_rate_90d"] = 1 - (
        features["reviews_90d"] / features["orders_90d"].replace(0, pd.NA)
    )
    features["review_missing_rate_90d"] = features["review_missing_rate_90d"].fillna(1.0)
    features["repeat_buyer"] = (features["orders_90d"] >= 2).astype(int)

    # 生命周期特征：快照前的全部有效订单（不是未来信息）
    lifetime = orders.loc[orders["purchase_ts"] < snapshot].groupby("customer_unique_id").agg(
        first_purchase_ts=("purchase_ts", "min"),
        lifetime_orders=("order_id", "nunique"),
        lifetime_revenue=("payment_total", "sum"),
    )
    features = features.merge(lifetime, left_on="customer_unique_id", right_index=True, how="left")
    features["tenure_days"] = (
        snapshot.normalize() - features["first_purchase_ts"].dt.normalize()
    ).dt.days
    features["customer_state"] = features["customer_state"].fillna("UNKNOWN")

    features["snapshot"] = snapshot
    features["snapshot_month"] = snapshot.strftime("%Y-%m")

    if with_label:
        future = orders[
            (orders["purchase_ts"] >= snapshot)
            & (orders["purchase_ts"] < snapshot + timedelta(days=LABEL_DAYS))
        ]
        active_ids = set(future["customer_unique_id"].unique())
        features[TARGET] = features["customer_unique_id"].isin(active_ids).astype(int)

    columns = ["customer_unique_id", "snapshot", "snapshot_month"] + FEATURES
    if with_label:
        columns.append(TARGET)
    return features[columns]


def build_dataset(with_label: bool = True) -> pd.DataFrame:
    """构建全部快照的训练/评估数据集。"""
    orders = load_orders()
    category_breadth = load_order_category_breadth()
    snapshots = pd.date_range(SNAPSHOT_START, SNAPSHOT_END, freq="MS")
    frames = []
    for snapshot in snapshots:
        rows = _snapshot_rows(snapshot, orders, category_breadth, with_label=with_label)
        if not rows.empty:
            frames.append(rows)
    dataset = pd.concat(frames, ignore_index=True)
    dataset["customer_state"] = dataset["customer_state"].fillna("UNKNOWN")
    return dataset


def build_scoring_set(snapshot: str = SCORING_SNAPSHOT) -> pd.DataFrame:
    """构建单个快照的评分数据（无标签），用于给当前用户打分。"""
    orders = load_orders()
    category_breadth = load_order_category_breadth()
    return _snapshot_rows(pd.Timestamp(snapshot), orders, category_breadth, with_label=False)


def split_time(dataset: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """按快照时间切分：训练 <= 2018-03，测试 >= 2018-04。"""
    train_mask = dataset["snapshot"] <= pd.Timestamp(TRAIN_LAST_SNAPSHOT)
    return dataset[train_mask].reset_index(drop=True), dataset[~train_mask].reset_index(drop=True)


def leakage_checks(dataset: pd.DataFrame) -> List[str]:
    """可执行的特征泄漏检查，供测试与流水线调用。"""
    issues: List[str] = []
    if dataset["snapshot"].isna().any():
        issues.append("存在空快照")
    if (dataset["recency_days"] < 0).any():
        issues.append("recency_days 为负，说明特征使用了快照之后的数据")
    if (dataset["tenure_days"] < 0).any():
        issues.append("tenure_days 为负")
    if TARGET in dataset.columns:
        rate = dataset[TARGET].mean()
        if not 0 <= rate <= 1:
            issues.append("标签比例异常：%.3f" % rate)
    if "orders_90d" in dataset and (dataset["orders_90d"] <= 0).any():
        issues.append("orders_90d 存在非正值")
    return issues


if __name__ == "__main__":
    data = build_dataset()
    print(data.shape)
    print(data.groupby("snapshot_month")[TARGET].agg(["count", "mean"]).tail(8))
    print("泄漏检查：", leakage_checks(data) or "全部通过")
