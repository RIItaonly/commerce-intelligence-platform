"""原始数据下载：从 Olist 官方 GitHub 仓库拉取 9 张 CSV。

用法：
    python -m src.ingestion.download_data           # 缺失文件才下载
    python -m src.ingestion.download_data --force   # 强制重新下载
    python -m src.ingestion.download_data --check   # 只校验本地文件完整性
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

from src import config

BASE_URL = "https://raw.githubusercontent.com/olist/work-at-olist-data/master/datasets"

# 官方仓库中各文件的行数量级与最小体积（字节），用于校验下载完整性
EXPECTED_MIN_SIZE = {
    "raw_orders": 15_000_000,
    "raw_order_items": 14_000_000,
    "raw_order_payments": 5_000_000,
    "raw_order_reviews": 13_000_000,
    "raw_customers": 8_000_000,
    "raw_products": 2_000_000,
    "raw_sellers": 150_000,
    "raw_geolocation": 50_000_000,
    "raw_category_translation": 2_000,
}


def download_file(filename: str, target: Path, force: bool = False) -> Path:
    if target.exists() and not force:
        print("  = 已存在，跳过 %s" % filename)
        return target
    print("  ↓ 下载 %s" % filename)
    response = requests.get("%s/%s" % (BASE_URL, filename), stream=True, timeout=300)
    response.raise_for_status()
    tmp_path = target.with_suffix(target.suffix + ".part")
    with tmp_path.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            handle.write(chunk)
    tmp_path.replace(target)
    return target


def check_files() -> int:
    """校验本地文件完整性，返回问题文件数。"""
    problems = 0
    for table, filename in config.RAW_FILES.items():
        path = config.RAW_DIR / filename
        if not path.exists():
            print("  ✗ 缺失 %s" % filename)
            problems += 1
            continue
        size = path.stat().st_size
        minimum = EXPECTED_MIN_SIZE.get(table, 0)
        if size < minimum:
            print("  ✗ 体积异常 %s (%s bytes < %s)" % (filename, size, minimum))
            problems += 1
        else:
            print("  ✓ %s (%.1f MB)" % (filename, size / 1024 / 1024))
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="下载 Olist 原始数据集")
    parser.add_argument("--force", action="store_true", help="强制重新下载")
    parser.add_argument("--check", action="store_true", help="只校验本地文件")
    args = parser.parse_args(argv)

    config.RAW_DIR.mkdir(parents=True, exist_ok=True)

    if args.check:
        problems = check_files()
        print("\n校验完成：%d 个文件异常" % problems)
        return 1 if problems else 0

    print("目标目录：%s" % config.RAW_DIR)
    for filename in config.RAW_FILES.values():
        try:
            download_file(filename, config.RAW_DIR / filename, force=args.force)
        except Exception as error:  # 网络失败不应静默
            print("  ! 下载失败 %s: %s" % (filename, error), file=sys.stderr)
            return 1

    problems = check_files()
    print("\n下载完成，%d 个文件异常" % problems)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
