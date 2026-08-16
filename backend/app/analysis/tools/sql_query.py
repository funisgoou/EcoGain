"""sql_query 工具（AGENT-3）：只读 SQL 执行。"""
from __future__ import annotations

from datetime import datetime

from app.analysis.state import AnalysisState
from app.core.config import get_config
from app.core.logging import get_logger
from app.core.security import SqlRejected, validate_sql, wrap_limit
from app.db.duckdb import get_duckdb
from app.services import task_service

log = get_logger(__name__)

TOOL_DESC = "对 DuckDB 分析库执行只读查询（业务数据+附件导入表）。仅 SELECT/WITH/SHOW/DESCRIBE；返回列名+行数据。"

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "sql_query",
        "description": TOOL_DESC,
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "单条只读 SQL 查询语句（DuckDB 方言）"}
            },
            "required": ["sql"],
        },
    },
}


def format_rows_compact(columns: list[str], rows: list[tuple], truncated: bool) -> str:
    """紧凑文本序列化：列名行 + 每行数据（截断标记）。"""
    lines = [" | ".join(columns)]
    lines.append("-" * min(80, max(20, len(lines[0]))))
    for r in rows[:100]:  # 回传 Agent 再截 100 行（row_limit 只管执行层）
        lines.append(" | ".join("NULL" if v is None else str(v) for v in r))
    if truncated:
        lines.append(f"...（结果超出行数上限，已截断；共返回 {len(rows)} 行）")
    return "\n".join(lines)


async def sql_query_tool(state: AnalysisState, sql: str) -> str:
    cfg = get_config()
    validated = validate_sql(sql)  # core.security → AGENT-3 闸门
    if isinstance(validated, SqlRejected):
        return f"[50002] {validated.reason}。请修改后重试。"  # 拒绝原因回传（不抛异常）
    final_sql = wrap_limit(validated, cfg.sql_row_limit)
    duck = get_duckdb()
    t0 = datetime.now()
    qr = await duck.execute_query(final_sql, cfg.sql_timeout_seconds, cfg.sql_row_limit)
    elapsed_ms = int((datetime.now() - t0).total_seconds() * 1000)
    await task_service.log_record(
        state["task_id"], "info" if not qr.error else "warn", "tool_exec",
        f"sql_query {elapsed_ms}ms rows={len(qr.rows)} sql={sql[:200]}",
    )
    if qr.error:
        return f"执行失败：{qr.error}"  # 超时/报错同样回传 Agent 供修正
    return format_rows_compact(qr.columns, qr.rows, qr.truncated)
