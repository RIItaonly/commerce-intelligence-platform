"""项目级配置：路径、数据库连接、分析时间窗。

所有路径基于项目根目录推导，因此脚本可以在任意工作目录下运行。
配置优先级：环境变量 > 项目根目录 .env > 默认值。
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_env_file(path: Path) -> None:
    """极简 .env 读取（避免额外依赖 python-dotenv）。"""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(ROOT / ".env")


def _path(env_key: str, default: str) -> Path:
    return (ROOT / os.environ.get(env_key, default)).resolve()


RAW_DIR = _path("RAW_DATA_DIR", "data/raw")
INTERIM_DIR = _path("INTERIM_DATA_DIR", "data/interim")
WAREHOUSE_DIR = _path("WAREHOUSE_DIR", "data/warehouse")
SQL_DIR = ROOT / "sql"
REPORTS_DIR = ROOT / "reports"
OUTPUTS_DIR = ROOT / "outputs"
SCREENSHOT_DIR = OUTPUTS_DIR / "screenshots"
MODEL_DIR = ROOT / "models" / "artifacts"

for _directory in (
    RAW_DIR,
    INTERIM_DIR,
    WAREHOUSE_DIR,
    REPORTS_DIR,
    OUTPUTS_DIR,
    SCREENSHOT_DIR,
    MODEL_DIR,
):
    _directory.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip() or (
    "sqlite:///" + (WAREHOUSE_DIR / "commerce.db").as_posix()
)

LOAD_GEOLOCATION = os.environ.get("LOAD_GEOLOCATION", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Olist 首尾月份数据不完整，趋势类分析默认剔除
ANALYSIS_START_DATE = os.environ.get("ANALYSIS_START_DATE", "2017-01-01")
ANALYSIS_END_DATE = os.environ.get("ANALYSIS_END_DATE", "2018-08-31")

# 原始 CSV 文件名（含官方仓库中使用频率写作 lenght 的历史字段）
RAW_FILES = {
    "raw_orders": "olist_orders_dataset.csv",
    "raw_order_items": "olist_order_items_dataset.csv",
    "raw_order_payments": "olist_order_payments_dataset.csv",
    "raw_order_reviews": "olist_order_reviews_dataset.csv",
    "raw_customers": "olist_customers_dataset.csv",
    "raw_products": "olist_products_dataset.csv",
    "raw_sellers": "olist_sellers_dataset.csv",
    "raw_geolocation": "olist_geolocation_dataset.csv",
    "raw_category_translation": "product_category_name_translation.csv",
}
