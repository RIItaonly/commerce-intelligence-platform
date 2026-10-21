"""数据口径与 fan-out 防护测试（依赖已构建的 SQLite 数仓）。

这些断言固定了阶段 1 的关键数字；如果上游 SQL 改动导致重复计数，测试会立刻失败。
"""
import pytest

from src import config, sql_engine

pytestmark = pytest.mark.skipif(
    not (config.WAREHOUSE_DIR / "commerce.db").exists(),
    reason="数据仓库不存在，需先运行流水线（CI 环境跳过）",
)


def test_fct_order_grain_is_one_row_per_order():
    rows = sql_engine.query_scalar("SELECT COUNT(*) FROM fct_order")
    distinct = sql_engine.query_scalar("SELECT COUNT(DISTINCT order_id) FROM fct_order")
    assert rows == distinct == 99_441


def test_payment_total_matches_baseline():
    total = sql_engine.query_scalar("SELECT SUM(payment_total) FROM fct_order")
    assert total == pytest.approx(16_008_872.12, abs=0.5)


def test_product_gmv_matches_baseline():
    total = sql_engine.query_scalar("SELECT SUM(product_gmv) FROM fct_order")
    assert total == pytest.approx(13_591_643.70, abs=0.5)


def test_order_item_grain():
    rows = sql_engine.query_scalar("SELECT COUNT(*) FROM fct_order_item")
    distinct = sql_engine.query_scalar(
        "SELECT COUNT(*) FROM (SELECT DISTINCT order_id, order_item_id FROM fct_order_item)"
    )
    assert rows == distinct == 112_650


def test_valid_order_window_matches_phase_two():
    result = sql_engine.read_sql(
        """
        SELECT
            COUNT(*) AS orders,
            SUM(is_valid_order) AS valid_orders,
            SUM(CASE WHEN is_valid_order = 1 THEN payment_total ELSE 0 END) AS revenue
        FROM fct_order
        WHERE order_month BETWEEN '2017-01-01' AND '2018-08-01'
        """
    ).iloc[0]
    assert int(result["orders"]) == 99_092
    assert int(result["valid_orders"]) == 97_910
    assert float(result["revenue"]) == pytest.approx(15_687_157, abs=50)


def test_revenue_is_not_fanned_out_by_items():
    """订单粒度收入应等于支付表的聚合收入（而不是商品明细行数级别的重复求和）。"""
    order_level = sql_engine.query_scalar(
        "SELECT SUM(payment_total) FROM fct_order WHERE is_valid_order = 1"
    )
    payment_level = sql_engine.query_scalar(
        "SELECT SUM(payment_value) FROM stg_payments p "
        "JOIN stg_orders o ON o.order_id = p.order_id WHERE o.is_valid_order = 1"
    )
    assert order_level == pytest.approx(payment_level, abs=0.5)
