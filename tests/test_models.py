"""流失特征与模型评估函数的测试：重点验证时间边界、无泄漏、指标正确性。"""
import numpy as np
import pandas as pd
import pytest

from src.features import churn_features as cf
from src.models import churn, forecasting, recommender, segmentation


def _synthetic_orders() -> pd.DataFrame:
    rows = [
        # A：快照前 12 天 + 2 天各一单；快照后 4 天还有一单（标签应命中）
        ("o1", "A", "SP", "2018-05-20 10:00:00", 100.0, 90.0, 8.0, 1, 1, 5, 0, 10, 0, 1, 1),
        ("o2", "A", "SP", "2018-05-30 10:00:00", 50.0, 45.0, 5.0, 1, 1, 4, 0, 12, 0, 1, 2),
        ("o3", "A", "SP", "2018-06-05 10:00:00", 70.0, 60.0, 10.0, 1, 1, 5, 0, 3, 0, 1, 1),
        # B：快照前 83 天，已签收但无评价；标签应为 0
        ("o4", "B", "RJ", "2018-03-10 10:00:00", 200.0, 180.0, 20.0, 2, 1, np.nan, 0, np.nan, 0, 1, 3),
        # C：只有快照之后的订单，不能出现在特征里
        ("o5", "C", "MG", "2018-06-03 10:00:00", 30.0, 25.0, 5.0, 1, 1, 5, 0, 4, 0, 1, 1),
        # D：快照前 120 天，超出 90 天回看窗口
        ("o6", "D", "RS", "2018-02-01 10:00:00", 80.0, 70.0, 10.0, 1, 1, 3, 1, 20, 1, 1, 1),
    ]
    columns = [
        "order_id", "customer_unique_id", "customer_state", "purchase_ts",
        "payment_total", "product_gmv", "freight_total", "item_count", "seller_count",
        "review_score", "is_bad_review", "delivery_days", "is_late_delivery",
        "is_delivered", "max_installments",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    frame["purchase_ts"] = pd.to_datetime(frame["purchase_ts"])
    return frame


def _category_breadth(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({"order_id": frame["order_id"], "n_categories": 1})


def test_snapshot_respects_time_boundaries():
    orders = _synthetic_orders()
    snapshot = pd.Timestamp("2018-06-01")
    result = cf._snapshot_rows(snapshot, orders, _category_breadth(orders), with_label=True)

    assert set(result["customer_unique_id"]) == {"A", "B"}
    customer_a = result.set_index("customer_unique_id").loc["A"]
    assert customer_a["orders_90d"] == 2
    assert customer_a["recency_days"] == 2
    assert customer_a["revenue_90d"] == pytest.approx(150.0)
    assert customer_a["active_30d"] == 1
    assert customer_a["tenure_days"] == 12

    customer_b = result.set_index("customer_unique_id").loc["B"]
    assert customer_b["orders_90d"] == 1
    assert customer_b["recency_days"] == 83
    assert customer_b["review_missing_rate_90d"] == pytest.approx(1.0)
    assert customer_b["active_30d"] == 0


def test_snapshot_leakage_checks_pass():
    orders = _synthetic_orders()
    result = cf._snapshot_rows(
        pd.Timestamp("2018-06-01"), orders, _category_breadth(orders), with_label=True
    )
    assert cf.leakage_checks(result) == []


def test_time_split_is_strict():
    frame = pd.DataFrame(
        {
            "snapshot": pd.to_datetime(["2018-02-01", "2018-03-01", "2018-04-01"]),
            "customer_unique_id": ["a", "b", "c"],
            "recency_days": [1, 2, 3],
            "tenure_days": [10, 20, 30],
            "orders_90d": [1, 1, 1],
            "active_30d": [0, 1, 0],
        }
    )
    train, test = cf.split_time(frame)
    assert list(train["snapshot"].dt.strftime("%Y-%m")) == ["2018-02", "2018-03"]
    assert list(test["snapshot"].dt.strftime("%Y-%m")) == ["2018-04"]


def test_ranking_metrics_known_values():
    y = np.array([0, 0, 1, 1])
    score = np.array([0.1, 0.2, 0.8, 0.9])
    result = churn.ranking_metrics(y, score)
    assert result["positives"] == 2
    assert result["base_rate"] == 0.5
    assert result["pr_auc"] == pytest.approx(1.0)
    assert result["roc_auc"] == pytest.approx(1.0)
    assert result["top10_precision"] == pytest.approx(1.0)
    assert result["top10_recall"] == pytest.approx(0.5)
    assert result["lift_at_10pct"] == pytest.approx(2.0)


def test_ndcg_known_value():
    # 命中位置 1 和 3，共 3 个相关项
    value = recommender._ndcg([1, 0, 1], total_relevant=3, k=3)
    expected = (1.0 + 1.0 / np.log2(4)) / (1.0 + 1.0 / np.log2(3) + 1.0 / np.log2(4))
    assert value == pytest.approx(expected)


def test_recency_rule_score_monotone():
    frame = pd.DataFrame({"recency_days": [0.0, 10.0, 90.0]})
    scores = churn._rule_score(frame)
    assert scores[0] > scores[1] > scores[2]


def test_seasonal_naive_uses_lag_seven():
    history = pd.Series(np.arange(14, dtype=float), index=pd.date_range("2018-01-01", periods=14))
    forecast = forecasting.seasonal_naive(history, horizon=7)
    assert forecast.tolist() == [7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0]


def test_forecast_metrics_zero_error():
    result = forecasting._metrics(np.array([1.0, 2.0]), np.array([1.0, 2.0]))
    assert result["mae"] == 0.0
    assert result["rmse"] == 0.0


def test_lag_features_values():
    history = list(np.arange(1, 31, dtype=float))  # 1..30
    features = forecasting._lag_features(history, pd.Timestamp("2018-02-01"))
    assert features["lag_1"] == 30.0
    assert features["lag_7"] == 24.0
    assert features["roll_mean_7"] == pytest.approx(np.mean(np.arange(24, 31)))
    assert features["roll_mean_28"] == pytest.approx(np.mean(np.arange(3, 31)))


def test_kmeans_on_three_blobs():
    rng = np.random.default_rng(0)
    x = np.vstack([rng.normal(0, 0.1, (50, 3)), rng.normal(5, 0.1, (50, 3)), rng.normal(-5, 0.1, (50, 3))])
    result = segmentation._fit_kmeans(x, k=3, seed=1, n_init=3)
    assert len(np.unique(result["labels"])) == 3
    predicted = segmentation._predict(result["centroids"], result["centroids"])
    assert predicted.tolist() == [0, 1, 2]
