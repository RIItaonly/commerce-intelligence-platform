"""模型监控：特征分布漂移（PSI / KS）与预测分布漂移。

参照口径
--------
- 流失特征快照不持久化历史版本（只保留最新打分），因此本脚本调用特征构建器
  重建最近 N 个快照：前 N-1 个为参照集（训练分布），最新一个为当前集
  （模拟"上线后新到的数据"）。
- 对全部数值特征计算 PSI（Population Stability Index）与 KS 检验，
  并对比模型预测概率 p_active_30d 的分布。

判读阈值（业界常用经验值）
------------------------
- PSI < 0.1：分布稳定
- 0.1 ~ 0.25：轻度漂移，关注
- > 0.25：显著漂移，建议重训；脚本以退出码 1 提示

输出
----
- outputs/drift_report.csv：逐特征 PSI / KS 明细
- outputs/drift_summary.json：汇总与结论
"""
import json
from typing import Tuple

import numpy as np
import pandas as pd
from scipy import stats

from .. import config

PSI_ATTENTION = 0.1
PSI_ALERT = 0.25

# 不参与漂移检查的非特征列
NON_FEATURE_COLS = {
    "customer_unique_id",
    "snapshot",
    "snapshot_month",
    "p_active_30d",
    "churn_risk",
    "risk_band",
    "customer_state",
}


def psi(reference: pd.Series, current: pd.Series, bins: int = 10) -> float:
    """Population Stability Index：按参照集分位数分箱，对比两分布占比。"""
    ref = reference.dropna().astype(float)
    cur = current.dropna().astype(float)
    if len(ref) < 100 or len(cur) < 100 or ref.nunique() < 3:
        return 0.0
    quantiles = np.linspace(0, 1, bins + 1)
    edges = np.unique(ref.quantile(quantiles).values)
    if len(edges) < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    ref_pct = np.histogram(ref, bins=edges)[0] / len(ref)
    cur_pct = np.histogram(cur, bins=edges)[0] / len(cur)
    # 避免 log(0)
    ref_pct = np.clip(ref_pct, 1e-4, None)
    cur_pct = np.clip(cur_pct, 1e-4, None)
    return float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))


def ks_pvalue(reference: pd.Series, current: pd.Series) -> float:
    ref = reference.dropna().astype(float)
    cur = current.dropna().astype(float)
    if len(ref) < 100 or len(cur) < 100:
        return 1.0
    return float(stats.ks_2samp(ref, cur).pvalue)


def _build_recent_snapshots(n_snapshots: int = 4) -> pd.DataFrame:
    """重建最近 n 个月度快照的流失特征（不含标签），用于漂移对比。"""
    from ..features import churn_features as cf

    orders = cf.load_orders()
    breadth = cf.load_order_category_breadth()
    snapshots = pd.date_range(cf.SNAPSHOT_START, cf.SNAPSHOT_END, freq="MS")[-n_snapshots:]
    frames = []
    for snapshot in snapshots:
        print("  重建快照特征 %s ..." % snapshot.date())
        frames.append(cf._snapshot_rows(snapshot, orders, breadth, with_label=False))
    return pd.concat(frames, ignore_index=True)


def _split_reference_current(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, str]:
    latest = df["snapshot"].max()
    return df[df["snapshot"] < latest], df[df["snapshot"] == latest], str(latest)


def run(n_snapshots: int = 4) -> dict:
    scores = _build_recent_snapshots(n_snapshots)
    reference, current, latest_snapshot = _split_reference_current(scores)
    # 用离线模型对参照/当前集打分，得到预测分布
    import joblib

    from ..features import churn_features as cf

    model = joblib.load(config.MODEL_DIR / "churn_model.joblib")
    scores = scores.copy()
    scores["p_active_30d"] = model.predict_proba(scores[cf.FEATURES])[:, 1]
    reference, current, latest_snapshot = _split_reference_current(scores)

    feature_cols = [
        c
        for c in scores.columns
        if c not in NON_FEATURE_COLS and pd.api.types.is_numeric_dtype(scores[c])
    ]

    rows = []
    for col in feature_cols:
        rows.append(
            {
                "feature": col,
                "psi": psi(reference[col], current[col]),
                "ks_pvalue": ks_pvalue(reference[col], current[col]),
                "ref_mean": float(reference[col].mean()),
                "cur_mean": float(current[col].mean()),
            }
        )
    # 预测分布漂移：复购概率
    rows.append(
        {
            "feature": "PREDICTION__p_active_30d",
            "psi": psi(reference["p_active_30d"], current["p_active_30d"]),
            "ks_pvalue": ks_pvalue(reference["p_active_30d"], current["p_active_30d"]),
            "ref_mean": float(reference["p_active_30d"].mean()),
            "cur_mean": float(current["p_active_30d"].mean()),
        }
    )

    report = pd.DataFrame(rows).sort_values("psi", ascending=False)
    report["level"] = pd.cut(
        report["psi"],
        bins=[-np.inf, PSI_ATTENTION, PSI_ALERT, np.inf],
        labels=["稳定", "关注", "显著漂移"],
    )

    config.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    report.to_csv(config.OUTPUTS_DIR / "drift_report.csv", index=False, encoding="utf-8-sig")

    n_alert = int((report["psi"] > PSI_ALERT).sum())
    n_attention = int((report["psi"] > PSI_ATTENTION).sum()) - n_alert
    summary = {
        "reference_snapshots": int(reference["snapshot"].nunique()),
        "current_snapshot": latest_snapshot,
        "n_reference_rows": int(len(reference)),
        "n_current_rows": int(len(current)),
        "n_features_checked": int(len(rows)),
        "n_alert": n_alert,
        "n_attention": n_attention,
        "top_drift": report.head(5)[["feature", "psi"]].to_dict("records"),
        "conclusion": (
            "存在显著漂移特征，建议评估重训"
            if n_alert > 0
            else "特征分布整体稳定"
        ),
    }
    (config.OUTPUTS_DIR / "drift_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("== 漂移检查 ==")
    print("参照：%d 个历史快照 / %d 行；当前：%s / %d 行" % (
        summary["reference_snapshots"],
        summary["n_reference_rows"],
        latest_snapshot,
        summary["n_current_rows"],
    ))
    print("显著漂移 %d 个，关注 %d 个" % (n_alert, n_attention))
    print(report.head(10).to_string(index=False))
    print("明细 → %s" % (config.OUTPUTS_DIR / "drift_report.csv"))
    return summary


if __name__ == "__main__":
    result = run()
    raise SystemExit(1 if result["n_alert"] > 0 else 0)
