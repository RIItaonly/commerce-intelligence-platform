"""流失风险 / 复购倾向模型：基线、LogisticRegression、RandomForest、LightGBM。

任务：过去 90 天行为 → 未来 30 天是否复购（p）。流失风险 = 1 - p。
评估重点不是 accuracy（正类仅约 0.3%），而是排序能力与校准：
PR-AUC、ROC-AUC、Brier、top-decile lift、校准曲线、分群错误分析。

用法：python -m src.models.churn
产物（models/artifacts/）：
  churn_model.joblib              最优模型的完整 pipeline
  churn_metrics.json              数据集信息、各模型指标、校准与限制说明
  churn_model_comparison.csv      模型对比表
  churn_feature_importance.csv    特征重要性（树模型）
  churn_calibration.csv           校准曲线数据
  churn_error_analysis.csv        分群错误分析
  churn_scores.csv                最新快照的用户级复购概率与流失风险
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src import config
from src.features import churn_features as cf

RANDOM_STATE = 42


# ---------------------------------------------------------------- 预处理与模型
def _numeric_imputer() -> SimpleImputer:
    """数值特征中位数填充。

    缺失来自「快照前 90 天没有已签收订单」等情况（评价、配送时长不可得），
    属于真实缺失而非数据错误；用中位数填充并把「评价缺失率」单独作为特征保留。
    """
    return SimpleImputer(strategy="median")


def _preprocessor() -> ColumnTransformer:
    return ColumnTransformer(
        [
            ("num", Pipeline([("impute", _numeric_imputer()), ("scale", StandardScaler())]), cf.NUMERIC_FEATURES),
            (
                "cat",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="constant", fill_value="UNKNOWN")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
                    ]
                ),
                cf.CATEGORICAL_FEATURES,
            ),
        ]
    )


def build_models() -> Dict[str, object]:
    from lightgbm import LGBMClassifier  # 延迟导入：避免 pytest 等场景在收集阶段加载原生库

    return {
        "LogisticRegression": Pipeline(
            [
                ("prep", _preprocessor()),
                ("clf", LogisticRegression(max_iter=2000, random_state=RANDOM_STATE)),
            ]
        ),
        "RandomForest": Pipeline(
            [
                ("prep", _preprocessor()),
                (
                    "clf",
                    RandomForestClassifier(
                        n_estimators=300,
                        min_samples_leaf=50,
                        max_features="sqrt",
                        n_jobs=-1,
                        random_state=RANDOM_STATE,
                    ),
                ),
            ]
        ),
        "LightGBM": Pipeline(
            [
                ("prep", _preprocessor()),
                (
                    "clf",
                    LGBMClassifier(
                        n_estimators=500,
                        learning_rate=0.03,
                        num_leaves=31,
                        min_child_samples=100,
                        subsample=0.8,
                        colsample_bytree=0.8,
                        reg_lambda=1.0,
                        random_state=RANDOM_STATE,
                        n_jobs=-1,
                        verbose=-1,
                    ),
                ),
            ]
        ),
    }


# ---------------------------------------------------------------- 评估
def ranking_metrics(y_true: np.ndarray, score: np.ndarray, k_ratio: float = 0.1) -> Dict[str, float]:
    """排序与概率质量指标。"""
    y_true = np.asarray(y_true, dtype=int)
    score = np.asarray(score, dtype=float)
    n = len(y_true)
    k = max(1, int(np.ceil(n * k_ratio)))
    order = np.argsort(-score)
    captured = int(y_true[order[:k]].sum())
    positives = int(y_true.sum())
    precision = captured / k
    base_rate = positives / n
    return {
        "n": n,
        "positives": positives,
        "base_rate": float(base_rate),
        "pr_auc": float(average_precision_score(y_true, score)) if positives else float("nan"),
        "roc_auc": float(roc_auc_score(y_true, score)) if 0 < positives < n else float("nan"),
        "brier": float(brier_score_loss(y_true, score)),
        "log_loss": float(log_loss(y_true, np.clip(score, 1e-6, 1 - 1e-6), labels=[0, 1])),
        "top10_precision": float(precision),
        "top10_recall": float(captured / positives) if positives else float("nan"),
        "lift_at_10pct": float(precision / base_rate) if base_rate > 0 else float("nan"),
    }


def calibration_table(y_true: np.ndarray, score: np.ndarray, bins: int = 10) -> pd.DataFrame:
    """按预测概率分位分箱的校准表 + ECE。"""
    frame = pd.DataFrame({"y": y_true, "score": score})
    frame["bin"] = pd.qcut(frame["score"], q=bins, duplicates="drop")
    table = (
        frame.groupby("bin")
        .agg(n=("y", "size"), mean_predicted=("score", "mean"), observed_rate=("y", "mean"))
        .reset_index()
    )
    table["abs_gap"] = (table["mean_predicted"] - table["observed_rate"]).abs()
    table["ece"] = (table["n"] / len(frame) * table["abs_gap"]).sum()
    return table


def _rule_score(frame: pd.DataFrame) -> np.ndarray:
    """朴素基线：越近购买越可能复购（1 / (1 + recency)）。"""
    return 1.0 / (1.0 + frame["recency_days"].to_numpy(dtype=float))


def _feature_names(pipeline: Pipeline) -> List[str]:
    prep = pipeline.named_steps["prep"]
    return list(prep.get_feature_names_out())


def _error_analysis(test_df: pd.DataFrame, scores: np.ndarray) -> pd.DataFrame:
    """按关键分群检查模型表现，定位错误集中在哪里。"""
    df = test_df.copy()
    df["score"] = scores
    df["recency_bucket"] = pd.cut(
        df["recency_days"], bins=[-1, 14, 30, 60, 90], labels=["0-14 天", "15-30 天", "31-60 天", "61-90 天"]
    )
    df["order_bucket"] = np.where(df["orders_90d"] >= 2, "90 天内 2 单以上", "90 天内 1 单")
    rows = []
    for column in ("recency_bucket", "order_bucket", "customer_state"):
        for name, group in df.groupby(column):
            if len(group) < 200 or group["active_30d"].sum() < 20:
                continue
            rows.append(
                {
                    "dimension": column,
                    "group": str(name),
                    "n": int(len(group)),
                    "positives": int(group["active_30d"].sum()),
                    "actual_rate": float(group["active_30d"].mean()),
                    "mean_predicted": float(group["score"].mean()),
                    "pr_auc": float(average_precision_score(group["active_30d"], group["score"])),
                }
            )
    return pd.DataFrame(rows).sort_values(["dimension", "n"], ascending=[True, False])


# ---------------------------------------------------------------- 主流程
def run() -> Dict[str, object]:
    print("  构建特征数据集（17 个月度快照）…")
    dataset = cf.build_dataset(with_label=True)
    issues = cf.leakage_checks(dataset)
    if issues:
        raise RuntimeError("特征泄漏检查未通过：%s" % "；".join(issues))

    train_df, test_df = cf.split_time(dataset)
    x_train = train_df[cf.FEATURES]
    y_train = train_df[cf.TARGET].to_numpy()
    x_test = test_df[cf.FEATURES]
    y_test = test_df[cf.TARGET].to_numpy()

    print("  训练集 %s 行（正类 %.3f%%），测试集 %s 行（正类 %.3f%%）"
          % ("{:,}".format(len(train_df)), y_train.mean() * 100,
             "{:,}".format(len(test_df)), y_test.mean() * 100))

    # 基线 1：常数先验 + 极小随机扰动（无排序能力，仅保留正确的概率尺度）
    # 基线 2：recency 规则
    dummy = DummyClassifier(strategy="prior", random_state=RANDOM_STATE).fit(x_train, y_train)
    rng = np.random.default_rng(RANDOM_STATE)
    prior_scores = dummy.predict_proba(x_test)[:, 1] + rng.normal(0, 1e-7, len(test_df))
    scores: Dict[str, np.ndarray] = {"随机基线（先验概率）": prior_scores}
    scores["Recency 规则"] = _rule_score(test_df)

    metrics: Dict[str, Dict[str, float]] = {
        "随机基线（先验概率）": ranking_metrics(y_test, scores["随机基线（先验概率）"]),
        "Recency 规则": ranking_metrics(y_test, scores["Recency 规则"]),
    }

    models = build_models()
    fitted: Dict[str, Pipeline] = {}
    for name, pipeline in models.items():
        print("  训练 %s …" % name)
        pipeline.fit(x_train, y_train)
        fitted[name] = pipeline
        scores[name] = pipeline.predict_proba(x_test)[:, 1]
        metrics[name] = ranking_metrics(y_test, scores[name])

    best_name = max(("LogisticRegression", "RandomForest", "LightGBM"), key=lambda n: metrics[n]["pr_auc"])
    best_model = fitted[best_name]
    print("  最优模型：%s（PR-AUC %.4f）" % (best_name, metrics[best_name]["pr_auc"]))

    # 客户不重叠子集：测试集中从未在训练集出现的客户，检验跨用户泛化
    unseen_mask = ~test_df["customer_unique_id"].isin(train_df["customer_unique_id"])
    unseen_metrics = ranking_metrics(
        y_test[unseen_mask.to_numpy()], scores[best_name][unseen_mask.to_numpy()]
    )

    # 多个测试快照上的稳定性
    per_snapshot = []
    for month, group in test_df.groupby("snapshot_month"):
        mask = group.index.to_numpy()
        per_snapshot.append(
            {
                "snapshot_month": month,
                "n": int(len(group)),
                "positives": int(group[cf.TARGET].sum()),
                "pr_auc": float(average_precision_score(group[cf.TARGET], scores[best_name][mask])),
                "roc_auc": float(roc_auc_score(group[cf.TARGET], scores[best_name][mask]))
                if 0 < group[cf.TARGET].sum() < len(group) else float("nan"),
            }
        )
    snapshot_df = pd.DataFrame(per_snapshot)

    # 校准
    calibration = calibration_table(y_test, scores[best_name])
    ece = float(calibration["ece"].iloc[0])

    # 特征重要性（LightGBM）
    importance_df = pd.DataFrame()
    if "LightGBM" in fitted:
        names = _feature_names(fitted["LightGBM"])
        values = fitted["LightGBM"].named_steps["clf"].feature_importances_
        importance_df = (
            pd.DataFrame({"feature": names, "importance": values})
            .sort_values("importance", ascending=False)
            .reset_index(drop=True)
        )
        importance_df["importance_share"] = importance_df["importance"] / importance_df["importance"].sum()

    error_df = _error_analysis(test_df, scores[best_name])

    # 最新快照打分
    print("  给最新快照用户打分 …")
    scoring = cf.build_scoring_set()
    scoring["p_active_30d"] = best_model.predict_proba(scoring[cf.FEATURES])[:, 1]
    scoring["churn_risk"] = 1 - scoring["p_active_30d"]
    quantiles = scoring["p_active_30d"].rank(pct=True)
    scoring["risk_band"] = np.select(
        [quantiles <= 0.1, quantiles <= 0.4],
        ["高流失风险（复购概率最低 10%）", "中高流失风险（最低 10%-40%）"],
        default="常规（复购概率前 60%）",
    )
    scoring = scoring.sort_values("p_active_30d", ascending=False)

    # 落盘
    artifact_dir = config.MODEL_DIR
    joblib.dump(best_model, artifact_dir / "churn_model.joblib")

    comparison = pd.DataFrame(
        [
            {"model": name, **{k: v for k, v in values.items() if k not in ("n", "positives")}}
            for name, values in metrics.items()
        ]
    ).sort_values("pr_auc", ascending=False)
    comparison.to_csv(artifact_dir / "churn_model_comparison.csv", index=False, encoding="utf-8-sig")
    calibration.drop(columns=["bin"]).to_csv(
        artifact_dir / "churn_calibration.csv", index=False, encoding="utf-8-sig"
    )
    if not importance_df.empty:
        importance_df.to_csv(
            artifact_dir / "churn_feature_importance.csv", index=False, encoding="utf-8-sig"
        )
    error_df.to_csv(artifact_dir / "churn_error_analysis.csv", index=False, encoding="utf-8-sig")
    snapshot_df.to_csv(artifact_dir / "churn_by_snapshot.csv", index=False, encoding="utf-8-sig")
    scoring.to_csv(artifact_dir / "churn_scores.csv", index=False, encoding="utf-8-sig")

    summary = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "target": "未来 30 天是否复购（active_30d），流失风险 = 1 - p",
        "train": {
            "rows": int(len(train_df)),
            "customers": int(train_df["customer_unique_id"].nunique()),
            "snapshot_range": [str(train_df["snapshot"].min())[:10], str(train_df["snapshot"].max())[:10]],
            "positive_rate": float(y_train.mean()),
        },
        "test": {
            "rows": int(len(test_df)),
            "customers": int(test_df["customer_unique_id"].nunique()),
            "snapshot_range": [str(test_df["snapshot"].min())[:10], str(test_df["snapshot"].max())[:10]],
            "positive_rate": float(y_test.mean()),
        },
        "chosen_model": best_name,
        "metrics": metrics,
        "unseen_customers": unseen_metrics,
        "per_snapshot": snapshot_df.to_dict(orient="records"),
        "calibration_ece": ece,
        "top_features": importance_df.head(10).to_dict(orient="records") if not importance_df.empty else [],
        "scoring_snapshot": cf.SCORING_SNAPSHOT,
        "scoring_customers": int(len(scoring)),
        "scoring_top_decile_mean_probability": float(scoring["p_active_30d"].head(max(1, len(scoring) // 10)).mean()),
        "leakage_checks": "通过",
    }
    (artifact_dir / "churn_metrics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=float), encoding="utf-8"
    )

    print("  模型与指标 → %s" % artifact_dir)
    print("  测试集 PR-AUC：%s" % ", ".join(
        "%s %.4f" % (name, values["pr_auc"]) for name, values in metrics.items()
    ))
    print("  最新快照打分用户数：%s" % "{:,}".format(len(scoring)))
    return summary


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
