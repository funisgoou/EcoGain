"""任务 DTO（API 文档 §6.1）。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

TASK_STATUSES = {"queued", "running", "success", "failed", "cancelled"}


class TaskItem(BaseModel):
    task_id: int
    task_status: str
    current_step: str | None = None  # planning | querying | summarizing
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
