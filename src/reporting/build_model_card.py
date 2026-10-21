"""生成 reports/model_card.md：汇总四个模型卡的用途、数据、指标、限制与不使用场景。

用法：python -m src.reporting.build_model_card
依赖阶段 3 的模型产物（models/artifacts/*.json）。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd

from src import config


def _load(name: str) -> Dict[str, object]:
    path = config.MODEL_DIR / name
    if not path.exists():
        raise FileNotFoundError("缺少模型产物 %s，请先运行对应模块" % path)
    return json.loads(path.read_text(encoding="utf-8"))


def _f(v: float, digits: int = 3) -> str:
    return "%.*f" % (digits, float(v))


def _pct(v: float, digits: int = 2) -> str:
    return "%.*f%%" % (digits, float(v) * 100)


def _money(v: float) -> str:
    return "R$ %s" % format(int(round(float(v))), ",")


def _table(df: pd.DataFrame, columns: List[str], formats: Dict[str, object] | None = None) -> str:
    formats = formats or {}
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for _, row in df.iterrows():
        cells = []
        for column in columns:
            value = row[column]
            fmt = formats.get(column)
            try:
                cells.append(fmt(value) if fmt else str(value))
            except (TypeError, ValueError):
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _churn_section() -> List[str]:
    m = _load("churn_metrics.json")
    train, test = m["train"], m["test"]
    metrics = m["metrics"]
    rows = []
    for name in ["随机基线（先验概率）", "Recency 规则", "LogisticRegression", "RandomForest", "LightGBM"]:
        if name not in metrics:
            continue
        value = metrics[name]
        rows.append(
            {
                "model": name,
                "pr_auc": value["pr_auc"],
                "roc_auc": value["roc_auc"],
                "brier": value["brier"],
                "lift": value["lift_at_10pct"],
                "recall": value["top10_recall"],
            }
        )
    comparison = pd.DataFrame(rows)

    importance = pd.read_csv(config.MODEL_DIR / "churn_feature_importance.csv").head(10)
    calibration = pd.read_csv(config.MODEL_DIR / "churn_calibration.csv")
    error = pd.read_csv(config.MODEL_DIR / "churn_error_analysis.csv")
    error = error[error["dimension"].isin(["recency_bucket", "order_bucket"])].copy()

    unseen = m["unseen_customers"]
    lines = [
        "## 1. 流失风险 / 复购倾向模型",
        "",
        "| 项目 | 说明 |",
        "| --- | --- |",
        "| 业务问题 | 未来 30 天哪些用户最可能复购？流失风险 = 1 − P(复购) |",
        "| 任务类型 | 二分类（稀有正类），时间外验证 |",
        "| 标签 | 快照后 30 天内是否有有效订单 |",
        "| 训练数据 | %s ~ %s，%s 行 / %s 位用户，正类 %s"
        % (train["snapshot_range"][0], train["snapshot_range"][1],
           "{:,}".format(train["rows"]), "{:,}".format(train["customers"]),
           _pct(train["positive_rate"], 3)),
        "| 测试数据 | %s ~ %s，%s 行 / %s 位用户，正类 %s"
        % (test["snapshot_range"][0], test["snapshot_range"][1],
           "{:,}".format(test["rows"]), "{:,}".format(test["customers"]),
           _pct(test["positive_rate"], 3)),
        "| 特征 | 过去 90 天订单/收入/评价/配送/分期/多品类 + 生命周期单量 + 州 |",
        "| 防泄漏 | 特征只用快照前数据，标签只用快照后 30 天；流水线内含泄漏断言 |",
        "| 最优模型 | **%s** |" % m["chosen_model"],
        "",
        "模型对比（测试集）：",
        "",
        _table(
            comparison,
            ["model", "pr_auc", "roc_auc", "brier", "lift", "recall"],
            {"pr_auc": _f, "roc_auc": _f, "brier": _f, "lift": lambda v: "%.2fx" % v, "recall": lambda v: _pct(v, 1)},
        ),
        "",
        "top-decile lift 表示：按模型挑出预测复购概率最高的 10% 用户，其实际复购率是随机挑选的多少倍；",
        "在正类仅 %s 的情况下，排序能力比 accuracy 更有业务意义。" % _pct(test["positive_rate"], 3),
        "客户不重叠子集（测试集中从未在训练集出现的用户）PR-AUC = %s，ROC-AUC = %s，"
        % (_f(unseen["pr_auc"]), _f(unseen["roc_auc"])),
        "说明模型并非只靠记住老客户。",
        "",
        "校准质量：ECE = %s（按预测概率十分位分箱，越低越好）。" % _f(m["calibration_ece"]),
        "",
        _table(
            calibration,
            ["n", "mean_predicted", "observed_rate", "abs_gap"],
            {"n": lambda v: "{:,.0f}".format(v), "mean_predicted": _f, "observed_rate": _f, "abs_gap": _f},
        ),
        "",
        "主要特征（LightGBM 重要性占比）：",
        "",
        _table(
            importance,
            ["feature", "importance_share"],
            {"importance_share": lambda v: _pct(v, 1)},
        ),
        "",
        "错误分析（按最近购买时间 / 历史单量）：",
        "",
        _table(
            error,
            ["dimension", "group", "n", "positives", "actual_rate", "mean_predicted", "pr_auc"],
            {"n": lambda v: "{:,.0f}".format(v), "actual_rate": lambda v: _pct(v, 2),
             "mean_predicted": _f, "pr_auc": _f},
        ),
        "",
        "**限制与不使用场景**：",
        "",
        "- 正类极稀有（约 0.4%），PR-AUC 绝对值不高；模型适合**排序**（挑出高潜复购用户），不适合承诺个体概率。",
        "- Olist 约 97% 用户只买一次，复购行为本身稀疏；结论不能外推到高频复购型电商。",
        "- 同一用户会在不同快照重复出现，时间切分下测试集与训练集可能有重叠用户；已用「不重叠子集」做稳健性检查。",
        "- 模型只使用交易行为，未接入营销触达、浏览、客服等数据；**不能**用于「发券给谁会一定复购」的因果决策。",
        "- 最新快照打分只代表当前数据窗口，部署后需要按月重训并监控特征漂移。",
        "",
    ]
    return lines


def _segmentation_section() -> List[str]:
    m = _load("segmentation_metrics.json")
    profiles = pd.DataFrame(m["profiles"]).sort_values("revenue_share", ascending=False)
    stab = m["stability"]
    lines = [
        "## 2. 客户分群（RFM + K-Means）",
        "",
        "| 项目 | 说明 |",
        "| --- | --- |",
        "| 业务问题 | 客户可以分成哪些可运营的群体？各群体贡献多少收入？ |",
        "| 数据 | analytics_rfm，%s 位有有效订单的客户 |" % "{:,}".format(m["n_customers"]),
        "| 特征 | RFM 的百分位秩（对极端消费额稳健） |",
        "| 聚类数 | k=%d（轮廓系数 %s） |" % (m["chosen_k"], _f(m["silhouette"])),
        "| 稳定性 | bootstrap ARI %s ± %s，多种子 ARI 最低 %s |"
        % (_f(stab["bootstrap_ari_mean"]), _f(stab["bootstrap_ari_std"]), _f(stab["seed_ari_min"])),
        "",
        _table(
            profiles,
            ["cluster_name", "customers", "customer_share", "revenue_share",
             "avg_recency_days", "avg_frequency", "share_repeat", "avg_monetary"],
            {"customers": lambda v: "{:,.0f}".format(v), "customer_share": lambda v: _pct(v, 1),
             "revenue_share": lambda v: _pct(v, 1), "avg_recency_days": lambda v: "%.0f" % v,
             "avg_frequency": lambda v: "%.2f" % v, "share_repeat": lambda v: _pct(v, 1),
             "avg_monetary": _money},
        ),
        "",
        "**限制与不使用场景**：",
        "",
        "- frequency 在 Olist 上信息量很低（97% 单次购买），分群主要由最近购买时间与消费额驱动。",
        "- K-Means 假设簇近似球形且规模相近；轮廓系数 %s 属于中等可分性，不代表存在「天然」客群。" % _f(m["silhouette"]),
        "- 分群是描述性的，不能解释为「该群体对营销更敏感」；要回答敏感度必须做实验。",
        "- 分群结果会随数据窗口变化，需固定口径并定期重跑。",
        "",
    ]
    return lines


def _recommender_section() -> List[str]:
    m = _load("recommendation_metrics.json")
    evaluation = m["evaluation"]
    rows = []
    for k in (5, 10, 20):
        key = "k=%d" % k
        rows.append(
            {
                "k": k,
                "pop_recall": evaluation["metrics"]["popularity"][key]["recall"],
                "pop_ndcg": evaluation["metrics"]["popularity"][key]["ndcg"],
                "pop_coverage": evaluation["metrics"]["popularity"][key]["coverage"],
                "cf_recall": evaluation["metrics"]["item_item"][key]["recall"],
                "cf_ndcg": evaluation["metrics"]["item_item"][key]["ndcg"],
                "cf_coverage": evaluation["metrics"]["item_item"][key]["coverage"],
            }
        )
    table = pd.DataFrame(rows)
    lines = [
        "## 3. 商品推荐（热门基线 + item-item 协同过滤）",
        "",
        "| 项目 | 说明 |",
        "| --- | --- |",
        "| 业务问题 | 给有过购买记录的用户推荐哪些商品？ |",
        "| 数据 | 订单商品明细（购买行为），训练 < %s，测试 ≥ %s |" % (m["test_period"][0], m["test_period"][0]),
        "| 可推荐目录 | 训练期最热门的 %s 个商品 |" % "{:,}".format(m["catalog_size"]),
        "| 评估用户 | %s 位 warm 用户（训练期与测试期都购买过） |" % "{:,}".format(evaluation["n_warm_users"]),
        "| 冷启动占比 | %s（测试期有购买但训练期无购买） |" % _pct(evaluation["cold_start_share"], 1),
        "",
        "评估结果：",
        "",
        _table(
            table,
            ["k", "pop_recall", "pop_ndcg", "pop_coverage", "cf_recall", "cf_ndcg", "cf_coverage"],
            {"pop_recall": _f, "pop_ndcg": _f, "pop_coverage": lambda v: _pct(v, 1),
             "cf_recall": _f, "cf_ndcg": _f, "cf_coverage": lambda v: _pct(v, 1),
             "k": lambda v: "%d" % int(v)},
        ),
        "",
        "**限制与不使用场景**：",
        "",
        "- Olist 没有曝光/点击/浏览日志，这是**基于购买行为**的推荐，不是完整的点击推荐系统，不能评估 CTR。",
        "- 推荐目录只覆盖热门商品，Recall@K 的分母包含全部测试购买商品，指标偏保守。",
        "- 冷启动用户占比 %s，实际系统必须配合热门/内容策略，不能只依赖协同过滤。" % _pct(evaluation["cold_start_share"], 1),
        "- 协同过滤学到的是共现关系，不是「买 A 导致买 B」；不能用于因果归因。",
        "",
    ]
    return lines


def _forecast_section() -> List[str]:
    m = _load("forecast_metrics.json")
    rows = []
    for target, label in (("orders", "订单量"), ("revenue", "收入")):
        result = m["targets"][target]
        for model, value in result["metrics"].items():
            rows.append(
                {
                    "target": label,
                    "model": model,
                    "mae": value["mae"],
                    "rmse": value["rmse"],
                    "mape": value["mape"],
                    "best": "是" if model == result["best_model"] else "",
                }
            )
    table = pd.DataFrame(rows)
    orders = m["targets"]["orders"]
    revenue = m["targets"]["revenue"]
    lines = [
        "## 4. 时间序列预测（未来 30 天）",
        "",
        "| 项目 | 说明 |",
        "| --- | --- |",
        "| 业务问题 | 未来 30 天订单量与收入大概是多少？ |",
        "| 数据 | 日粒度，%s ~ %s |" % (m["train_period"][0], m["train_period"][1]),
        "| 验证 | 滚动原点 %s，每次预测 %d 天 |" % ("、".join(m["rolling_origins"]), m["horizon_days"]),
        "| 模型 | Seasonal Naive、SARIMA(1,1,1)(1,0,1,7)、LightGBM |",
        "",
        _table(
            table,
            ["target", "model", "mae", "rmse", "mape", "best"],
            {"mae": lambda v: "{:,.0f}".format(v), "rmse": lambda v: "{:,.0f}".format(v),
             "mape": lambda v: _pct(v, 1)},
        ),
        "",
        "- 订单量：最优 **%s**，未来 30 天预计 **%s** 单（日均 %.0f）。"
        % (orders["best_model"], "{:,.0f}".format(orders["forecast_total"]), orders["forecast_mean"]),
        "- 收入：最优 **%s**，未来 30 天预计 **%s**（日均 %s）。"
        % (revenue["best_model"], _money(revenue["forecast_total"]), _money(revenue["forecast_mean"])),
        "",
        "**限制与不使用场景**：",
        "",
        "- 数据只覆盖约两年，且 2018-08-23 之后采集不完整（已截断），长期趋势无法可靠外推。",
        "- 2017-11 Black Friday 是未建模的异常峰值，会抬高验证误差；预测区间来自残差分位数，不是保证。",
        "- 日粒度噪声大（MAPE 偏高），适合运营排期与容量参考，不适合财务承诺。",
        "- 模型未纳入促销日历、价格、流量投放等外生变量；有促销计划时应做情景调整。",
        "",
    ]
    return lines


def build() -> Path:
    sections: List[str] = [
        "# 模型卡（Model Card）",
        "",
        "- 生成时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "- 项目：Commerce Intelligence Platform（Olist 公开电商数据）",
        "- 复现：`python -m src.models.churn`、`python -m src.models.segmentation`、"
        "`python -m src.models.recommender`、`python -m src.models.forecasting`、"
        "`python -m src.reporting.build_model_card`",
        "",
        "> 这份模型卡回答三个问题：模型解决什么业务问题、在什么数据上验证、**不能**用来做什么。",
        "> Olist 是观测数据，除模拟 A/B 实验外，本项目的模型结论都是相关性/预测性的，不做因果声明。",
        "",
    ]
    sections += _churn_section()
    sections += _segmentation_section()
    sections += _recommender_section()
    sections += _forecast_section()
    sections += [
        "## 5. 模拟 A/B 实验（独立模块）",
        "",
        "实验设计与统计检验不构成一个预测模型，单独记录在 `reports/experiment_report.md`。",
        "其随机分组结论来自模拟数据，**不能**与以上真实观测模型的结果混用。",
        "",
        "## 6. 跨模型通用限制",
        "",
        "1. **数据来源**：Olist 是历史交易数据，缺少曝光、点击、营销触达、客服等关键行为；所有模型都存在未观测混杂。",
        "2. **时间边界**：训练/验证按时间切分，但数据仅约两年；跨年度、跨市场的泛化未经验证。",
        "3. **指标解释**：稀有事件用 PR-AUC / lift，回归用 MAE/RMSE，均值差异用置信区间与效应量；单一 accuracy 或 p 值不足以支撑决策。",
        "4. **监控要求**：上线后需要监控输入特征分布（漂移）、预测分布和实际效果，按月重训；本项目阶段 4 将补充监控与 API。",
        "5. **不使用场景**：个体层面的因果决策、法律/信贷/医疗等高风险决策、对外承诺的财务预测。",
        "",
    ]
    path = config.REPORTS_DIR / "model_card.md"
    path.write_text("\n".join(sections) + "\n", encoding="utf-8")
    print("  模型卡 → %s" % path)
    return path


def main() -> int:
    build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
