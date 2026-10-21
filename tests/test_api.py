"""FastAPI 接口测试：基于 TestClient 的端到端冒烟。

依赖 models/artifacts/ 下的离线模型产物（由流水线生成），
因此本测试文件假设流水线已至少跑过阶段 3 的模型步骤。
"""
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from src import config
from src.api.app import app

client = TestClient(app)

pytestmark = pytest.mark.skipif(
    not (config.MODEL_DIR / "churn_scores.csv").exists(),
    reason="模型产物不存在，需先运行流水线",
)


def _first_id(csv_name: str) -> str:
    return pd.read_csv(config.MODEL_DIR / csv_name, usecols=["customer_unique_id"])[
        "customer_unique_id"
    ].iloc[0]


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "churn_scores.csv" in body["artifacts"]


def test_churn_score_and_404():
    cid = _first_id("churn_scores.csv")
    resp = client.get(f"/churn/score/{cid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["customer_unique_id"] == cid
    assert 0.0 <= body["p_active_30d"] <= 1.0
    assert 0.0 <= body["churn_risk"] <= 1.0
    assert client.get("/churn/score/__not_exist__").status_code == 404


def test_churn_top_risk():
    resp = client.get("/churn/top-risk?n=5")
    assert resp.status_code == 200
    customers = resp.json()["customers"]
    assert len(customers) == 5
    risks = [c["churn_risk"] for c in customers]
    assert risks == sorted(risks, reverse=True)


def test_segment():
    cid = _first_id("segmentation_labels.csv")
    resp = client.get(f"/segment/{cid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["cluster_name"]
    assert body["rule_segment"]
    assert client.get("/segment/__not_exist__").status_code == 404


def test_recommend_cf_and_cold_start():
    # 训练期有行为的用户 → 协同过滤
    warm_id = _first_id("recommendation_examples.csv")
    resp = client.get(f"/recommend/{warm_id}?k=5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "cf"
    assert len(body["items"]) == 5
    assert all("product_id" in item for item in body["items"])
    # 未知用户 → 冷启动回退热门
    resp = client.get("/recommend/__cold_user__?k=5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "popularity"
    assert len(body["items"]) == 5


def test_forecast():
    for target in ("orders", "revenue"):
        resp = client.get(f"/forecast?target={target}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["n_days"] == 30
        row = body["forecast"][0]
        assert row["lower_80"] <= row["forecast"] <= row["upper_80"]
    assert client.get("/forecast?target=bogus").status_code == 422


def test_model_metrics():
    resp = client.get("/model/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) >= {"churn", "segmentation", "recommendation", "forecast"}
