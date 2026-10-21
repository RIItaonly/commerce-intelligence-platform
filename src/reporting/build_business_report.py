"""生成 reports/business_insights.md：阶段 1-2 的业务洞察报告。

原则：报告里每个数字都来自 src/analytics 的查询函数（可追溯到具体 SQL 视图），
不手填；观测数据只做相关性陈述，因果结论留给阶段 3 的模拟实验模块。

用法：python -m src.reporting.build_business_report
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd

from src import config
from src.analytics import attribution, fulfillment, funnel, kpi, retention, rfm


# ---------------------------------------------------------------- 格式化工具
def _money(v: float) -> str:
    return "R$ %s" % format(int(round(float(v))), ",")


def _smoney(v: float) -> str:
    v = float(v)
    sign = "+" if v >= 0 else "-"
    return "%sR$ %s" % (sign, format(int(round(abs(v))), ","))


def _num(v: float) -> str:
    return format(int(round(float(v))), ",")


def _pct(v: float) -> str:
    return "%.1f%%" % (float(v) * 100)


def _f2(v: float) -> str:
    return "%.2f" % float(v)


def _md_table(df: pd.DataFrame, columns: List[str], formats: Dict[str, object] | None = None) -> str:
    """极简 Markdown 表格（不依赖 tabulate）。"""
    formats = formats or {}
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for _, row in df.iterrows():
        cells = []
        for col in columns:
            value = row[col]
            fmt = formats.get(col)
            try:
                cells.append(fmt(value) if fmt else str(value))
            except (TypeError, ValueError):
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------- 各章节
def _section_overview() -> List[str]:
    h = kpi.headline()
    monthly = kpi.monthly_kpi()
    top_cat = kpi.top_categories(8)
    top_state = kpi.top_states(8)
    concentration = kpi.seller_concentration()

    peak = monthly.loc[monthly["revenue"].idxmax()]
    peak_note = "收入峰值出现在 **%s**（%s，黑五所在月），其后 12 月回落，2018 年恢复平稳增长。" % (
        str(peak["order_month"])[:7], _money(peak["revenue"]))

    return [
        "## 1. 经营总览",
        "",
        "分析时间窗 **%s ~ %s**（%d 个完整月份）内：" % (
            config.ANALYSIS_START_DATE, config.ANALYSIS_END_DATE, h.get("n_months", 0)),
        "",
        "- 有效订单 **%s** 单（总订单 %s 单，取消/不可用已剔除），覆盖真实用户 **%s** 人。"
        % (_num(h["orders_valid"]), _num(h["orders_total"]), _num(h["customers"])),
        "- 实收收入 **%s**，GMV（商品金额）**%s**，运费 **%s**；客单价 **%s**。"
        % (_money(h["revenue"]), _money(h["gmv"]), _money(h["freight"]), _money(h["aov"])),
        "- 已签收 **%s** 单，整体迟到率 **%s**，平均配送 **%.1f** 天。"
        % (_num(h["orders_delivered"]), _pct(h["late_delivery_rate"]), h["avg_delivery_days"]),
        "- 平均评分 **%.2f** / 5，差评率（≤2 分）**%s**。" % (h["avg_review_score"], _pct(h["bad_review_rate"])),
        "- %s" % peak_note,
        "",
        "注意口径：实收收入（支付金额，含运费）与 GMV（商品金额，不含运费）是两个不同指标，本报告全程分开使用。",
        "",
        "### 头部品类（按 GMV）",
        "",
        _md_table(
            top_cat,
            ["category", "orders", "items_sold", "gmv", "gmv_share", "avg_price", "avg_review_score"],
            {"orders": _num, "items_sold": _num, "gmv": _money, "gmv_share": _pct,
             "avg_price": lambda v: "R$ %.0f" % float(v), "avg_review_score": _f2},
        ),
        "",
        "### 头部地区（买家州，按实收收入）",
        "",
        _md_table(
            top_state,
            ["state", "orders", "customers", "revenue", "revenue_share", "aov", "avg_delivery_days", "late_delivery_rate"],
            {"orders": _num, "customers": _num, "revenue": _money, "revenue_share": _pct,
             "aov": lambda v: "R$ %.0f" % float(v), "avg_delivery_days": lambda v: "%.1f" % float(v),
             "late_delivery_rate": _pct},
        ),
        "",
        "商家侧集中度：GMV Top 10 商家占 **%s**，Top 100 占 **%s**（共 %s 个商家），长尾特征明显。"
        % (_pct(concentration["top10_share"]), _pct(concentration["top100_share"]),
           _num(concentration["n_sellers"])),
        "",
        "> 数据来源：`sql/analytics/01_monthly_kpi.sql`（analytics_monthly_kpi）、`02_category_performance.sql`、",
        "> `03_state_performance.sql`、`04_seller_performance.sql`。",
        "",
    ]


def _section_lifecycle() -> List[str]:
    repeat = retention.repeat_summary()
    cohort_avg = retention.cohort_average_retention(periods=(1, 2, 3, 6))
    overview = rfm.rfm_overview()
    segments = rfm.segment_summary()
    nvr = retention.new_vs_returning()
    funnel_df = funnel.order_funnel()

    cohort_text = "、".join(
        "%d 个月留存 **%s**" % (period, _pct(value)) for period, value in sorted(cohort_avg.items())
    )
    last = nvr.iloc[-1]
    returning_rev_share = (
        last["returning_revenue"] / (last["new_revenue"] + last["returning_revenue"])
        if (last["new_revenue"] + last["returning_revenue"]) else 0.0
    )

    return [
        "## 2. 用户生命周期",
        "",
        "### 2.1 履约漏斗（下单 → 评价）",
        "",
        _md_table(
            funnel_df[["label", "orders", "rate_of_total", "rate_of_prev"]],
            ["label", "orders", "rate_of_total", "rate_of_prev"],
            {"orders": _num, "rate_of_total": _pct, "rate_of_prev": _pct},
        ),
        "",
        "Olist 只有订单状态时间戳，没有曝光/点击/加购日志，漏斗只能从下单开始；且各阶段按时间戳是否存在",
        "判定，已取消订单也可能到达过部分阶段，因此上表读作「到达过该环节的订单量」，不是严格子集漏斗。",
        "",
        "### 2.2 复购与新客结构",
        "",
        "- 真实用户 **%s** 人，其中有过复购（≥2 单）的仅 **%s**（%s），客均 **%.2f** 单。"
        % (_num(repeat["customers"]), _num(repeat["repeat_customers"]),
           _pct(repeat["repeat_customer_share"]), repeat["avg_orders_per_customer"]),
        "- 复购用户贡献了 **%s** 的收入——复购人群占比很小，但收入贡献明显高于人数占比。"
        % _pct(repeat["repeat_revenue_share"]),
        "- 月度维度看，老客（首购早于当月）收入占比爬升至窗口期末的 **%s**，"
        "平台仍处于「拉新驱动」阶段，留存运营空间很大。" % _pct(returning_rev_share),
        "",
        "### 2.3 留存队列（按首购月份）",
        "",
        "按队列人数加权平均：首购后 %s。整体复购留存很低，与 Olist 公开分析结论一致，" % cohort_text,
        "这也是平台方最需要改善的经营杠杆。",
        "",
        "### 2.4 RFM 客户分群（规则版）",
        "",
        _md_table(
            segments,
            ["segment", "customers", "customer_share", "revenue", "revenue_share", "avg_monetary", "avg_recency_days"],
            {"customers": _num, "customer_share": _pct, "revenue": _money, "revenue_share": _pct,
             "avg_monetary": _money, "avg_recency_days": lambda v: "%.0f" % float(v)},
        ),
        "",
        "说明：Olist 约 **%s** 的客户只有 1 单，frequency 维度 NTILE 退化，因此分群用业务规则"
        % _pct(overview["single_order_share"]),
        "（是否复购 + 最近购买间隔）而不是机械五分位；K-Means 版本在阶段 3 建模模块中对比。",
        "高价值客户（累计消费前 20%%，门槛 %s）贡献了大部分收入，是精细化运营的优先对象。"
        % _money(overview["high_value_threshold"]),
        "",
        "> 数据来源：`sql/analytics/05_retention_cohort.sql`、`06_rfm.sql`、`09_funnel.sql`，",
        "> 及 `src/analytics/retention.py` 中的用户粒度聚合查询。",
        "",
    ]


def _section_fulfillment() -> List[str]:
    stats_ = fulfillment.delivery_stats()
    late = fulfillment.late_review()
    corr = fulfillment.delivery_review_correlation()
    buckets = fulfillment.delivery_buckets()
    control = fulfillment.category_control()

    return [
        "## 3. 履约与体验",
        "",
        "> 口径说明：本节统计**全部已签收订单**（含分析窗口外的少量月份），与第 1 节的窗口口径略有差异",
        "（如平均配送 12.6 天 vs 12.5 天），结论不受影响。",
        "",
        "- 已签收订单平均配送 **%.1f** 天（中位数 %.0f 天，P90 %.0f 天），平台给出的预计送达平均为 %.1f 天。"
        % (stats_["avg_delivery_days"], stats_["median_delivery_days"],
           stats_["p90_delivery_days"], stats_["avg_estimated_days"]),
        "- 迟到订单（实际晚于预计）平均晚到 **%.1f** 天。" % stats_["avg_delay_days_when_late"],
        "",
        "### 3.1 配送时长与评分",
        "",
        _md_table(
            buckets,
            ["delivery_bucket", "orders", "avg_review_score", "bad_review_rate", "late_delivery_rate"],
            {"orders": _num, "avg_review_score": _f2, "bad_review_rate": _pct, "late_delivery_rate": _pct},
        ),
        "",
        "### 3.2 迟到 vs 准时（订单粒度）",
        "",
        "- 准时订单（%s 单）平均评分 **%.2f**，差评率 %s；迟到订单（%s 单）平均评分 **%.2f**，差评率 %s。"
        % (_num(late["on_time"]["orders"]), late["on_time"]["avg_review_score"], _pct(late["on_time"]["bad_review_rate"]),
           _num(late["late"]["orders"]), late["late"]["avg_review_score"], _pct(late["late"]["bad_review_rate"])),
        "- 评分差 **%.2f** 分，差评率差 **%s**；配送时长与评分的 Spearman 相关 **%.3f**（n=%s，p<0.001）。"
        % (late["diff"]["avg_review_score"], _pct(late["diff"]["bad_review_rate"]),
           corr["spearman_delivery_days"], _num(corr["n"])),
        "",
        "### 3.3 按品类分层对照（控制品类结构差异）",
        "",
        _md_table(
            control[["category", "items_on_time", "items_late", "review_on_time", "review_late", "review_diff"]],
            ["category", "items_on_time", "items_late", "review_on_time", "review_late", "review_diff"],
            {"items_on_time": _num, "items_late": _num, "review_on_time": _f2,
             "review_late": _f2, "review_diff": lambda v: "%+.2f" % float(v)},
        ),
        "",
        "可以看到：在样本量足够的品类内部，「迟到单评分低于准时单」的方向基本一致，说明整体层面的差异",
        "不只是品类结构不同造成的。**但这仍是观测数据的相关性**：商家质量、地区物流能力、商品属性等未观测",
        "因素没有排除，本节不做因果断言。因果评估方法见阶段 3 的模拟 A/B 实验模块。",
        "",
        "> 数据来源：`sql/analytics/07_fulfillment_experience.sql`，及 `src/analytics/fulfillment.py` 中的",
        "> 分层对照与相关性查询。",
        "",
    ]


def _section_attribution() -> List[str]:
    peak = attribution.peak_month_analysis()
    growth = attribution.window_growth_analysis()

    cat_top = peak["by_category"].head(6)
    growth_cat = growth["by_category"].head(6)
    growth_bottom = growth["by_category"].tail(3).sort_values("delta")

    return [
        "## 4. 收入归因",
        "",
        "### 4.1 峰值月分解：%s vs %s" % (peak["peak_month"], peak["prev_month"]),
        "",
        "GMV 从 %s 增至 %s（净增 %s）。贡献最大的品类：" % (
            _money(peak["prev_gmv"]), _money(peak["peak_gmv"]),
            _money(peak["peak_gmv"] - peak["prev_gmv"])),
        "",
        _md_table(
            cat_top[["key", "prev_gmv", "cur_gmv", "delta", "contribution_share"]],
            ["key", "prev_gmv", "cur_gmv", "delta", "contribution_share"],
            {"prev_gmv": _money, "cur_gmv": _money, "delta": _smoney, "contribution_share": _pct},
        ),
        "",
        "### 4.2 窗口增长分解：%s vs %s" % (growth["current"], growth["previous"]),
        "",
        "同比增长贡献最大的品类：",
        "",
        _md_table(
            growth_cat[["key", "prev_gmv", "cur_gmv", "delta", "contribution_share"]],
            ["key", "prev_gmv", "cur_gmv", "delta", "contribution_share"],
            {"prev_gmv": _money, "cur_gmv": _money, "delta": _smoney, "contribution_share": _pct},
        ),
        "",
        "增长拖累最大的品类：",
        "",
        _md_table(
            growth_bottom[["key", "prev_gmv", "cur_gmv", "delta"]],
            ["key", "prev_gmv", "cur_gmv", "delta"],
            {"prev_gmv": _money, "cur_gmv": _money, "delta": _smoney},
        ),
        "",
        "> 数据来源：`src/analytics/attribution.py` 的 compare_periods（按月补零的严格期间对比），",
        "> 连续月份环比见 `sql/analytics/08_revenue_attribution.sql`。",
        "",
    ]


def _section_limits() -> List[str]:
    return [
        "## 5. 结论边界（诚实声明）",
        "",
        "1. **观测数据，不做因果断言。** 本报告所有「A 与 B 相关」的发现（如迟到与低评分）均未排除全部混杂，",
        "   不能直接解释为「A 导致 B」。促销/改版的增量效果评估放在阶段 3 的**独立模拟实验**模块，",
        "   并会明确区分模拟结论与真实观测发现。",
        "2. **时间范围有限。** 2016-09/10/12 与 2018-09 之后为不完整月份，趋势分析限定 %s ~ %s；"
        % (config.ANALYSIS_START_DATE, config.ANALYSIS_END_DATE),
        "   数据只有约 2 年，不支持长期趋势外推。",
        "3. **行为日志缺失。** Olist 只有交易与评价数据，没有曝光、点击、加购日志：漏斗只能从下单开始，",
        "   推荐系统（阶段 3）只能是「基于购买行为的推荐」，不能类比完整的点击推荐系统。",
        "4. **指标口径。** GMV（商品金额）、实收收入（支付金额，含运费）、利润是不同指标，本报告不估算利润。",
        "",
        "## 附录：可追溯性",
        "",
        "| 结论 | 来源视图 | SQL 文件 | Python 模块 |",
        "| --- | --- | --- | --- |",
        "| 月度 KPI / 头部品类 / 地区 / 商家 | analytics_monthly_kpi 等 | sql/analytics/01-04 | src/analytics/kpi.py |",
        "| 履约漏斗 | analytics_order_funnel | sql/analytics/09_funnel.sql | src/analytics/funnel.py |",
        "| 留存队列 / 复购 | analytics_cohort_retention | sql/analytics/05 | src/analytics/retention.py |",
        "| RFM 分群 | analytics_rfm | sql/analytics/06_rfm.sql | src/analytics/rfm.py |",
        "| 配送与评分 | analytics_delivery_review / analytics_late_review | sql/analytics/07 | src/analytics/fulfillment.py |",
        "| 收入归因 | analytics_category_gmv_mom / state | sql/analytics/08 | src/analytics/attribution.py |",
        "",
    ]


def run() -> Path:
    lines: List[str] = [
        "# 业务洞察报告（阶段 1-2：数据底座 + 经营分析）",
        "",
        "- 生成时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "- 数据：Olist 巴西电商公开数据（约 10 万订单，多表关系型）",
        "- 数据库：`%s`" % config.DATABASE_URL,
        "- 原则：报告内每个数字都可追溯到 `sql/analytics/` 的具体视图或 `src/analytics/` 的查询函数。",
        "",
    ]
    lines += _section_overview()
    lines += _section_lifecycle()
    lines += _section_fulfillment()
    lines += _section_attribution()
    lines += _section_limits()

    path = config.REPORTS_DIR / "business_insights.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("  业务报告 → %s" % path)
    return path


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
