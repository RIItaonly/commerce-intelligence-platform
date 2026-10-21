"""原始 CSV 入库：写 raw_* 表。

设计要点：
1. 显式声明每张表的列顺序，和 `sql/staging/00_schema.sql` 的 DDL 严格一致；
2. 时间列统一转成 ISO 字符串（`YYYY-MM-DD HH:MM:SS`），保证 SQLite `julianday/strftime`
   与 Postgres `TIMESTAMP` 都可直接使用；
3. 空字符串 → NULL，避免把 '' 写进数值列；
4. 分块写入，避免 100 万行地理表撑爆内存。

用法：
    python -m src.ingestion.load_raw              # 全量入库
    python -m src.ingestion.load_raw --tables raw_orders raw_customers
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List

import pandas as pd

from src import config, sql_engine

# 每张表的列顺序（与 00_schema.sql 一致）
COLUMNS: Dict[str, List[str]] = {
    "raw_orders": [
        "order_id",
        "customer_id",
        "order_status",
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ],
    "raw_order_items": [
        "order_id",
        "order_item_id",
        "product_id",
        "seller_id",
        "shipping_limit_date",
        "price",
        "freight_value",
    ],
    "raw_order_payments": [
        "order_id",
        "payment_sequential",
        "payment_type",
        "payment_installments",
        "payment_value",
    ],
    "raw_order_reviews": [
        "review_id",
        "order_id",
        "review_score",
        "review_comment_title",
        "review_comment_message",
        "review_creation_date",
        "review_answer_timestamp",
    ],
    "raw_customers": [
        "customer_id",
        "customer_unique_id",
        "customer_zip_code_prefix",
        "customer_city",
        "customer_state",
    ],
    "raw_products": [
        "product_id",
        "product_category_name",
        "product_name_length",
        "product_description_length",
        "product_photos_qty",
        "product_weight_g",
        "product_length_cm",
        "product_height_cm",
        "product_width_cm",
    ],
    "raw_sellers": [
        "seller_id",
        "seller_zip_code_prefix",
        "seller_city",
        "seller_state",
    ],
    "raw_geolocation": [
        "geolocation_zip_code_prefix",
        "geolocation_lat",
        "geolocation_lng",
        "geolocation_city",
        "geolocation_state",
    ],
    "raw_category_translation": [
        "product_category_name",
        "product_category_name_english",
    ],
}

# 原始 CSV 中需要改名的历史字段（官方数据里是 lenght 拼写）
CSV_RENAMES: Dict[str, Dict[str, str]] = {
    "raw_products": {
        "product_name_lenght": "product_name_length",
        "product_description_lenght": "product_description_length",
    }
}

TIMESTAMP_COLUMNS: Dict[str, List[str]] = {
    "raw_orders": [
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ],
    "raw_order_items": ["shipping_limit_date"],
    "raw_order_reviews": ["review_creation_date", "review_answer_timestamp"],
}

NUMERIC_COLUMNS: Dict[str, List[str]] = {
    "raw_order_items": ["price", "freight_value"],
    "raw_order_payments": ["payment_value"],
    "raw_geolocation": ["geolocation_lat", "geolocation_lng"],
}

INTEGER_COLUMNS: Dict[str, List[str]] = {
    "raw_orders": [],
    "raw_order_items": ["order_item_id"],
    "raw_order_payments": ["payment_sequential", "payment_installments"],
    "raw_order_reviews": ["review_score"],
    "raw_customers": ["customer_zip_code_prefix"],
    "raw_products": [
        "product_name_length",
        "product_description_length",
        "product_photos_qty",
        "product_weight_g",
        "product_length_cm",
        "product_height_cm",
        "product_width_cm",
    ],
    "raw_sellers": ["seller_zip_code_prefix"],
    "raw_geolocation": ["geolocation_zip_code_prefix"],
}

CHUNK_SIZE = 200_000


def _to_iso_timestamp(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce")
    return parsed.dt.strftime("%Y-%m-%d %H:%M:%S").where(parsed.notna(), None)


def _clean_frame(table: str, frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.rename(columns=CSV_RENAMES.get(table, {}))

    missing = [column for column in COLUMNS[table] if column not in frame.columns]
    if missing:
        raise ValueError("表 %s 缺少列：%s" % (table, missing))

    frame = frame[COLUMNS[table]].copy()

    for column in TIMESTAMP_COLUMNS.get(table, []):
        frame[column] = _to_iso_timestamp(frame[column])

    for column in NUMERIC_COLUMNS.get(table, []):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    for column in INTEGER_COLUMNS.get(table, []):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")

    for column in frame.columns:
        if frame[column].dtype == object:
            frame[column] = frame[column].astype("string").replace({"": None})

    return frame


def _native_records(frame: pd.DataFrame):
    """把 DataFrame 转成纯 Python 类型的行元组。

    必要性：sqlite3 只能绑定 Python 原生类型。pandas 的 Int64/Float64 标量会被
    当作 buffer 绑成 BLOB，导致 AVG/SUM 等聚合失效（本项目实测踩过这个坑）。
    """
    frame = frame.astype(object).where(pd.notna(frame), None)
    return [row for row in frame.itertuples(index=False, name=None)]


def _insert_chunks(conn, table: str, frame: pd.DataFrame) -> int:
    if sql_engine.dialect() == "postgres":
        return sql_engine.write_dataframe(conn, frame, table, if_exists="append")

    placeholders = ", ".join(["?"] * len(frame.columns))
    column_sql = ", ".join(frame.columns)
    statement = "INSERT OR REPLACE INTO %s (%s) VALUES (%s)" % (table, column_sql, placeholders)
    total = 0
    for start in range(0, len(frame), CHUNK_SIZE):
        chunk = frame.iloc[start : start + CHUNK_SIZE]
        rows = _native_records(chunk)
        conn.executemany(statement, rows)
        total += len(rows)
    conn.commit()
    return total


def load_table(conn, table: str, path: Path, chunksize: int = 500_000) -> int:
    print("  载入 %s ← %s" % (table, path.name))
    rows_loaded = 0
    reader = pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
        na_values=[""],
        chunksize=chunksize,
        low_memory=False,
    )
    for chunk in reader:
        frame = _clean_frame(table, chunk)
        rows_loaded += _insert_chunks(conn, table, frame)
    print("    → %s 行" % format(rows_loaded, ","))
    return rows_loaded


def load_all(tables: List[str] | None = None) -> Dict[str, int]:
    tables = tables or list(config.RAW_FILES.keys())
    if not config.LOAD_GEOLOCATION and "raw_geolocation" in tables:
        tables = [table for table in tables if table != "raw_geolocation"]
        print("  跳过 raw_geolocation（设置 LOAD_GEOLOCATION=true 可开启）")

    conn = sql_engine.get_connection()
    stats: Dict[str, int] = {}
    try:
        sql_engine.execute_file(conn, config.SQL_DIR / "staging" / "00_schema.sql")
        if sql_engine.dialect() == "sqlite":
            for table in tables:
                conn.execute("DELETE FROM %s" % table)
            conn.commit()
        for table in tables:
            path = config.RAW_DIR / config.RAW_FILES[table]
            if not path.exists():
                raise FileNotFoundError(
                    "缺少原始文件 %s，请先执行：python -m src.ingestion.download_data" % path
                )
            stats[table] = load_table(conn, table, path)
        if sql_engine.dialect() == "sqlite":
            conn.commit()
            conn.execute("VACUUM")
    finally:
        conn.close()
    return stats


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="把 Olist 原始 CSV 写入 raw_* 表")
    parser.add_argument("--tables", nargs="*", default=None, help="只载入指定表")
    args = parser.parse_args(argv)

    print("数据库：%s" % config.DATABASE_URL)
    stats = load_all(args.tables)
    print("\n入库完成：")
    for table, rows in stats.items():
        print("  %-26s %10s 行" % (table, format(rows, ",")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
