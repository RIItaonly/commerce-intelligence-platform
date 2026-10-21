"""端到端流水线：raw → staging → marts → analytics → 质量/洞察 → 模型与模型卡。

用法：
    python -m src.pipeline all                  # 全量（含 CSV 重新入库、模型训练）
    python -m src.pipeline staging marts analytics quality report   # 跳过入库与建模
    python -m src.pipeline churn segmentation recommender forecast modelcard
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import List

from src import config, sql_engine

STEPS = [
    "ingest", "staging", "marts", "analytics", "quality", "report",
    "experiment", "churn", "segmentation", "recommender", "forecast", "modelcard",
    "drift",
]


def step_ingest() -> None:
    from src.ingestion import load_raw

    load_raw.load_all()


def _run_sql_files(paths: List[Path]) -> None:
    conn = sql_engine.get_connection()
    try:
        for path in paths:
            count = sql_engine.execute_file(conn, path)
            print("  执行 %-32s（%d 条语句）" % (path.name, count))
    finally:
        conn.close()


def step_staging() -> None:
    _run_sql_files([config.SQL_DIR / "staging" / "01_staging_views.sql"])


def step_marts() -> None:
    _run_sql_files(sorted((config.SQL_DIR / "marts").glob("*.sql")))


def step_analytics() -> None:
    _run_sql_files(sorted((config.SQL_DIR / "analytics").glob("*.sql")))


def step_quality() -> None:
    from src.cleaning import quality_checks

    quality_checks.run()


def step_report() -> None:
    from src.reporting import build_business_report

    build_business_report.run()


def step_experiment() -> None:
    from src.experiment import run_experiment

    run_experiment.build_report()


def step_churn() -> None:
    from src.models import churn

    churn.run()


def step_segmentation() -> None:
    from src.models import segmentation

    segmentation.run()


def step_recommender() -> None:
    from src.models import recommender

    recommender.run()


def step_forecast() -> None:
    from src.models import forecasting

    forecasting.run()


def step_modelcard() -> None:
    from src.reporting import build_model_card

    build_model_card.build()


def step_drift() -> None:
    from src.monitoring import drift

    drift.run()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Commerce Intelligence Platform 流水线")
    parser.add_argument("steps", nargs="*", default=["all"], choices=STEPS + ["all"],
                        help="要执行的步骤，默认 all")
    args = parser.parse_args(argv)

    steps = STEPS if "all" in args.steps else args.steps
    print("数据库：%s" % config.DATABASE_URL)
    print("步骤：%s\n" % " → ".join(steps))

    started = time.time()
    for step in steps:
        tick = time.time()
        print("== %s ==" % step)
        globals()["step_%s" % step]()
        print("   用时 %.1f 秒\n" % (time.time() - tick))
    print("全部完成，总用时 %.1f 秒" % (time.time() - started))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
