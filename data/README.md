# data/

```
data/
├── raw/         # 原始 CSV（Olist 9 张表，约 123MB，已 gitignore）
├── interim/     # 中间产物（清洗后的 parquet/csv）
└── warehouse/   # 本地 SQLite 数仓文件 commerce.db（已 gitignore）
```

## 原始数据获取

```powershell
python -m src.ingestion.download_data          # 从官方仓库下载 9 个 CSV
python -m src.ingestion.download_data --check  # 只校验本地文件是否完整
```

| 文件 | 行数量级 | 粒度 |
| --- | --- | --- |
| olist_orders_dataset.csv | 99441 | order_id |
| olist_order_items_dataset.csv | 112650 | (order_id, order_item_id) |
| olist_order_payments_dataset.csv | 103886 | (order_id, payment_sequential) |
| olist_order_reviews_dataset.csv | 99224 | review_id |
| olist_customers_dataset.csv | 99441 | customer_id（订单级） |
| olist_products_dataset.csv | 32951 | product_id |
| olist_sellers_dataset.csv | 3095 | seller_id |
| olist_geolocation_dataset.csv | 1000163 | zip_code_prefix（可重复，默认不导入） |
| product_category_name_translation.csv | 71 | category_name |

> 数据为公开数据集，仅用于分析演示；仓库不提交 CSV 本体，克隆后按上面的命令重新下载即可复现。
