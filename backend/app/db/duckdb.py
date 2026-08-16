"""DuckDB 单例与读写锁（AGENT-3 查询 / ATT-3 导入 / ATT-6 删表）。

实现决策（SPEC 4.6）：单 Database 实例（读写模式）+ 全局 asyncio.Lock 串行写
+ Agent 查询走语句级只读校验（core.security.validate_sql）。
DuckDB Python API 是同步的，全部调用丢进 asyncio.to_thread 防阻塞事件循环。
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import duckdb

from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class QueryResult:
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    truncated: bool = False
    error: str | None = None


class DuckDBManager:
    """进程内唯一读写连接。查询（sql_query 工具）与写（附件导入/删表）共用，
    写走 write_txn 串行化；查询本身只读、由语句级校验保证安全。"""

    def __init__(self, db_path: str):
        self._write_lock = asyncio.Lock()
        self._conn = duckdb.connect(db_path)

    # ---- 查询（Agent sql_query 专用）----
    async def execute_query(self, sql: str, timeout_s: int, row_limit: int = 1000) -> QueryResult:
        try:
            rel = await asyncio.wait_for(
                asyncio.to_thread(self._conn.sql, sql), timeout_s
            )
            columns = list(rel.columns)
            all_rows = await asyncio.to_thread(rel.fetchall)
            return QueryResult(
                columns=columns,
                rows=all_rows[:row_limit],
                truncated=len(all_rows) > row_limit,
            )
        except asyncio.TimeoutError:
            # 超时不可真正 kill duckdb 线程；SELECT 只读无副作用，POC 接受
            log.warning("sql_timeout", timeout_s=timeout_s)
            return QueryResult(error=f"SQL 执行超过 {timeout_s}s 超时")
        except duckdb.Error as e:
            return QueryResult(error=f"SQL 执行错误：{e}")

    # ---- 写（附件导入/DROP 表，后台链路专用）----
    @asynccontextmanager
    async def write_txn(self):
        async with self._write_lock:  # 串行化所有写
            yield self._conn  # 调用方在 to_thread 中执行 DDL/DML

    def close(self) -> None:
        self._conn.close()


_manager: DuckDBManager | None = None


def init_duckdb(db_path: str) -> DuckDBManager:
    global _manager
    if _manager is not None:
        return _manager
    _manager = DuckDBManager(db_path)
    return _manager


def get_duckdb() -> DuckDBManager:
    if _manager is None:
        raise RuntimeError("DuckDB 未初始化（init_duckdb 未调用）")
    return _manager


def duckdb_ping() -> bool:
    try:
        if _manager is None:
            return False
        _manager._conn.execute("SELECT 1")  # noqa: SLF001 —— 单例内部探针
        return True
    except Exception:  # noqa: BLE001 —— 健康检查吞异常
        return False


def list_attachment_tables(conn: duckdb.DuckDBPyConnection) -> list[str]:
    """遍历 information_schema，供会话删除时批量 DROP。"""
    try:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'attachments'"
        ).fetchall()
        return [r[0] for r in rows]
    except duckdb.Error:
        return []
