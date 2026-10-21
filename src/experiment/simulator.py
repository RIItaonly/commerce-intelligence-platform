"""模拟 A/B 实验数据生成器。

为什么需要「模拟」实验：
Olist 是公开的交易数据，用户进入哪个组、是否被促销触达都不是随机分配的，
直接拿它比较「参与促销 vs 未参与」会混入选择偏差。因此本模块**独立生成**一份
带随机分组的用户级实验数据，用来验证分析流程（随机化检查、检验、功效、多重检验）
是否正确；它与真实观测数据严格分开，结论不对外部业务做因果外推。

模拟设定（全部写入报告，避免把模拟结论当真实发现）：
- 随机化单位：用户；对照组/实验组各约 50%。
- 主指标：实验期购买转化率（0/1）。
- 次要指标：人均收入 ARPU（未购买记为 0）、购买者客单价。
- 护栏指标：退款率、投诉率（真实设定为两组相同，用于验证护栏流程）。
- 异质性：不同地区的基线转化率与真实提升不同，用于演示多重检验校正。
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

# 地区：基线转化率、实验组绝对提升（模拟的真实效应）
REGIONS: Dict[str, Dict[str, float]] = {
    "东南部": {"share": 0.45, "baseline_rate": 0.036, "effect": 0.0040},
    "南部": {"share": 0.20, "baseline_rate": 0.032, "effect": 0.0050},
    "东北部": {"share": 0.15, "baseline_rate": 0.026, "effect": 0.0010},
    "中西部": {"share": 0.12, "baseline_rate": 0.030, "effect": 0.0040},
    "北部": {"share": 0.08, "baseline_rate": 0.024, "effect": 0.0000},
}

SEGMENTS = {"新客": 0.55, "老客": 0.32, "高价值客户": 0.13}

BASELINE_REFUND_RATE = 0.025
BASELINE_COMPLAINT_RATE = 0.012
TREATMENT_AOV_LIFT = 0.04

# 固定种子保证报告可复现（选定的种子在模拟中产生一个显著正效应，便于演示完整决策流程）
SEED = 2026
DEFAULT_USERS = 80_000


def generate(n_users: int = DEFAULT_USERS, seed: int = SEED) -> pd.DataFrame:
    """生成用户级模拟实验数据。

    返回列：
      user_id, group(control/treatment), region, segment,
      prior_orders_90d, prior_spend_90d, converted, revenue, refunded, complained
    """
    rng = np.random.default_rng(seed)
    region_names = list(REGIONS.keys())
    region_probs = np.array([REGIONS[r]["share"] for r in region_names])
    segment_names = list(SEGMENTS.keys())
    segment_probs = np.array(list(SEGMENTS.values()))

    region = rng.choice(region_names, size=n_users, p=region_probs)
    segment = rng.choice(segment_names, size=n_users, p=segment_probs)

    # 简单随机分组：Bernoulli(0.5)，并保留随机化检查所需的协变量
    treatment = (rng.random(n_users) < 0.5).astype(int)

    baseline_rates = np.array([REGIONS[r]["baseline_rate"] for r in region])
    effects = np.array([REGIONS[r]["effect"] for r in region])
    conversion_prob = baseline_rates + treatment * effects

    converted = (rng.random(n_users) < conversion_prob).astype(int)

    # 购买者客单价：对数正态；实验组有 4% 的客单价提升（模拟）
    aov = rng.lognormal(mean=np.log(220.0), sigma=0.5, size=n_users)
    revenue = np.where(converted == 1, aov * (1 + TREATMENT_AOV_LIFT * treatment), 0.0).round(2)

    prior_orders = rng.poisson(0.6, size=n_users)
    prior_spend = np.where(
        prior_orders == 0,
        0.0,
        rng.lognormal(mean=np.log(180.0), sigma=0.8, size=n_users) * prior_orders,
    ).round(2)

    refunded = (rng.random(n_users) < BASELINE_REFUND_RATE).astype(int)
    complained = (rng.random(n_users) < BASELINE_COMPLAINT_RATE).astype(int)

    return pd.DataFrame(
        {
            "user_id": ["U%06d" % i for i in range(1, n_users + 1)],
            "group": np.where(treatment == 1, "treatment", "control"),
            "region": region,
            "segment": segment,
            "prior_orders_90d": prior_orders,
            "prior_spend_90d": prior_spend,
            "converted": converted,
            "revenue": revenue,
            "refunded": refunded,
            "complained": complained,
        }
    )


def design_parameters() -> Dict[str, object]:
    """实验设计参数（报告中展示，说明结论可解释的范围）。"""
    return {
        "n_users": DEFAULT_USERS,
        "assignment": "用户级简单随机分组（Bernoulli 0.5）",
        "primary_metric": "购买转化率（实验期是否购买）",
        "secondary_metrics": ["ARPU（人均收入）", "购买者客单价"],
        "guardrails": ["退款率", "投诉率"],
        "segments": ["地区（5 组）"],
        "regions": REGIONS,
        "segments_dist": SEGMENTS,
    }


if __name__ == "__main__":
    frame = generate()
    print(frame.head())
    print(frame.groupby("group")[["converted", "revenue", "refunded", "complained"]].mean())
