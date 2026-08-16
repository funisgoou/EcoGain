"""管理端 DTO（API 文档 §7）。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ReloadResp(BaseModel):
    status: str  # ok | error
    message: str


class TaskLogItem(BaseModel):
    log_level: str  # info | warn | error
    log_type: str  # llm_call | tool_exec | status | summary
    log_content: str
    created_at: datetime
