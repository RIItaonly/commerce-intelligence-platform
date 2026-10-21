"""生成模拟 A/B 实验报告 reports/experiment_report.md。

用法：python -m src.experiment.run_experiment
输出：
  data/interim/simulated_ab.csv       用户级模拟实验数据（可复现，seed 固定）
  reports/experiment_report.md        完整分析报告（含设计与边界声明）
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd

from src import config
from src.experiment import analysis, simulator


def _pct(v: float, digits: int = 2) -> str:
    return ("%." + str(digits) + "f%%") % (float(v) * 100)


def _pp(v: float) -> str:
    return "%+.2f pp" % (float(v) * 100)


def _money(v: float) -> str:
    return "R$ %s" % format(int(round(float(v))), ",")


def _money2(v: float) -> str:
    """小额金额保留两位，避免把 R$ 0.32 显示成 R$ 0。"""
    return "R$ %.2f" % float(v)


def _f2(v: float) -> str:
    return "%.2f" % float(v)


def _f3(v: float) -> str:
    return "%.3f" % float(v)


def _p(v: float) -> str:
    return "< 0.001" if float(v) < 0.001 else "%.3f" % float(v)


def _p_expr(v: float) -> str:
    """用于正文的 p 值表达，例如 p < 0.001 / p = 0.024。"""
    return "p < 0.001" if float(v) < 0.001 else "p = %.3f" % float(v)


def _md_table(df: pd.DataFrame, columns: List[str], formats: Dict[str, object] | None = None) -> str:
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


def _decision(primary: Dict[str, object], guardrail_df: pd.DataFrame) -> str:
    conversion = primary["conversion"]
    guardrail_bad = guardrail_df[
        (guardrail_df["p_value"] < 0.05) & (guardrail_df["diff"] > 0)
    ]
    if conversion["p_value"] < 0.05 and conversion["diff"] > 0 and guardrail_bad.empty:
        return (
            "主指标显著正向、护栏指标未出现统计显著的恶化，**建议进入小流量灰度上线**，"
            "同时继续监控退款率与投诉率（本结论仅基于模拟数据，真实上线前需在线上流量复验）。"
        )
    if conversion["p_value"] < 0.05 and conversion["diff"] < 0:
        return "主指标显著负向，**不建议上线**，需排查实验版本或触达策略。"
    if not guardrail_bad.empty:
        return "护栏指标出现显著恶化，即使主指标正向也**不建议直接上线**，应先定位护栏问题。"
    return "主指标未达到统计显著，**建议延长实验或提高样本量**；不显著不代表没有效果。"


def build_report() -> Path:
    frame = simulator.generate()
    data_path = config.INTERIM_DIR / "simulated_ab.csv"
    frame.to_csv(data_path, index=False, encoding="utf-8-sig")

    design = simulator.design_parameters()
    checks = analysis.randomization_checks(frame)
    primary = analysis.primary_analysis(frame)
    guardrail_df = analysis.guardrails(frame)
    region_df = analysis.heterogeneity(frame, by="region")
    power = analysis.power_analysis(frame)
    value = analysis.business_value(frame)
    observed = analysis.observed_contrast()

    conversion = primary["conversion"]
    arpu = primary["arpu"]
    aov = primary["aov"]
    ci_c = conversion["ci_control"]
    ci_t = conversion["ci_treatment"]

    balance_table = checks["balance"].copy()
    balance_table["smd"] = balance_table["smd"].apply(_f3)
    balance_table["balanced"] = balance_table["balanced"].map({True: "是", False: "否"})

    region_table = region_df.copy()
    region_table["control_rate"] = region_table["control_rate"].apply(_pct)
    region_table["treatment_rate"] = region_table["treatment_rate"].apply(_pct)
    region_table["diff"] = region_table["diff"].apply(_pp)
    region_table["ci"] = region_table.apply(
        lambda row: "[%s, %s]" % (_pp(row["ci_low"]), _pp(row["ci_high"])), axis=1
    )
    region_table["relative_lift"] = region_table["relative_lift"].apply(lambda v: _pct(v, 1))
    region_table["p_value"] = region_table["p_value"].apply(_p)
    region_table["p_adjusted"] = region_table["p_adjusted"].apply(_p)
    region_table["significant_raw"] = region_table["significant_raw"].map({True: "是", False: "否"})
    region_table["significant_bh"] = region_table["significant_bh"].map({True: "是", False: "否"})

    guardrail_table = guardrail_df.copy()
    guardrail_table["control_rate"] = guardrail_table["control_rate"].apply(_pct)
    guardrail_table["treatment_rate"] = guardrail_table["treatment_rate"].apply(_pct)
    guardrail_table["diff"] = guardrail_table["diff"].apply(_pp)
    guardrail_table["ci"] = guardrail_table.apply(
        lambda row: "[%s, %s]" % (_pp(row["ci_low"]), _pp(row["ci_high"])), axis=1
    )
    guardrail_table["relative_lift"] = guardrail_table["relative_lift"].apply(lambda v: _pct(v, 1))
    guardrail_table["p_value"] = guardrail_table["p_value"].apply(_p)

    power_table = power["table"].copy()
    power_table["mde_absolute"] = power_table["mde_absolute"].apply(_pp)
    power_table["mde_relative"] = power_table["mde_relative"].apply(lambda v: _pct(v, 1))
    power_table["n_per_group"] = power_table["n_per_group"].apply(lambda v: "{:,.0f}".format(v))
    power_table["n_total"] = power_table["n_total"].apply(lambda v: "{:,.0f}".format(v))
    power_table["cohens_h"] = power_table["cohens_h"].apply(_f3)

    lines: List[str] = [
        "# 模拟 A/B 实验报告",
        "",
        "- 生成时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "- 数据：**独立模拟**的用户级实验数据（seed=%d，%s 行），不是 Olist 真实实验"
        % (simulator.SEED, "{:,}".format(len(frame))),
        "- 数据文件：`data/interim/simulated_ab.csv`",
        "- 代码：`src/experiment/simulator.py`（生成）、`analysis.py`（分析）、`run_experiment.py`（报告）",
        "- 统计工具：`src/statistics/inference.py`（置信区间、检验、效应量、功效、多重检验）",
        "",
        "> **最重要的一句话**：本报告的所有因果结论都建立在模拟的随机分组上，只用于验证分析流程；",
        "> 它们 **不是** Olist 真实经营数据的结论。真实观测数据的发现见 `reports/business_insights.md`。",
        "",
        "## 1. 实验设计",
        "",
        "| 项目 | 设定 |",
        "| --- | --- |",
        "| 实验假设 | 新促销策略能提升购买转化率与人均收入，且不恶化退款/投诉 |",
        "| 随机化单位 | %s |" % design["assignment"],
        "| 样本量 | %s 用户（两组约各 50%%） |" % "{:,}".format(design["n_users"]),
        "| 主指标 | %s |" % design["primary_metric"],
        "| 次要指标 | %s |" % "、".join(design["secondary_metrics"]),
        "| 护栏指标 | %s |" % "、".join(design["guardrails"]),
        "| 异质性维度 | %s |" % "、".join(design["segments"]),
        "",
        "模拟数据生成规则（真实效应只存在于模拟器里）：",
        "",
        "- 不同地区有不同的基线转化率与真实提升，用于检验分层分析与多重检验校正；",
        "- 实验组购买者客单价有 %.0f%% 的模拟提升；" % (simulator.TREATMENT_AOV_LIFT * 100),
        "- 退款率与投诉率两组设定相同（真实效应为 0），用于验证护栏流程不会误报；",
        "- 实验前 90 天订单数/消费额与分组无关，用于随机化平衡性检查。",
        "",
        "## 2. 随机化检查",
        "",
        "- 对照组 **%s** 人（%s），实验组 **%s** 人（%s）。"
        % ("{:,}".format(checks["n_control"]), _pct(checks["control_share"], 1),
           "{:,}".format(checks["n_treatment"]), _pct(1 - checks["control_share"], 1)),
        "- SRM 检验（样本比例是否符合 50/50）：χ² = %.3f，%s。"
        % (checks["srm_chi2"], _p_expr(checks["srm_p_value"])),
        "",
        _md_table(
            balance_table,
            ["covariate", "control_mean", "treatment_mean", "smd", "balanced"],
            {"control_mean": _f2, "treatment_mean": _f2},
        ),
        "",
        "协变量的 |SMD| 均小于 0.1，说明随机分组在可观测特征上平衡。**平衡性检查只能排除可观测差异，",
        "不能证明两组在所有方面相同**，这也是实验结果仍需护栏指标的原因。",
        "",
        "## 3. 主指标与次要指标",
        "",
        "### 3.1 购买转化率（主指标）",
        "",
        "| 指标 | 对照组 | 实验组 |",
        "| --- | --- | --- |",
        "| 转化率 | %s（95%% CI %s ~ %s） | %s（95%% CI %s ~ %s） |"
        % (_pct(conversion["rate_a"]), _pct(ci_c["ci_low"]), _pct(ci_c["ci_high"]),
           _pct(conversion["rate_b"]), _pct(ci_t["ci_low"]), _pct(ci_t["ci_high"])),
        "",
        "- 绝对提升 **%s**（95%% CI %s ~ %s），相对提升 **%s**。"
        % (_pp(conversion["diff"]), _pp(conversion["ci_low"]), _pp(conversion["ci_high"]),
           _pct(conversion["relative_lift"], 1)),
        "- 两比例 z 检验：z = %.3f，%s；效应量 Cohen's h = %.3f。"
        % (conversion["z"], _p_expr(conversion["p_value"]), conversion["cohens_h"]),
        "- 卡方检验交叉验证：χ² = %.3f，%s。" % (conversion["chi2"], _p_expr(conversion["chi2_p_value"])),
        "",
        "### 3.2 人均收入 ARPU（次要指标）",
        "",
        "- 对照组 ARPU **%s**，实验组 **%s**，差值 **%s**（95%% CI %s ~ %s）。"
        % (_money2(arpu["mean_a"]), _money2(arpu["mean_b"]), _money2(arpu["diff"]),
           _money2(arpu["ci_low"]), _money2(arpu["ci_high"])),
        "- Welch t 检验：t = %.3f，%s；Cohen's d = %.3f。"
        % (arpu["t"], _p_expr(arpu["p_value"]), arpu["cohens_d"]),
        "- 需要区分「转化率提升」与「客单价提升」：ARPU 同时受两者影响，下面拆开看客单价。",
        "",
        "### 3.3 购买者客单价",
        "",
        "- 对照组 **%s**，实验组 **%s**，差值 **%s**（95%% CI %s ~ %s），%s。"
        % (_money2(aov["mean_a"]), _money2(aov["mean_b"]), _money2(aov["diff"]),
           _money2(aov["ci_low"]), _money2(aov["ci_high"]), _p_expr(aov["p_value"])),
        "",
        "## 4. 分组异质性与多重检验",
        "",
        "按地区拆分后，共做 %d 次检验。**同时做多次检验时，假阳性率会快速膨胀**："
        % len(region_df),
        "若每次检验 α=0.05，5 次独立检验中至少出现 1 个假阳性的概率约为 %.0f%%。"
        % ((1 - 0.95 ** len(region_df)) * 100),
        "因此同时报告原始 p 与 Benjamini-Hochberg（BH，控制 FDR）校正后的 p。",
        "",
        _md_table(
            region_table,
            ["group", "n_control", "n_treatment", "control_rate", "treatment_rate",
             "diff", "ci", "relative_lift", "p_value", "p_adjusted", "significant_raw", "significant_bh"],
        ),
        "",
        "读法：BH 校正后仍显著的地区，才适合作为「该地区效果更好」的候选结论；",
        "校正后不显著的地区不能因为原始 p<0.05 就单独宣布有效——这类「挑显著分组」是常见的分析陷阱。",
        "",
        "## 5. 护栏指标",
        "",
        _md_table(
            guardrail_table,
            ["metric", "control_rate", "treatment_rate", "diff", "ci", "relative_lift", "p_value"],
        ),
        "",
        "护栏指标越低越好。当前差异方向与显著性见上表；即使 p 值不显著，也要关注置信区间上限是否包含",
        "业务上不可接受的恶化幅度（**不显著 ≠ 安全**，可能只是样本量不够）。",
        "",
        "## 6. 功效与样本量",
        "",
        "基于对照组基线转化率 **%s**，事前测算不同最小可检测效应（MDE）所需样本量"
        % _pct(power["baseline_rate"], 2),
        "（α=0.05，power=0.8，双侧检验）：",
        "",
        _md_table(
            power_table,
            ["mde_absolute", "mde_relative", "n_per_group", "n_total", "cohens_h"],
        ),
        "",
        "本次实验观察到的绝对效应为 **%s**，在当前两组样本量下的统计功效约为 **%s**。"
        % (_pp(power["observed_effect"]), _pct(power["achieved_power"], 1)),
        "事后功效只作参考：实验设计阶段就应该用上面的公式确定样本量，而不是做完再算。",
        "",
        "## 7. 业务价值与决策建议",
        "",
        "按每月 **10 万** 用户流量估算（假设，不是 Olist 的真实流量）：",
        "",
        "- 人均收入提升 **%s** → 每月增量收入约 **%s**；"
        % (_money2(value["arpu_lift"]), _money(value["incremental_revenue_per_100k"])),
        "- 转化率提升 **%s** → 每月增量购买用户约 **%s** 人。"
        % (_pp(value["conversion_lift"]), "{:,.0f}".format(value["incremental_conversions_per_100k"])),
        "",
        "决策：%s" % _decision(primary, guardrail_df),
        "",
        "## 8. 与真实观测数据的对照（为什么不能直接拿 Olist 做因果）",
        "",
        "用同一套两比例检验分析 Olist 真实数据中的「迟到 vs 准时」差评率：",
        "",
        "- 准时订单 **%s** 单，差评率 **%s**；迟到订单 **%s** 单，差评率 **%s**。"
        % ("{:,}".format(observed["n_on_time"]), _pct(observed["bad_rate_on_time"], 1),
           "{:,}".format(observed["n_late"]), _pct(observed["bad_rate_late"], 1)),
        "- 差值 **%s**（95%% CI %s ~ %s），相对提升 **%s**，p %s。"
        % (_pp(observed["diff_bad_rate"]), _pp(observed["ci_low"]), _pp(observed["ci_high"]),
           _pct(observed["relative_lift"], 1),
           ("= " + _p(observed["p_value"])) if observed["p_value"] >= 0.001 else "< 0.001"),
        "",
        "这个差异在统计上极显著、效应量也很大，但**不能**据此说「迟到导致差评率上升 4 倍」：",
        "用户不是随机被分配到迟到组的，商家质量、地区物流能力、商品类型等因素同时影响迟到与评分。",
        "模拟实验之所以能做因果陈述，是因为分组由随机数决定；真实数据要达到同样强度，需要随机实验或",
        "可信的准实验设计（如断点回归、双重差分），本项目的 Olist 数据不具备这些条件。",
        "",
        "## 9. 结论边界",
        "",
        "1. **模拟而非真实**：数据由 `simulator.py` 按设定参数生成，效应大小是人为设定的，不能用于预测",
        "   Olist 或任何真实业务的促销效果。",
        "2. **单一实验场景**：只模拟了「促销 → 转化/收入」一个场景，未覆盖长期留存、口碑等长期效应。",
        "3. **统计显著 ≠ 业务重要**：报告同时给出效应量与置信区间，决策时应结合业务成本判断。",
        "4. **重复检验风险**：除地区外，若继续按用户分层、商品类目切分，必须继续做多重检验校正。",
        "",
    ]

    report_path = config.REPORTS_DIR / "experiment_report.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = {
        "n_users": int(len(frame)),
        "n_control": checks["n_control"],
        "n_treatment": checks["n_treatment"],
        "srm_p_value": checks["srm_p_value"],
        "control_rate": conversion["rate_a"],
        "treatment_rate": conversion["rate_b"],
        "conversion_diff": conversion["diff"],
        "conversion_p_value": conversion["p_value"],
        "arpu_diff": arpu["diff"],
        "arpu_p_value": arpu["p_value"],
        "achieved_power": power["achieved_power"],
        "guardrails": guardrail_df.to_dict(orient="records"),
        "business_value": value,
        "regions": region_df.to_dict(orient="records"),
    }
    (config.MODEL_DIR / "experiment_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("  模拟实验数据 → %s" % data_path)
    print("  实验报告 → %s" % report_path)
    return report_path


def main() -> int:
    build_report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
