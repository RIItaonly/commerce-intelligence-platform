"""FastAPI 预测/推荐接口：服务阶段 3 训练产出的模型结果。

设计说明
--------
- 模型在离线流水线（src/pipeline.py）中训练，API 只读取 models/artifacts/ 下的
  产物做推理服务，不在线重训，保证部署轻量、结果可复现。
- 启动时一次性加载 CSV/JSON 产物到内存（churn_scores 约 4.5MB、
  segmentation_labels 约 12MB，均在内存可承受范围）。
- 推荐接口对接 item-item 协同过滤的离线推荐清单；训练期无行为的冷启动用户
  回退到热门商品（诚实降级，并在响应中标注 source 字段）。

启动方式
--------
    uvicorn src.api.app:app --host 0.0.0.0 --port 8000
"""
import json
from functools import lru_cache
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query

from .. import config

app = FastAPI(
    title="Commerce Intelligence API",
    description=(
        "端到端电商智能决策平台的模型服务接口：流失风险打分、客户分群、"
        "商品推荐、销售预测。数据来自 Olist 巴西电商公开数据集，"
        "模型由离线流水线训练，API 仅做推理服务。"
    ),
    version="1.0.0",
)


# --------------------------------------------------------------------------- #
# 产物加载（lru_cache 保证进程内只加载一次）
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def _churn_scores() -> pd.DataFrame:
    df = pd.read_csv(config.MODEL_DIR / "churn_scores.csv")
    # 每个客户可能出现在多个快照，服务时只保留最新快照的打分
    df = df.sort_values("snapshot").groupby("customer_unique_id", as_index=False).tail(1)
    return df.set_index("customer_unique_id", drop=False)


@lru_cache(maxsize=1)
def _segments() -> pd.DataFrame:
    df = pd.read_csv(config.MODEL_DIR / "segmentation_labels.csv")
    return df.set_index("customer_unique_id", drop=False)


@lru_cache(maxsize=1)
def _recommendations() -> pd.DataFrame:
    return pd.read_csv(config.MODEL_DIR / "recommendation_examples.csv")


@lru_cache(maxsize=1)
def _popular_items() -> pd.DataFrame:
    return pd.read_csv(config.MODEL_DIR / "recommendation_popular_items.csv")


@lru_cache(maxsize=1)
def _forecast(target: str) -> pd.DataFrame:
    return pd.read_csv(config.MODEL_DIR / f"forecast_{target}.csv")


@lru_cache(maxsize=None)
def _metrics(name: str) -> dict:
    path = config.MODEL_DIR / f"{name}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _clean(record: dict) -> dict:
    """把 numpy 标量/NaN 转成 JSON 可序列化的 Python 原生类型。"""
    out = {}
    for key, value in record.items():
        if pd.isna(value):
            out[key] = None
        elif hasattr(value, "item"):
            out[key] = value.item()
        else:
            out[key] = value
    return out


# --------------------------------------------------------------------------- #
# 接口
# --------------------------------------------------------------------------- #
@app.get("/health")
def health() -> dict:
    artifacts = sorted(p.name for p in config.MODEL_DIR.glob("*"))
    return {"status": "ok", "n_artifacts": len(artifacts), "artifacts": artifacts}


@app.get("/churn/score/{customer_unique_id}")
def churn_score(customer_unique_id: str) -> dict:
    """客户流失（更准确说是 30 天复购概率）打分。

    返回最新快照下的复购概率 p_active_30d、流失风险 churn_risk 与风险分层。
    """
    scores = _churn_scores()
    if customer_unique_id not in scores.index:
        raise HTTPException(status_code=404, detail="客户不存在或无最新打分")
    row = scores.loc[customer_unique_id]
    return _clean(
        {
            "customer_unique_id": row["customer_unique_id"],
            "snapshot": row["snapshot"],
            "p_active_30d": row["p_active_30d"],
            "churn_risk": row["churn_risk"],
            "risk_band": row["risk_band"],
            "recency_days": row["recency_days"],
            "lifetime_orders": row["lifetime_orders"],
            "lifetime_revenue": row["lifetime_revenue"],
            "customer_state": row["customer_state"],
        }
    )


@app.get("/churn/top-risk")
def churn_top_risk(n: int = Query(20, ge=1, le=500)) -> dict:
    """流失风险最高的客户清单（用于运营挽留名单）。"""
    scores = _churn_scores().reset_index(drop=True)
    top = scores.nlargest(n, "churn_risk")[
        [
            "customer_unique_id",
            "churn_risk",
            "risk_band",
            "recency_days",
            "lifetime_orders",
            "lifetime_revenue",
            "customer_state",
        ]
    ]
    return {"n": len(top), "customers": [_clean(r) for r in top.to_dict("records")]}


@app.get("/segment/{customer_unique_id}")
def segment(customer_unique_id: str) -> dict:
    """客户分群标签（KMeans 聚类 + 规则分层对照）。"""
    segments = _segments()
    if customer_unique_id not in segments.index:
        raise HTTPException(status_code=404, detail="客户不存在")
    row = segments.loc[customer_unique_id]
    return _clean(
        {
            "customer_unique_id": row["customer_unique_id"],
            "cluster": row["cluster"],
            "cluster_name": row["cluster_name"],
            "rule_segment": row["rule_segment"],
            "recency_days": row["recency_days"],
            "frequency": row["frequency"],
            "monetary": row["monetary"],
        }
    )


@app.get("/recommend/{customer_unique_id}")
def recommend(customer_unique_id: str, k: int = Query(10, ge=1, le=50)) -> dict:
    """商品推荐。

    训练期有购买行为的用户返回 item-item 协同过滤结果（source=cf），
    冷启动用户回退到全局热门商品（source=popularity）。
    注意：Olist 无曝光/点击日志，这是基于购买行为的推荐。
    """
    recs = _recommendations()
    user_recs = recs[recs["customer_unique_id"] == customer_unique_id].head(k)
    if len(user_recs) > 0:
        items = user_recs[["rank", "product_id", "category", "avg_price"]].to_dict("records")
        return {
            "customer_unique_id": customer_unique_id,
            "source": "cf",
            "items": [_clean(r) for r in items],
        }
    popular = _popular_items().head(k)
    popular = popular.rename(columns={"category_name_en": "category"})
    cols = [c for c in ("product_id", "category", "avg_price") if c in popular.columns]
    return {
        "customer_unique_id": customer_unique_id,
        "source": "popularity",
        "note": "冷启动用户（训练期无购买行为），回退到热门商品",
        "items": [_clean(r) for r in popular[cols].to_dict("records")],
    }


@app.get("/forecast")
def forecast(target: str = Query("orders", regex="^(orders|revenue)$")) -> dict:
    """未来 30 天的订单量 / 收入预测（含 80% 预测区间）。"""
    df = _forecast(target)
    return {
        "target": target,
        "model": str(df["model"].iloc[0]),
        "n_days": len(df),
        "forecast": [_clean(r) for r in df.to_dict("records")],
    }


@app.get("/model/metrics")
def model_metrics() -> dict:
    """各模型的离线评估指标摘要（流失 / 分群 / 推荐 / 预测）。"""
    return {
        "churn": _metrics("churn_metrics"),
        "segmentation": _metrics("segmentation_metrics"),
        "recommendation": _metrics("recommendation_metrics"),
        "forecast": _metrics("forecast_metrics"),
        "experiment": _metrics("experiment_summary"),
    }
