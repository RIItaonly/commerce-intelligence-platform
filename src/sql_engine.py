"""跨引擎 SQL 执行层。

项目内 `sql/` 目录下的 SQL 统一以 **PostgreSQL 方言**书写（这是简历/生产栈的目标），
本模块负责在本地零安装场景下把它适配到 SQLite 执行：

1. 连接管理：`DATABASE_URL` 为 sqlite 时用 sqlite3（默认），为 postgresql 时用 psycopg2。
2. 方言适配：
   - `DATE_TRUNC('month', ts)` → SQLite `strftime('%Y-%m-01', ts)`
   - `DAYS_BETWEEN(a, b)`       → SQLite `julianday(a) - julianday(b)`
   - `ILIKE`                    → SQLite `LIKE`（SQLite 的 LIKE 本身不区分大小写）

只适配实际用到的语法，保持 SQL 文件本身可读、可迁移。
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence

import pandas as pd

from src import config

_DATE_TRUNC_UNITS = {
    "day": "date({0})",
    "week": "strftime('%Y-W%W', {0})",
    "month": "strftime('%Y-%m-01', {0})",
    "quarter": (
        "(strftime('%Y', {0}) || '-Q' || "
        "CAST((CAST(strftime('%m', {0}) AS INTEGER) + 2) / 3 AS TEXT))"
    ),
    "year": "strftime('%Y-01-01', {0})",
}

_DATE_TRUNC_RE = re.compile(r"DATE_TRUNC\s*\(\s*'(\w+)'\s*,\s*([^()]+?)\s*\)", re.IGNORECASE)
_DAYS_BETWEEN_RE = re.compile(r"DAYS_BETWEEN\s*\(\s*([^,()]+?)\s*,\s*([^()]+?)\s*\)", re.IGNORECASE)
_MONTH_INDEX_RE = re.compile(r"MONTH_INDEX\s*\(\s*([^()]+?)\s*\)", re.IGNORECASE)


def dialect() -> str:
    return "postgres" if config.DATABASE_URL.startswith("postgres") else "sqlite"


def sqlite_path() -> Path:
    url = config.DATABASE_URL
    if url.startswith("sqlite:///"):
        return Path(url.replace("sqlite:///", "", 1))
    raise ValueError("DATABASE_URL 不是 sqlite:/// 形式：%s" % url)


def translate(sql: str, target: Optional[str] = None) -> str:
    """把 PostgreSQL 方言的 SQL 翻译为 `target` 方言（默认当前引擎）。"""
    target = target or dialect()
    if target == "postgres":
        return sql

    def _date_trunc(match: re.Match) -> str:
        unit = match.group(1).lower()
        expr = match.group(2).strip()
        template = _DATE_TRUNC_UNITS.get(unit)
        if template is None:
            return match.group(0)
        return template.format(expr)

    def _days_between(match: re.Match) -> str:
        left = match.group(1).strip()
        right = match.group(2).strip()
        return "(julianday({0}) - julianday({1}))".format(left, right)

    def _month_index(match: re.Match) -> str:
        expr = match.group(1).strip()
        return (
            "(CAST(strftime('%Y', {0}) AS INTEGER) * 12 + CAST(strftime('%m', {0}) AS INTEGER))"
        ).format(expr)

    translated = _DATE_TRUNC_RE.sub(_date_trunc, sql)
    translated = _DAYS_BETWEEN_RE.sub(_days_between, translated)
    translated = _MONTH_INDEX_RE.sub(_month_index, translated)
    translated = re.sub(r"\bSTRING_AGG\b", "group_concat", translated, flags=re.IGNORECASE)
    translated = re.sub(r"\bILIKE\b", "LIKE", translated, flags=re.IGNORECASE)
    return translated


def get_connection():
    """返回数据库连接（sqlite3.Connection 或 psycopg2 connection）。"""
    if dialect() == "postgres":
        import psycopg2  # 仅在 Postgres 模式下需要

        return psycopg2.connect(config.DATABASE_URL)
    path = sqlite_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA synchronous = OFF")
    return conn


def _split_statements(script: str, conn) -> Iterable[str]:
    """按语句切分 SQL 脚本，兼容 sqlite（忽略注释与字符串中的分号）。"""
    if isinstance(conn, sqlite3.Connection):
        buffer = ""
        for line in script.splitlines(keepends=True):
            buffer += line
            if sqlite3.complete_statement(buffer):
                statement = buffer.strip()
                if statement:
                    yield statement
                buffer = ""
        if buffer.strip():
            yield buffer.strip()
    else:
        for statement in script.split(";"):
            if statement.strip():
                yield statement.strip()


def execute(conn, sql: str, params: Optional[Sequence[Any]] = None) -> None:
    """执行单条 SQL（自动做方言适配）。"""
    statement = translate(sql)
    if isinstance(conn, sqlite3.Connection):
        conn.execute(statement, params or ())
    else:
        with conn.cursor() as cursor:
            cursor.execute(statement, params or ())


def execute_file(conn, path: Path) -> int:
    """执行 .sql 文件，返回执行的语句数。"""
    script = Path(path).read_text(encoding="utf-8")
    count = 0
    if isinstance(conn, sqlite3.Connection):
        for statement in _split_statements(script, conn):
            conn.execute(translate(statement))
            count += 1
        conn.commit()
    else:
        with conn.cursor() as cursor:
            cursor.execute(script)
        conn.commit()
        count = 1
    return count


def read_sql(sql: str, params: Optional[Sequence[Any]] = None, conn=None) -> pd.DataFrame:
    """执行查询并返回 DataFrame（自动做方言适配）。"""
    owns_connection = conn is None
    conn = conn or get_connection()
    try:
        statement = translate(sql)
        if isinstance(conn, sqlite3.Connection):
            return pd.read_sql_query(statement, conn, params=params)
        return pd.read_sql_query(statement, conn, params=params)
    finally:
        if owns_connection:
            conn.close()


def query_scalar(sql: str, params: Optional[Sequence[Any]] = None) -> Any:
    df = read_sql(sql, params=params)
    if df.empty:
        return None
    return df.iloc[0, 0]


def table_exists(conn, table: str) -> bool:
    if isinstance(conn, sqlite3.Connection):
        sql = "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name = ?"
        cursor = conn.execute(sql, (table,))
    else:
        sql = (
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
            "AND table_name = %s"
        )
        cursor = conn.cursor()
        cursor.execute(sql, (table,))
    return cursor.fetchone() is not None


def write_dataframe(conn, df: pd.DataFrame, table: str, if_exists: str = "replace") -> int:
    """把 DataFrame 写入表。sqlite 走 pandas.to_sql，postgres 走 executemany。"""
    if isinstance(conn, sqlite3.Connection):
        df.to_sql(table, conn, if_exists=if_exists, index=False)
        conn.commit()
        return len(df)

    columns = list(df.columns)
    placeholders = ", ".join(["%s"] * len(columns))
    column_sql = ", ".join('"%s"' % column for column in columns)
    if if_exists == "replace":
        execute(conn, 'DROP TABLE IF EXISTS "%s"' % table)
    execute(conn, 'CREATE TABLE IF NOT EXISTS "%s" (%s)' % (table, column_sql))
    rows = [tuple(None if pd.isna(value) else value for value in row) for row in df.itertuples(index=False)]
    with conn.cursor() as cursor:
        cursor.executemany('INSERT INTO "%s" (%s) VALUES (%s)' % (table, column_sql, placeholders), rows)
    conn.commit()
    return len(rows)


def list_tables(conn) -> List[str]:
    if isinstance(conn, sqlite3.Connection):
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
        )
        return [row[0] for row in cursor.fetchall()]
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1"
        )
        return [row[0] for row in cursor.fetchall()]


def run_sql_directory(conn, directory: Path) -> List[str]:
    """按文件名顺序执行目录下所有 .sql 文件，返回已执行文件列表。"""
    executed: List[str] = []
    for path in sorted(Path(directory).glob("*.sql")):
        execute_file(conn, path)
        executed.append(path.name)
    return executed
