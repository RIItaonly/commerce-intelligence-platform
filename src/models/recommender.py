"""商品推荐：热门基线 + item-item 协同过滤（基于购买行为）。

边界声明（必须保留）：
Olist 只有交易数据，没有曝光、点击、浏览日志。因此这是「买了 A 的人还买什么」的
购买行为推荐，不是短视频/信息流的点击推荐系统；评估指标是下一次购买的 Recall@K /
NDCG@K，而不是 CTR。

评估设计：
- 时间切分：训练 < 2018-05-01，测试 2018-05-01 ~ 2018-08-31（严格未来）；
- 只评估「训练期有购买、测试期也有购买」的 warm 用户（冷启动用户单独统计占比）；
- 推荐时排除用户已购买过的商品；
- 热门基线：训练期购买用户数最多的 Top-K 商品；
- 协同过滤：Top-3,000 热门商品上的 item-user 二值矩阵，余弦相似度，取每个商品 Top-50 邻居。

用法：python -m src.models.recommender
产物（models/artifacts/）：
  recommendation_metrics.json
  recommendation_popular_items.csv
  recommendation_examples.csv
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Sequence, Set, Tuple

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix

from src import config, sql_engine

TRAIN_END = "2018-05-01"
CATALOG_ITEMS = 3_000
NEIGHBORS = 50
K_VALUES = (5, 10, 20)
EXAMPLE_CUSTOMERS = 200


def load_lines() -> pd.DataFrame:
    df = sql_engine.read_sql(
        """
        SELECT
            oi.customer_unique_id,
            oi.product_id,
            oi.purchase_ts,
            oi.category_name_en,
            oi.price
        FROM fct_order_item oi
        WHERE oi.is_valid_order = 1 AND oi.purchase_ts IS NOT NULL
        """
    )
    df["purchase_ts"] = pd.to_datetime(df["purchase_ts"])
    return df


def popularity(train: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """热门基线：按购买用户数排序（避免大单用户刷榜）。"""
    stats = (
        train.groupby(["product_id", "category_name_en"])
        .agg(users=("customer_unique_id", "nunique"), lines=("product_id", "size"), avg_price=("price", "mean"))
        .reset_index()
        .sort_values(["users", "lines"], ascending=False)
        .head(n)
        .reset_index(drop=True)
    )
    stats["rank"] = np.arange(1, len(stats) + 1)
    return stats


def build_item_catalog(train: pd.DataFrame) -> Tuple[List[str], pd.Index, pd.Index]:
    """取训练期最热门的 N 个商品作为可推荐目录。"""
    counts = train.groupby("product_id")["customer_unique_id"].nunique().sort_values(ascending=False)
    catalog = counts.head(CATALOG_ITEMS).index.tolist()
    users = pd.Index(sorted(train["customer_unique_id"].unique()))
    item_index = pd.Index(catalog)
    return catalog, users, item_index


def build_item_item(train: pd.DataFrame, item_index: pd.Index, users: pd.Index) -> Tuple[np.ndarray, np.ndarray]:
    """在 Top-N 商品上构建 item-user 二值矩阵并计算余弦相似度 Top-K 邻居。"""
    filtered = train[train["product_id"].isin(item_index) & train["customer_unique_id"].isin(users)]
    item_pos = {item: i for i, item in enumerate(item_index)}
    user_pos = {user: i for i, user in enumerate(users)}
    rows = filtered["product_id"].map(item_pos).to_numpy()
    cols = filtered["customer_unique_id"].map(user_pos).to_numpy()
    data = np.ones(len(rows), dtype=np.float32)
    matrix = csr_matrix((data, (rows, cols)), shape=(len(item_index), len(users)))
    matrix.data = np.ones_like(matrix.data)  # 二值化：同一用户重复购买同一商品只算一次

    counts = np.asarray(matrix.sum(axis=1)).ravel()
    inverse = np.zeros_like(counts, dtype=np.float32)
    np.divide(1.0, np.sqrt(counts), out=inverse, where=counts > 0)
    normalized = matrix.multiply(inverse[:, None]).tocsr()

    similarity = (normalized @ normalized.T).toarray().astype(np.float32)
    np.fill_diagonal(similarity, 0.0)

    k = min(NEIGHBORS, len(item_index) - 1)
    neighbor_idx = np.argpartition(-similarity, k, axis=1)[:, :k]
    neighbor_sim = np.take_along_axis(similarity, neighbor_idx, axis=1)
    order = np.argsort(-neighbor_sim, axis=1)
    neighbor_idx = np.take_along_axis(neighbor_idx, order, axis=1)
    neighbor_sim = np.take_along_axis(neighbor_sim, order, axis=1)
    return neighbor_idx, neighbor_sim


class ItemItemRecommender:
    def __init__(self, catalog: List[str], neighbor_idx: np.ndarray, neighbor_sim: np.ndarray, popular: List[str]):
        self.catalog = catalog
        self.item_pos = {item: i for i, item in enumerate(catalog)}
        self.neighbor_idx = neighbor_idx
        self.neighbor_sim = neighbor_sim
        self.popular = popular

    def recommend(self, purchased: Sequence[str], k: int = 20) -> List[str]:
        purchased_idx = [self.item_pos[item] for item in purchased if item in self.item_pos]
        scores = np.zeros(len(self.catalog), dtype=np.float32)
        for idx in purchased_idx:
            scores[self.neighbor_idx[idx]] += self.neighbor_sim[idx]
        if purchased_idx:
            scores[purchased_idx] = -1.0
        if scores.max() <= 0:
            # 冷启动 / 购买商品不在目录：退回热门
            return [item for item in self.popular if item not in set(purchased)][:k]
        top = np.argpartition(-scores, min(k, len(scores) - 1))[:k]
        top = top[np.argsort(-scores[top])]
        return [self.catalog[i] for i in top]


def _ndcg(hits: List[int], total_relevant: int, k: int) -> float:
    dcg = sum(1.0 / np.log2(position + 2) for position, hit in enumerate(hits[:k]) if hit)
    ideal = sum(1.0 / np.log2(i + 2) for i in range(min(total_relevant, k)))
    return float(dcg / ideal) if ideal > 0 else 0.0


def evaluate(
    test: pd.DataFrame,
    train: pd.DataFrame,
    train_users: Set[str],
    recommender: ItemItemRecommender,
    popularity_rank: List[str],
) -> Dict[str, object]:
    """在 warm 用户上评估热门基线与协同过滤。"""
    warm = test[test["customer_unique_id"].isin(train_users)]
    truth = warm.groupby("customer_unique_id")["product_id"].apply(lambda s: set(s)).to_dict()
    purchased_map = train.groupby("customer_unique_id")["product_id"].apply(set).to_dict()

    metrics = {
        "popularity": {k: {"recall": [], "ndcg": [], "recommended": set()} for k in K_VALUES},
        "item_item": {k: {"recall": [], "ndcg": [], "recommended": set()} for k in K_VALUES},
    }

    for user, actual in truth.items():
        already = purchased_map.get(user, set())
        popular_recs = [item for item in popularity_rank if item not in already][: max(K_VALUES)]
        personal_recs = recommender.recommend(already, k=max(K_VALUES))
        for name, recs in (("popularity", popular_recs), ("item_item", personal_recs)):
            for k in K_VALUES:
                top = recs[:k]
                hits = [1 if item in actual else 0 for item in top]
                metrics[name][k]["recall"].append(sum(hits) / len(actual) if actual else 0.0)
                metrics[name][k]["ndcg"].append(_ndcg(hits, len(actual), k))
                metrics[name][k]["recommended"].update(top)

    summary = {}
    for name, result in metrics.items():
        summary[name] = {}
        for k, values in result.items():
            summary[name]["k=%d" % k] = {
                "recall": float(np.mean(values["recall"])) if values["recall"] else 0.0,
                "ndcg": float(np.mean(values["ndcg"])) if values["ndcg"] else 0.0,
                "coverage": float(len(values["recommended"]) / len(recommender.catalog)),
            }
    return {
        "n_warm_users": int(len(truth)),
        "n_test_users": int(test["customer_unique_id"].nunique()),
        "metrics": summary,
    }


def run() -> Dict[str, object]:
    lines = load_lines()
    train = lines[lines["purchase_ts"] < TRAIN_END]
    test = lines[lines["purchase_ts"] >= TRAIN_END]
    print("  训练明细 %s 行，测试明细 %s 行" % ("{:,}".format(len(train)), "{:,}".format(len(test))))

    catalog, users, item_index = build_item_catalog(train)
    popular_table = popularity(train, n=20)
    popular_rank = popular_table["product_id"].tolist()

    print("  构建 item-item 相似度（Top %s 商品）…" % "{:,}".format(len(catalog)))
    neighbor_idx, neighbor_sim = build_item_item(train, item_index, users)
    recommender = ItemItemRecommender(catalog, neighbor_idx, neighbor_sim, popular_rank)

    train_users = set(train["customer_unique_id"].unique())
    print("  评估 warm 用户…")
    evaluation = evaluate(test, train, train_users, recommender, popular_rank)

    # 冷启动占比：测试期有购买但训练期没有购买的用户
    test_users = set(test["customer_unique_id"].unique())
    evaluation["cold_start_share"] = float(len(test_users - train_users) / len(test_users))
    evaluation["n_test_users"] = int(len(test_users))
    evaluation["n_train_users"] = int(len(train_users))

    # 推荐示例：选测试期有购买的用户，展示实际购买与推荐结果
    warm_users = sorted(test_users & train_users)[:EXAMPLE_CUSTOMERS]
    purchased_map = train.groupby("customer_unique_id")["product_id"].apply(set).to_dict()
    category_map = lines.drop_duplicates("product_id").set_index("product_id")["category_name_en"].to_dict()
    price_map = lines.groupby("product_id")["price"].mean().to_dict()
    truth_map = test.groupby("customer_unique_id")["product_id"].apply(set).to_dict()
    rows = []
    for user in warm_users:
        recs = recommender.recommend(purchased_map.get(user, set()), k=10)
        actual = truth_map.get(user, set())
        for rank, item in enumerate(recs, start=1):
            rows.append(
                {
                    "customer_unique_id": user,
                    "rank": rank,
                    "product_id": item,
                    "category": category_map.get(item, "unknown"),
                    "avg_price": round(float(price_map.get(item, 0.0)), 2),
                    "is_actual_next_purchase": int(item in actual),
                }
            )
    examples = pd.DataFrame(rows)

    artifact_dir = config.MODEL_DIR
    popular_table.to_csv(artifact_dir / "recommendation_popular_items.csv", index=False, encoding="utf-8-sig")
    examples.to_csv(artifact_dir / "recommendation_examples.csv", index=False, encoding="utf-8-sig")

    summary = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "task": "基于购买行为的商品推荐（不是点击/曝光推荐）",
        "train_period": ["2016-09-04", TRAIN_END],
        "test_period": [TRAIN_END, "2018-10-17"],
        "catalog_size": len(catalog),
        "catalog_note": "只对训练期最热门的 %s 个商品计算相似度，召回上限受目录限制" % "{:,}".format(len(catalog)),
        "neighbors": NEIGHBORS,
        "evaluation": evaluation,
        "popular_top10": popular_table.head(10).to_dict(orient="records"),
        "limitations": [
            "Olist 没有曝光/点击日志，不能评估 CTR，也不能声称是完整推荐系统。",
            "Recall@K 的分母包含测试期购买的全部商品，但推荐目录只覆盖 Top-%s 商品，因此指标偏保守。" % "{:,}".format(len(catalog)),
            "只评估 warm 用户；冷启动用户占比见 evaluation.cold_start_share，实际系统需要单独的热门/内容策略。",
            "关联规则反映的是共现，不是「买 A 导致买 B」的因果。",
        ],
    }
    (artifact_dir / "recommendation_metrics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=float), encoding="utf-8"
    )

    item_metrics = evaluation["metrics"]["item_item"]
    pop_metrics = evaluation["metrics"]["popularity"]
    print("  Recall@10：热门 %.4f，协同过滤 %.4f"
          % (pop_metrics["k=10"]["recall"], item_metrics["k=10"]["recall"]))
    print("  NDCG@10：热门 %.4f，协同过滤 %.4f"
          % (pop_metrics["k=10"]["ndcg"], item_metrics["k=10"]["ndcg"]))
    print("  评估用户：%s（冷启动占比 %.1f%%）"
          % ("{:,}".format(evaluation["n_warm_users"]), evaluation["cold_start_share"] * 100))
    return summary


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
