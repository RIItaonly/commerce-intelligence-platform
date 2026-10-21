"""真实观测数据的统计描述（不含任何因果断言）。

数据来源：`fct_order`（订单粒度，已做 fan-out 预聚合）。

为什么单独做这个模块：
1. 简历里「会统计学」需要证据——这里对真实经营数据做描述性统计、
   区间估计与分层对照，说明我们理解「点估计 + 不确定性」。
2. 同时它也是第 4 节结论边界的技术支撑：真实数据只能支持相关性陈述。
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

from src import sql_engine
from src.statistics import inference


def _state_sample() -> pd.DataFrame:
    return sql_engine.read_sql(
        """
        SELECT
            customer_state,
            AVG(CASE WHEN is_delivered = 1 AND review_score IS NOT NULL
                     THEN review_score END) AS avg_review,
            AVG(CASE WHEN is_delivered = 1 THEN delivery_days END) AS avg_delivery_days,
            COUNT(*) AS orders
        FROM fct_order
        WHERE is_valid_order = 1
        GROUP BY customer_state
        HAVING COUNT(*) >= 100
        ORDER BY orders DESC
        """
    )


def sample_distribution_state_means(n_draws: int = 2000, sample_size: int = 300, seed: int = 42) -> Dict[str, object]:
    """抽样分布演示：各州平均评分的抽样分布（中心极限定理的直观证据）。

    做法：对每个州做 `n_draws` 次有放回抽样（每次 `sample_size` 单），
    记录抽样均值的分布，输出均值、标准差（即标准误）和 2.5%/97.5% 分位。
    """
    df = sql_engine.read_sql(
        """
        SELECT customer_state, review_score
        FROM fct_order
        WHERE is_valid_order = 1 AND review_score IS NOT NULL
        """
    )
    rng = np.random.default_rng(seed)
    rows: List[Dict[str, float]] = []
    for state, group in df.groupby("customer_state"):
        values = group["review_score"].to_numpy(dtype=float)
        if len(values) < 300:
            continue
        means = np.array(
            [rng.choice(values, size=sample_size, replace=True).mean() for _ in range(n_draws)]
        )
        rows.append(
            {
                "state": state,
                "population_mean": float(values.mean()),
                "population_std": float(values.std(ddof=1)),
                "n_population": int(len(values)),
                "sampling_mean": float(means.mean()),
                "sampling_se": float(means.std(ddof=1)),
                "sampling_p2_5": float(np.quantile(means, 0.025)),
                "sampling_p97_5": float(np.quantile(means, 0.975)),
                "theoretical_se": float(values.std(ddof=1) / np.sqrt(sample_size)),
            }
        )
    table = pd.DataFrame(rows).sort_values("n_population", ascending=False)
    return {
        "n_draws": n_draws,
        "sample_size": sample_size,
        "table": table.reset_index(drop=True),
        "max_se_gap": float((table["sampling_se"] - table["theoretical_se"]).abs().max()),
    }


def state_mean_ci(confidence: float = 0.95, min_orders: int = 100) -> pd.DataFrame:
    """各州平均评分与平均配送时长的区间估计（订单粒度）。"""
    df = sql_engine.read_sql(
        """
        SELECT customer_state, delivery_days, review_score, is_delivered, is_valid_order
        FROM fct_order
        WHERE is_valid_order = 1
        """
    )
    rows: List[Dict[str, float]] = []
    for state, group in df.groupby("customer_state"):
        if len(group) < min_orders:
            continue
        delivered = group[group["is_delivered"] == 1]
        reviewed = delivered[delivered["review_score"].notna()]
        delivery_ci = inference.mean_ci(delivered["delivery_days"].to_numpy(dtype=float), confidence)
        review_ci = inference.mean_ci(reviewed["review_score"].to_numpy(dtype=float), confidence)
        rows.append(
            {
                "state": state,
                "orders": int(len(group)),
                "avg_delivery_days": delivery_ci["mean"],
                "delivery_ci_low": delivery_ci["ci_low"],
                "delivery_ci_high": delivery_ci["ci_high"],
                "avg_review": review_ci["mean"],
                "review_ci_low": review_ci["ci_low"],
                "review_ci_high": review_ci["ci_high"],
                "reviews": review_ci["n"],
            }
        )
    return pd.DataFrame(rows).sort_values("orders", ascending=False).reset_index(drop=True)


def late_vs_ontime_by_state() -> Dict[str, object]:
    """按州分层的「迟到 vs 准时」评分对照，并对每个州做 Welch t 检验。

    这是「控制地区差异后差异是否依然存在」的统计版本，
    结果只说明观测数据的相关性结构，不做因果解释。
    """
    df = sql_engine.read_sql(
        """
        SELECT customer_state, is_late_delivery, review_score
        FROM fct_order
        WHERE is_valid_order = 1 AND is_delivered = 1 AND review_score IS NOT NULL
        """
    )
    rows: List[Dict[str, float]] = []
    for state, group in df.groupby("customer_state"):
        late = group.loc[group["is_late_delivery"] == 1, "review_score"].to_numpy(dtype=float)
        on_time = group.loc[group["is_late_delivery"] == 0, "review_score"].to_numpy(dtype=float)
        if len(late) < 60 or len(on_time) < 60:
            continue
        test = inference.welch_ttest(on_time, late)
        rows.append(
            {
                "state": state,
                "n_on_time": test["n_a"],
                "n_late": test["n_b"],
                "avg_on_time": test["mean_a"],
                "avg_late": test["mean_b"],
                "diff": test["diff"],
                "ci_low": test["ci_low"],
                "ci_high": test["ci_high"],
                "p_value": test["p_value"],
                "cohens_d": test["cohens_d"],
            }
        )
    table = pd.DataFrame(rows).sort_values("n_late", ascending=False).reset_index(drop=True)
    adjusted = inference.adjust_pvalues(table["p_value"].tolist(), method="bh")
    table["p_adjusted"] = adjusted["adjusted"]
    table["significant_bh"] = adjusted["rejected"]
    return {
        "table": table,
        "n_states": int(len(table)),
        "n_significant_raw": int((table["p_value"] < 0.05).sum()),
        "n_significant_bh": int(table["significant_bh"].sum()),
        "sample_median_diff": float(table["diff"].median()),
    }


def late_review_chi_square() -> Dict[str, float]:
    """迟到 × 是否为差评（≤2 分）的列联表卡方检验。"""
    df = sql_engine.read_sql(
        """
        SELECT is_late_delivery, is_bad_review
        FROM fct_order
        WHERE is_valid_order = 1 AND is_delivered = 1 AND review_score IS NOT NULL
        """
    )
    table = pd.crosstab(df["is_late_delivery"], df["is_bad_review"]).reindex(
        index=[0, 1], columns=[0, 1], fill_value=0
    )
    result = inference.chi_square_test(table.to_numpy())
    late_rate = float(table.loc[1, 1] / table.loc[1].sum())
    on_time_rate = float(table.loc[0, 1] / table.loc[0].sum())
    odds_ratio = float(
        (table.loc[1, 1] * table.loc[0, 0]) / (table.loc[1, 0] * table.loc[0, 1])
    )
    result.update(
        {
            "bad_review_rate_on_time": on_time_rate,
            "bad_review_rate_late": late_rate,
            "risk_ratio": late_rate / on_time_rate if on_time_rate else float("nan"),
            "odds_ratio": odds_ratio,
            "table": table,
        }
    )
    return result


def summary() -> Dict[str, object]:
    """汇总真实数据的统计描述，供报告与看板引用。"""
    sampling = sample_distribution_state_means()
    ci_table = state_mean_ci()
    stratified = late_vs_ontime_by_state()
    chi = late_review_chi_square()
    return {
        "sampling": sampling,
        "state_ci": ci_table,
        "stratified": stratified,
        "chi_square": chi,
    }
