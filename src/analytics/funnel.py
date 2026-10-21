"""订单履约漏斗：下单 → 审核 → 支付 → 发货 → 签收 → 评价。

数据来源：sql/analytics/09_funnel.sql → analytics_order_funnel（单行汇总）。
注意：Olist 没有曝光/点击/加购日志，漏斗只能从下单开始；各阶段按时间戳是否
存在判定，已取消订单也可能到达过部分阶段，因此阶段间不是严格单调的子集关系。
"""
from __future__ import annotations

import pandas as pd

from src import sql_engine

_STAGES = [
    ("orders_total", "下单"),
    ("orders_approved", "审核通过"),
    ("orders_paid", "产生支付"),
    ("orders_shipped", "发货"),
    ("orders_delivered", "签收"),
    ("orders_reviewed", "收到评价"),
]


def order_funnel() -> pd.DataFrame:
    """返回长表：stage / label / orders / rate_of_total / rate_of_prev。"""
    row = sql_engine.read_sql("SELECT * FROM analytics_order_funnel").iloc[0]
    records = []
    previous = None
    total = float(row["orders_total"])
    for column, label in _STAGES:
        value = float(row[column])
        records.append(
            {
                "stage": column,
                "label": label,
                "orders": int(value),
                "rate_of_total": value / total if total else 0.0,
                "rate_of_prev": value / previous if previous else 1.0,
            }
        )
        previous = value
    df = pd.DataFrame(records)
    df["canceled"] = int(row["orders_canceled"])
    df["unavailable"] = int(row["orders_unavailable"])
    return df
