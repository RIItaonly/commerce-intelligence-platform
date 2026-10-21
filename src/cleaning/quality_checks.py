"""数据质量校验：主键唯一性、空值、关联完整性、时间异常、数值异常、粒度一致性、月份覆盖度。

输出：
- outputs/data_quality_checks.csv   机器可读明细（每行一条检查）
- reports/data_quality_report.md    人类可读报告

状态约定：FAIL = 必须修复才能继续分析；WARN = 数据已知特点，分析时需注意；PASS = 通过。

用法：python -m src.cleaning.quality_checks
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd

from src import config, sql_engine


@dataclass
class Check:
    check_id: str
    category: str
    name: str
    status: str  # PASS / WARN / FAIL
    value: str
    detail: str = ""


_CHECKS: List[Check] = []


def _add(check_id: str, category: str, name: str, status: str, value, detail: str = "") -> None:
    _CHECKS.append(Check(check_id, category, name, status, str(value), detail))


def _scalar(sql: str):
    return sql_engine.query_scalar(sql)


def _count(sql: str) -> int:
    return int(_scalar(sql) or 0)


def _verdict(bad: int, fail_if_positive: bool = True) -> str:
    if bad == 0:
        return "PASS"
    return "FAIL" if fail_if_positive else "WARN"


def run_checks() -> pd.DataFrame:
    """执行全部检查，返回明细 DataFrame。"""
    _CHECKS.clear()

    # ---------------- 1. 主键唯一性 ----------------
    pk_specs = [
        ("pk_orders", "raw_orders.order_id 无重复",
         "SELECT COUNT(*) FROM (SELECT order_id FROM raw_orders GROUP BY order_id HAVING COUNT(*) > 1)"),
        ("pk_items", "raw_order_items.(order_id, order_item_id) 无重复",
         "SELECT COUNT(*) FROM (SELECT order_id, order_item_id FROM raw_order_items "
         "GROUP BY order_id, order_item_id HAVING COUNT(*) > 1)"),
        ("pk_customers", "raw_customers.customer_id 无重复",
         "SELECT COUNT(*) FROM (SELECT customer_id FROM raw_customers GROUP BY customer_id HAVING COUNT(*) > 1)"),
        ("pk_products", "raw_products.product_id 无重复",
         "SELECT COUNT(*) FROM (SELECT product_id FROM raw_products GROUP BY product_id HAVING COUNT(*) > 1)"),
        ("pk_sellers", "raw_sellers.seller_id 无重复",
         "SELECT COUNT(*) FROM (SELECT seller_id FROM raw_sellers GROUP BY seller_id HAVING COUNT(*) > 1)"),
        ("pk_reviews", "raw_order_reviews.review_id 无重复",
         "SELECT COUNT(*) FROM (SELECT review_id FROM raw_order_reviews GROUP BY review_id HAVING COUNT(*) > 1)"),
    ]
    for check_id, name, sql in pk_specs:
        bad = _count(sql)
        _add(check_id, "主键唯一性", name, _verdict(bad), bad)

    # ---------------- 2. 空值 ----------------
    bad = _count("SELECT COUNT(*) FROM raw_orders WHERE order_purchase_timestamp IS NULL")
    _add("null_purchase_ts", "空值", "raw_orders.order_purchase_timestamp 无空值", _verdict(bad), bad)

    bad = _count("SELECT COUNT(*) FROM raw_order_items WHERE price IS NULL")
    _add("null_item_price", "空值", "raw_order_items.price 无空值", _verdict(bad), bad)

    bad = _count("SELECT COUNT(*) FROM raw_order_payments WHERE payment_value IS NULL")
    _add("null_payment_value", "空值", "raw_order_payments.payment_value 无空值", _verdict(bad), bad)

    bad = _count("SELECT COUNT(*) FROM raw_products WHERE product_category_name IS NULL")
    _add("null_category", "空值", "raw_products.product_category_name 空值（已知数据特点）",
         "WARN" if bad > 0 else "PASS", bad,
         "缺失品类在 staging 层填充为 'unknown'，不影响主键与金额计算")

    # ---------------- 3. 关联完整性（孤儿记录） ----------------
    fk_specs = [
        ("fk_items_orders", "order_items → orders 无孤儿",
         "SELECT COUNT(*) FROM raw_order_items oi LEFT JOIN raw_orders o ON o.order_id = oi.order_id "
         "WHERE o.order_id IS NULL"),
        ("fk_payments_orders", "order_payments → orders 无孤儿",
         "SELECT COUNT(*) FROM raw_order_payments p LEFT JOIN raw_orders o ON o.order_id = p.order_id "
         "WHERE o.order_id IS NULL"),
        ("fk_reviews_orders", "order_reviews → orders 无孤儿",
         "SELECT COUNT(*) FROM raw_order_reviews r LEFT JOIN raw_orders o ON o.order_id = r.order_id "
         "WHERE o.order_id IS NULL"),
        ("fk_orders_customers", "orders → customers 无孤儿",
         "SELECT COUNT(*) FROM raw_orders o LEFT JOIN raw_customers c ON c.customer_id = o.customer_id "
         "WHERE c.customer_id IS NULL"),
        ("fk_items_products", "order_items → products 无孤儿",
         "SELECT COUNT(*) FROM raw_order_items oi LEFT JOIN raw_products p ON p.product_id = oi.product_id "
         "WHERE p.product_id IS NULL"),
        ("fk_items_sellers", "order_items → sellers 无孤儿",
         "SELECT COUNT(*) FROM raw_order_items oi LEFT JOIN raw_sellers s ON s.seller_id = oi.seller_id "
         "WHERE s.seller_id IS NULL"),
    ]
    for check_id, name, sql in fk_specs:
        bad = _count(sql)
        _add(check_id, "关联完整性", name, _verdict(bad), bad)

    # ---------------- 4. 时间异常 ----------------
    bounds = sql_engine.read_sql(
        "SELECT MIN(order_purchase_timestamp) AS min_ts, MAX(order_purchase_timestamp) AS max_ts FROM raw_orders"
    ).iloc[0]
    _add("time_range", "时间异常", "下单时间覆盖范围", "PASS",
         "%s ~ %s" % (str(bounds["min_ts"])[:10], str(bounds["max_ts"])[:10]),
         "首尾月份不完整，趋势分析限定 %s ~ %s" % (config.ANALYSIS_START_DATE, config.ANALYSIS_END_DATE))

    bad = _count(
        "SELECT COUNT(*) FROM raw_orders WHERE order_delivered_customer_date IS NOT NULL "
        "AND order_delivered_customer_date < order_purchase_timestamp"
    )
    _add("time_delivered_before_purchase", "时间异常", "签收时间早于下单时间的订单",
         "WARN" if bad > 0 else "PASS", bad, "物流时间戳为运营系统回填，存在少量异常；分析时不单独剔除")

    bad = _count(
        "SELECT COUNT(*) FROM raw_orders WHERE order_approved_at IS NOT NULL "
        "AND order_approved_at < order_purchase_timestamp"
    )
    _add("time_approved_before_purchase", "时间异常", "审核时间早于下单时间的订单",
         "WARN" if bad > 0 else "PASS", bad, "Olist 已知数据特点，漏斗分析按时间戳是否存在判定")

    # ---------------- 5. 数值异常 ----------------
    bad = _count("SELECT COUNT(*) FROM raw_order_items WHERE price <= 0")
    _add("num_price_nonpositive", "数值异常", "price <= 0 的明细行",
         "WARN" if bad > 0 else "PASS", bad)

    bad = _count("SELECT COUNT(*) FROM raw_order_items WHERE freight_value < 0")
    _add("num_freight_negative", "数值异常", "freight_value < 0 的明细行",
         "WARN" if bad > 0 else "PASS", bad)

    bad = _count("SELECT COUNT(*) FROM raw_order_payments WHERE payment_value <= 0")
    _add("num_payment_nonpositive", "数值异常", "payment_value <= 0 的支付记录",
         "WARN" if bad > 0 else "PASS", bad, "可能为全额券/赠品类支付")

    bad = _count("SELECT COUNT(*) FROM raw_order_reviews WHERE review_score < 1 OR review_score > 5")
    _add("num_review_out_of_range", "数值异常", "review_score 超出 1-5 范围",
         _verdict(bad), bad)

    # ---------------- 6. 粒度一致性（fan-out 防护） ----------------
    fct_rows = _count("SELECT COUNT(*) FROM fct_order")
    raw_rows = _count("SELECT COUNT(*) FROM raw_orders")
    _add("grain_fct_order_rows", "粒度一致性", "fct_order 行数 = raw_orders 行数（1 行 / order_id）",
         "PASS" if fct_rows == raw_rows else "FAIL", "%s / %s" % (f"{fct_rows:,}", f"{raw_rows:,}"))

    item_rows = _count("SELECT COUNT(*) FROM fct_order_item")
    raw_item_rows = _count("SELECT COUNT(*) FROM raw_order_items")
    _add("grain_fct_order_item_rows", "粒度一致性", "fct_order_item 行数 = raw_order_items 行数",
         "PASS" if item_rows == raw_item_rows else "FAIL", "%s / %s" % (f"{item_rows:,}", f"{raw_item_rows:,}"))

    sum_item_count = _count("SELECT SUM(item_count) FROM fct_order")
    _add("grain_item_count_sum", "粒度一致性", "fct_order.item_count 合计 = 明细行数",
         "PASS" if sum_item_count == raw_item_rows else "FAIL", "%s / %s" % (f"{sum_item_count:,}", f"{raw_item_rows:,}"))

    pay_fct = float(_scalar("SELECT SUM(payment_total) FROM fct_order") or 0)
    pay_raw = float(_scalar("SELECT SUM(payment_value) FROM raw_order_payments") or 0)
    _add("grain_payment_sum", "粒度一致性", "支付金额合计一致（防重复计算）",
         "PASS" if abs(pay_fct - pay_raw) < 0.01 else "FAIL",
         "R$ %s / R$ %s" % (f"{pay_fct:,.2f}", f"{pay_raw:,.2f}"))

    gmv_fct = float(_scalar("SELECT SUM(product_gmv) FROM fct_order") or 0)
    gmv_raw = float(_scalar("SELECT SUM(price) FROM raw_order_items") or 0)
    _add("grain_gmv_sum", "粒度一致性", "商品金额（GMV）合计一致",
         "PASS" if abs(gmv_fct - gmv_raw) < 0.01 else "FAIL",
         "R$ %s / R$ %s" % (f"{gmv_fct:,.2f}", f"{gmv_raw:,.2f}"))

    dim_rows = _count("SELECT COUNT(*) FROM dim_customer")
    dim_distinct = _count("SELECT COUNT(DISTINCT customer_unique_id) FROM dim_customer")
    _add("grain_dim_customer_unique", "粒度一致性", "dim_customer 每 customer_unique_id 仅 1 行",
         "PASS" if dim_rows == dim_distinct else "FAIL", "%s / %s" % (f"{dim_rows:,}", f"{dim_distinct:,}"))

    raw_reviews = _count("SELECT COUNT(*) FROM raw_order_reviews")
    stg_reviews = _count("SELECT COUNT(*) FROM stg_reviews")
    _add("grain_review_dedup", "粒度一致性", "stg_reviews 按订单去重（1 单多评价保留最新）",
         "WARN" if stg_reviews < raw_reviews else "PASS",
         "%s → %s（去重 %s 条）" % (f"{raw_reviews:,}", f"{stg_reviews:,}", f"{raw_reviews - stg_reviews:,}"),
         "保证订单粒度聚合不产生 fan-out")

    # ---------------- 7. 月份覆盖度 ----------------
    monthly = sql_engine.read_sql(
        "SELECT order_month, COUNT(*) AS n FROM fct_order GROUP BY order_month ORDER BY order_month"
    )
    sparse = monthly[monthly["n"] < 100]
    _add("month_coverage", "月份覆盖度", "订单量 < 100 的不完整月份",
         "WARN" if len(sparse) > 0 else "PASS",
         "、".join("%s（%d 单）" % (m[:7], n) for m, n in zip(sparse["order_month"], sparse["n"])) or "无",
         "趋势分析已限定 %s ~ %s" % (config.ANALYSIS_START_DATE, config.ANALYSIS_END_DATE))

    return pd.DataFrame([c.__dict__ for c in _CHECKS])


def write_csv(df: pd.DataFrame) -> Path:
    path = config.OUTPUTS_DIR / "data_quality_checks.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def write_markdown(df: pd.DataFrame) -> Path:
    counts = df["status"].value_counts().to_dict()
    lines = [
        "# 数据质量报告",
        "",
        "- 生成时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "- 数据库：`%s`" % config.DATABASE_URL,
        "- 分析时间窗：%s ~ %s（剔除首尾不完整月份）" % (config.ANALYSIS_START_DATE, config.ANALYSIS_END_DATE),
        "",
        "## 概览",
        "",
        "| 通过 | 警告 | 失败 |",
        "| --- | --- | --- |",
        "| %d | %d | %d |" % (counts.get("PASS", 0), counts.get("WARN", 0), counts.get("FAIL", 0)),
        "",
        "## 检查明细",
        "",
        "| 类别 | 检查项 | 状态 | 数值 | 说明 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for _, row in df.iterrows():
        lines.append(
            "| %s | %s | %s | %s | %s |"
            % (row["category"], row["name"], row["status"], row["value"], row["detail"] or "—")
        )
    lines += [
        "",
        "## 已知数据特点与处理口径",
        "",
        "1. **粒度**：一笔订单可含多个商品、多条支付、多条评价。所有事实表先预聚合到目标粒度再关联，",
        "   `fct_order`（1 行/订单）与 `fct_order_item`（1 行/明细）均通过行数与金额合计校验，无 fan-out。",
        "2. **评价去重**：同一订单存在多条评价时按最新回答时间保留 1 条（见 `grain_review_dedup`）。",
        "3. **品类缺失**：少量商品无品类，staging 层填充为 `unknown`，单独成组不剔除。",
        "4. **不完整月份**：2016-09/10/12 与 2018-09 之后订单量极少，趋势类分析限定在分析时间窗内。",
        "5. **时间戳异常**：少量订单审核/签收时间早于下单时间，为运营系统回填特点，不单独剔除，",
        "   漏斗分析按时间戳是否存在判定。",
        "6. **指标口径**：GMV = 商品金额（不含运费）；实收收入 = 支付金额（含运费）；两者不混用。",
        "",
        "## 结论",
        "",
    ]
    if counts.get("FAIL", 0) == 0:
        lines.append("全部关键检查通过（无 FAIL），数据集可用于后续分析；WARN 项为已知数据特点，已在报告中说明处理方式。")
    else:
        lines.append("存在 FAIL 项，请先修复再进入分析阶段：")
        for _, row in df[df["status"] == "FAIL"].iterrows():
            lines.append("- **%s**：%s（%s）" % (row["check_id"], row["name"], row["value"]))

    path = config.REPORTS_DIR / "data_quality_report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run() -> pd.DataFrame:
    df = run_checks()
    csv_path = write_csv(df)
    md_path = write_markdown(df)
    counts = df["status"].value_counts().to_dict()
    print("  质量检查：通过 %d / 警告 %d / 失败 %d" % (counts.get("PASS", 0), counts.get("WARN", 0), counts.get("FAIL", 0)))
    print("  明细 → %s" % csv_path)
    print("  报告 → %s" % md_path)
    return df


def main() -> int:
    df = run()
    return 1 if (df["status"] == "FAIL").any() else 0


if __name__ == "__main__":
    raise SystemExit(main())
