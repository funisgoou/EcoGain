"""工具注册表：5 个工具的 schema 与执行函数统一出口。"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.analysis.state import AnalysisState
from app.analysis.tools.file_tools import (READ_SCHEMA, WRITE_SCHEMA,
                                           file_read_tool, file_write_tool)
from app.analysis.tools.gen_result import GEN_SCHEMA, generate_result_file_tool
from app.analysis.tools.sql_query import TOOL_SCHEMA as SQL_SCHEMA
from app.analysis.tools.sql_query import sql_query_tool
from app.analysis.tools.text_search import SEARCH_SCHEMA, text_search_tool

TOOL_REGISTRY: dict[str, Callable[..., Awaitable[str]]] = {
    "sql_query": sql_query_tool,
    "file_read": file_read_tool,
    "file_write": file_write_tool,
    "text_search": text_search_tool,
    "generate_result_file": generate_result_file_tool,
}

ALL_TOOLS: list[dict] = [
    SQL_SCHEMA, READ_SCHEMA, WRITE_SCHEMA, SEARCH_SCHEMA, GEN_SCHEMA,
]
