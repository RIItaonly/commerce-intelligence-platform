"""RFM + K-Means 客户分群：k 选择、稳定性、与规则分群对比。

数据来源：`analytics_rfm`（与阶段 2 的规则分群同一份 RFM 数据）。
建模流程：
1. 特征：recency_days、log1p(frequency)、log1p(monetary)，标准化；
2. 用轮廓系数在 k=2..8 中选 k（抽样计算，避免 O(n²) 距离矩阵）；
3. 全量 K-Means，随机种子与 bootstrap 重采样检验分群稳定性；
4. 与阶段 2 的业务规则分群做交叉对比，检查两者是否讲同一个故事。

用法：python -m src.models.segmentation
产物（models/artifacts/）：
  segmentation_model.joblib
  segmentation_metrics.json
  segmentation_profiles.csv
  segmentation_labels.csv
  segmentation_crosstab.csv
  segmentation_k_selection.csv
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List

import joblib
import numpy as np
import pandas as pd
from scipy.cluster.vq import kmeans2
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from src import config
from src.analytics import rfm

RANDOM_STATE = 42
K_RANGE = range(2, 9)
SILHOUETTE_SAMPLE = 12_000


def _fit_kmeans(x: np.ndarray, k: int, seed: int, n_init: int = 10):
    """多初始化 K-Means（scipy.kmeans2，k-means++），返回惯性最优的一组中心与标签。

    说明：这里用 scipy 实现而不是 sklearn.cluster.KMeans，是因为当前 Anaconda/venv
    混装环境下 sklearn 的 threadpoolctl 在 Windows 上会报 BLAS 配置读取错误；
    scipy 版本算法相同，且结果可复现（固定 seed）。
    """
    best = None
    for attempt in range(n_init):
        try:
            centroids, labels = kmeans2(
                x, k, iter=100, minit="++", seed=seed + attempt, missing="raise"
            )
        except (ValueError, np.linalg.LinAlgError):
            continue
        if len(np.unique(labels)) < k:
            continue
        inertia = float(((x - centroids[labels]) ** 2).sum())
        if best is None or inertia < best["inertia"]:
            best = {"inertia": inertia, "centroids": centroids, "labels": labels}
    if best is None:
        raise RuntimeError("K-Means 未能得到 %d 个非空簇" % k)
    return best


def _predict(x: np.ndarray, centroids: np.ndarray) -> np.ndarray:
    distances = ((x[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2)
    return distances.argmin(axis=1)


def load_features() -> pd.DataFrame:
    df = rfm.load_rfm()
    # 剔除「只有取消/不可用订单」的用户：frequency=0、monetary=0，RFM 无业务含义
    df = df[df["frequency"] >= 1].reset_index(drop=True)
    # 用百分位秩代替原始值：Olist 的 monetary 极端右偏（最大 R$13,664），
    # 直接标准化会让少数极值主导 K-Means，秩变换对离群值稳健且不改变排序。
    df["r_rank"] = df["recency_days"].rank(pct=True)
    df["f_rank"] = df["frequency"].rank(pct=True)
    df["m_rank"] = df["monetary"].rank(pct=True)
    return df


def _matrix(df: pd.DataFrame) -> np.ndarray:
    return df[["r_rank", "f_rank", "m_rank"]].to_numpy(dtype=float)


def select_k(x_scaled: np.ndarray, seed: int = RANDOM_STATE) -> pd.DataFrame:
    """抽样计算各 k 的轮廓系数。"""
    rng = np.random.default_rng(seed)
    n = len(x_scaled)
    sample_idx = rng.choice(n, size=min(SILHOUETTE_SAMPLE, n), replace=False)
    sample = x_scaled[sample_idx]
    rows: List[Dict[str, float]] = []
    for k in K_RANGE:
        result = _fit_kmeans(sample, k, seed=seed)
        rows.append(
            {
                "k": k,
                "silhouette": float(silhouette_score(sample, result["labels"])),
                "inertia": result["inertia"],
            }
        )
    return pd.DataFrame(rows)


def stability(x_scaled: np.ndarray, base_labels: np.ndarray, k: int, n_boot: int = 10) -> Dict[str, float]:
    """bootstrap 重采样 + 随机种子稳定性（用 ARI 衡量分群一致性）。"""
    rng = np.random.default_rng(RANDOM_STATE)
    n = len(x_scaled)
    eval_idx = rng.choice(n, size=min(20_000, n), replace=False)
    base_eval = base_labels[eval_idx]

    bootstrap_aris: List[float] = []
    for i in range(n_boot):
        idx = rng.choice(n, size=int(0.8 * n), replace=False)
        result = _fit_kmeans(x_scaled[idx], k, seed=i, n_init=5)
        bootstrap_aris.append(
            float(adjusted_rand_score(base_eval, _predict(x_scaled[eval_idx], result["centroids"])))
        )

    seed_aris: List[float] = []
    for i in range(5):
        result = _fit_kmeans(x_scaled, k, seed=100 + i, n_init=10)
        seed_aris.append(float(adjusted_rand_score(base_labels, result["labels"])))

    return {
        "bootstrap_ari_mean": float(np.mean(bootstrap_aris)),
        "bootstrap_ari_std": float(np.std(bootstrap_aris)),
        "bootstrap_ari_min": float(np.min(bootstrap_aris)),
        "seed_ari_mean": float(np.mean(seed_aris)),
        "seed_ari_min": float(np.min(seed_aris)),
        "n_boot": n_boot,
    }


def name_clusters(profiles: pd.DataFrame, median_m: float, median_r: float) -> pd.Series:
    """按 RFM 相对水平给分群起业务可读名称。

    阈值使用**全体客户**的中位数，而不是各簇均值的中位数，
    否则在「少数高价值簇拉高均值」时会误判。
    """
    names = []
    used = set()
    for _, row in profiles.iterrows():
        high_value = row["avg_monetary"] >= median_m * 2
        recent = row["avg_recency_days"] <= median_r
        repeat = row["avg_frequency"] >= 1.5

        if repeat and recent:
            base = "复购活跃"
        elif repeat and not recent:
            base = "复购沉睡"
        elif high_value and recent:
            base = "近期高价值单次客"
        elif high_value and not recent:
            base = "沉睡高价值单次客"
        elif recent:
            base = "近期低价值单次客"
        else:
            base = "沉睡低价值单次客"

        name = base
        suffix = 2
        while name in used:
            name = "%s %d" % (base, suffix)
            suffix += 1
        used.add(name)
        names.append(name)
    return pd.Series(names, index=profiles.index)


def profile_table(df: pd.DataFrame, labels: np.ndarray) -> pd.DataFrame:
    frame = df.copy()
    frame["cluster"] = labels
    total_revenue = frame["monetary"].sum()
    profiles = (
        frame.groupby("cluster")
        .agg(
            customers=("customer_unique_id", "count"),
            avg_recency_days=("recency_days", "mean"),
            median_recency_days=("recency_days", "median"),
            avg_frequency=("frequency", "mean"),
            share_repeat=("frequency", lambda s: float((s >= 2).mean())),
            avg_monetary=("monetary", "mean"),
            median_monetary=("monetary", "median"),
            revenue=("monetary", "sum"),
        )
        .reset_index()
    )
    profiles["customer_share"] = profiles["customers"] / len(frame)
    profiles["revenue_share"] = profiles["revenue"] / total_revenue
    profiles["cluster_name"] = name_clusters(
        profiles, median_m=float(frame["monetary"].median()), median_r=float(frame["recency_days"].median())
    )
    return profiles


def run() -> Dict[str, object]:
    df = load_features()
    x = _matrix(df)
    scaler = StandardScaler()
    x_scaled = scaler.fit_transform(x)

    print("  选择 k（轮廓系数，抽样 %s）…" % "{:,}".format(min(SILHOUETTE_SAMPLE, len(df))))
    k_table = select_k(x_scaled)
    best_k = int(k_table.loc[k_table["silhouette"].idxmax(), "k"])

    print("  K-Means 全量训练（k=%d）…" % best_k)
    result = _fit_kmeans(x_scaled, best_k, seed=RANDOM_STATE, n_init=20)
    labels = result["labels"]
    centroids = result["centroids"]
    df["cluster"] = labels

    profiles = profile_table(df, labels)
    name_map = dict(zip(profiles["cluster"], profiles["cluster_name"]))
    df["cluster_name"] = df["cluster"].map(name_map)

    print("  稳定性检验（bootstrap + 多种子）…")
    stab = stability(x_scaled, labels, best_k)
    best_silhouette = float(k_table.loc[k_table["k"] == best_k, "silhouette"].iloc[0])

    # 与规则分群对比
    rule_df = rfm.add_segments(df[["customer_unique_id", "recency_days", "frequency", "monetary", "first_purchase_ts", "last_purchase_ts"]].copy())
    df["rule_segment"] = rule_df["segment"].to_numpy()
    crosstab = pd.crosstab(df["rule_segment"], df["cluster_name"])
    crosstab_share = crosstab.div(crosstab.sum(axis=1), axis=0)

    # 每个规则分群最常落入的 K-Means 分群
    dominant = crosstab.idxmax(axis=1).rename("dominant_cluster").reset_index()
    dominant["dominant_share"] = [
        float(crosstab.loc[row["rule_segment"], row["dominant_cluster"]] / crosstab.loc[row["rule_segment"]].sum())
        for _, row in dominant.iterrows()
    ]

    artifact_dir = config.MODEL_DIR
    joblib.dump(
        {"scaler": scaler, "centroids": centroids, "k": best_k, "cluster_names": name_map},
        artifact_dir / "segmentation_model.joblib",
    )
    k_table.to_csv(artifact_dir / "segmentation_k_selection.csv", index=False, encoding="utf-8-sig")
    profiles.to_csv(artifact_dir / "segmentation_profiles.csv", index=False, encoding="utf-8-sig")
    crosstab.to_csv(artifact_dir / "segmentation_crosstab.csv", encoding="utf-8-sig")
    dominant.to_csv(artifact_dir / "segmentation_rule_comparison.csv", index=False, encoding="utf-8-sig")
    df[
        ["customer_unique_id", "cluster", "cluster_name", "rule_segment", "recency_days",
         "frequency", "monetary"]
    ].to_csv(artifact_dir / "segmentation_labels.csv", index=False, encoding="utf-8-sig")

    summary = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": "analytics_rfm（与阶段 2 规则分群同一口径）",
        "n_customers": int(len(df)),
        "features": ["recency_days 百分位秩", "frequency 百分位秩", "monetary 百分位秩"],
        "chosen_k": best_k,
        "silhouette": best_silhouette,
        "k_selection": k_table.to_dict(orient="records"),
        "stability": stab,
        "profiles": profiles.to_dict(orient="records"),
        "rule_segment_dominant_cluster": dominant.to_dict(orient="records"),
        "notes": [
            "Olist 约 97% 客户仅 1 单，frequency 的信息量有限，分群主要由 recency 与 monetary 驱动。",
            "轮廓系数在 0.25-0.35 量级属于常见的中等可分性，不应期望非常清晰的自然分群。",
            "分群只用于运营分层，不用于因果判断；高价值分群不等于「对营销更敏感」。",
        ],
    }
    (artifact_dir / "segmentation_metrics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=float), encoding="utf-8"
    )

    print("  k=%d，轮廓系数 %.3f，bootstrap ARI %.3f ± %.3f"
          % (best_k, best_silhouette, stab["bootstrap_ari_mean"], stab["bootstrap_ari_std"]))
    print("  分群画像 → %s" % (artifact_dir / "segmentation_profiles.csv"))
    return summary


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
