"""Agent 状态定义（AGENT-1，结构与 DATA §6.4 一致）。"""
from __future__ import annotations

from typing import Any, TypedDict

from app.schemas.result import AnalysisResultModel


class AnalysisState(TypedDict):
    messages: list[Any]  # LangChain 消息序列（含 ToolMessage 回填）
    task_id: int
    conversation_id: int
    user_id: int
    trace_id: str
    attachment_schemas: list[dict]  # [{table, columns:[{name,type}], row_count}]
    text_attachments: list[dict]  # [{file_name, preview}]
    tool_rounds: int  # 已执行工具轮次（上限 max_tool_rounds）
    final_result: AnalysisResultModel | None  # output_node 产出
