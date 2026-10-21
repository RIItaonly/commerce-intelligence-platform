"""实验分析：随机化检查、主指标检验、异质性、护栏、功效与业务价值。"""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd
from scipy import stats

from src import sql_engine
from src.statistics import inference


def _split(df: pd.DataFrame):
    control = df.loc[df["group"] == "control"]
    treatment = df.loc[df["group"] == "treatment"]
    return control, treatment


def randomization_checks(df: pd.DataFrame) -> Dict[str, object]:
    """SRM（样本比例失衡）与协变量平衡性检查。"""
    counts = df["group"].value_counts().reindex(["control", "treatment"], fill_value=0)
    expected = np.array([len(df) / 2, len(df) / 2])
    chi2, p_value = stats.chisquare(counts.to_numpy(dtype=float), expected)

    control, treatment = _split(df)
    balance_rows: List[Dict[str, float]] = []
    for column, label in [
        ("prior_orders_90d", "实验前 90 天订单数"),
        ("prior_spend_90d", "实验前 90 天消费额"),
    ]:
        smd = inference.standardized_mean_diff(
            control[column].to_numpy(dtype=float), treatment[column].to_numpy(dtype=float)
        )
        balance_rows.append(
            {
                "covariate": label,
                "control_mean": float(control[column].mean()),
                "treatment_mean": float(treatment[column].mean()),
                "smd": smd,
                "balanced": abs(smd) < 0.1,
            }
        )
    return {
        "n_control": int(counts["control"]),
        "n_treatment": int(counts["treatment"]),
        "control_share": float(counts["control"] / len(df)),
        "srm_chi2": float(chi2),
        "srm_p_value": float(p_value),
        "balance": pd.DataFrame(balance_rows),
    }


def primary_analysis(df: pd.DataFrame, confidence: float = 0.95) -> Dict[str, object]:
    """主指标（转化率）与次要指标（ARPU、购买者客单价）分析。"""
    control, treatment = _split(df)
    c_conv = int(control["converted"].sum())
    t_conv = int(treatment["converted"].sum())
    conversion = inference.two_proportion_test(
        c_conv, len(control), t_conv, len(treatment), confidence=confidence
    )
    conversion["ci_control"] = inference.proportion_ci(c_conv, len(control), confidence)
    conversion["ci_treatment"] = inference.proportion_ci(t_conv, len(treatment), confidence)

    arpu = inference.welch_ttest(
        control["revenue"].to_numpy(dtype=float),
        treatment["revenue"].to_numpy(dtype=float),
        confidence=confidence,
    )
    aov = inference.welch_ttest(
        control.loc[control["converted"] == 1, "revenue"].to_numpy(dtype=float),
        treatment.loc[treatment["converted"] == 1, "revenue"].to_numpy(dtype=float),
        confidence=confidence,
    )
    return {"conversion": conversion, "arpu": arpu, "aov": aov}


def guardrails(df: pd.DataFrame, confidence: float = 0.95) -> pd.DataFrame:
    """护栏指标：方向为「越低越好」，关注是否出现不可接受的恶化。"""
    control, treatment = _split(df)
    rows = []
    for column, label in [("refunded", "退款率"), ("complained", "投诉率")]:
        test = inference.two_proportion_test(
            int(control[column].sum()), len(control),
            int(treatment[column].sum()), len(treatment),
            confidence=confidence,
        )
        rows.append(
            {
                "metric": label,
                "control_rate": test["rate_a"],
                "treatment_rate": test["rate_b"],
                "diff": test["diff"],
                "ci_low": test["ci_low"],
                "ci_high": test["ci_high"],
                "p_value": test["p_value"],
                "relative_lift": test["relative_lift"],
            }
        )
    return pd.DataFrame(rows)


def heterogeneity(df: pd.DataFrame, by: str = "region", confidence: float = 0.95) -> pd.DataFrame:
    """分组异质性分析 + BH 多重检验校正。

    探索多个分组时，不做校正会显著抬高假阳性率：即使真实没有差异，
    5 个分组里至少 1 个 p<0.05 的概率约为 23%。这里同时输出原始 p 与校正后 p。
    """
    rows = []
    for name, group in df.groupby(by):
        control = group[group["group"] == "control"]
        treatment = group[group["group"] == "treatment"]
        if len(control) < 30 or len(treatment) < 30:
            continue
        test = inference.two_proportion_test(
            int(control["converted"].sum()), len(control),
            int(treatment["converted"].sum()), len(treatment),
            confidence=confidence,
        )
        rows.append(
            {
                "group": name,
                "n_control": test["n_a"],
                "n_treatment": test["n_b"],
                "control_rate": test["rate_a"],
                "treatment_rate": test["rate_b"],
                "diff": test["diff"],
                "relative_lift": test["relative_lift"],
                "ci_low": test["ci_low"],
                "ci_high": test["ci_high"],
                "p_value": test["p_value"],
            }
        )
    table = pd.DataFrame(rows).sort_values("diff", ascending=False).reset_index(drop=True)
    adjusted = inference.adjust_pvalues(table["p_value"].tolist(), method="bh")
    table["p_adjusted"] = adjusted["adjusted"]
    table["significant_raw"] = table["p_value"] < 0.05
    table["significant_bh"] = adjusted["rejected"]
    return table


def power_analysis(df: pd.DataFrame) -> Dict[str, object]:
    """事前样本量测算 + 事后功效。

    事前：在基线转化率约 3.2% 时，要检测不同绝对提升所需的每组样本量。
    事后：用观察到的效应量，计算当前样本量下的统计功效（post-hoc power 只作参考，
    不能替代事前设计）。
    """
    control, treatment = _split(df)
    baseline = float(control["converted"].mean())
    observed_effect = float(treatment["converted"].mean() - baseline)

    rows = []
    for mde in (0.002, 0.003, 0.004, 0.005):
        result = inference.required_sample_size_proportion(baseline, baseline + mde)
        rows.append(
            {
                "mde_absolute": mde,
                "mde_relative": mde / baseline,
                "n_per_group": result["n_per_group"],
                "n_total": result["n_total"],
                "cohens_h": result["cohens_h"],
            }
        )
    achieved = inference.achieved_power_proportion(
        baseline, baseline + max(observed_effect, 1e-6), len(treatment)
    )
    return {
        "baseline_rate": baseline,
        "observed_effect": observed_effect,
        "table": pd.DataFrame(rows),
        "achieved_power": float(achieved),
    }


def business_value(df: pd.DataFrame, monthly_traffic: int = 100_000) -> Dict[str, float]:
    """把统计效应换算成业务价值（模拟场景，单位：巴西雷亚尔）。"""
    control, treatment = _split(df)
    arpu_lift = float(treatment["revenue"].mean() - control["revenue"].mean())
    conv_lift = float(treatment["converted"].mean() - control["converted"].mean())
    return {
        "arpu_lift": arpu_lift,
        "conversion_lift": conv_lift,
        "incremental_revenue_per_user": arpu_lift,
        "incremental_revenue_per_100k": arpu_lift * monthly_traffic,
        "incremental_conversions_per_100k": conv_lift * monthly_traffic,
    }


def observed_contrast() -> Dict[str, object]:
    """真实观测数据对照：迟到 vs 准时的差评率差异。

    这是一个**统计显著但非因果**的例子：迟到订单的差评率远高于准时订单，
    但用户不是随机被分配到「迟到组」的，商家质量、地区物流等因素同时影响
    迟到与评分。把它放在实验报告里，是为了说明「显著」不等于「因果」。
    """
    df = sql_engine.read_sql(
        """
        SELECT
            is_late_delivery,
            COUNT(*) AS orders,
            SUM(COALESCE(is_bad_review, 0)) AS bad_reviews,
            AVG(review_score) AS avg_review
        FROM fct_order
        WHERE is_valid_order = 1 AND is_delivered = 1 AND review_score IS NOT NULL
        GROUP BY is_late_delivery
        """
    ).set_index("is_late_delivery")
    on_time = df.loc[0]
    late = df.loc[1]
    test = inference.two_proportion_test(
        int(on_time["bad_reviews"]), int(on_time["orders"]),
        int(late["bad_reviews"]), int(late["orders"]),
    )
    return {
        "n_on_time": int(on_time["orders"]),
        "n_late": int(late["orders"]),
        "bad_rate_on_time": float(on_time["bad_reviews"]) / float(on_time["orders"]),
        "bad_rate_late": float(late["bad_reviews"]) / float(late["orders"]),
        "avg_review_on_time": float(on_time["avg_review"]),
        "avg_review_late": float(late["avg_review"]),
        "diff_bad_rate": test["diff"],
        "relative_lift": test["relative_lift"],
        "p_value": test["p_value"],
        "ci_low": test["ci_low"],
        "ci_high": test["ci_high"],
        "cohens_h": test["cohens_h"],
    }
