"""任务与结果路由（TASK-7 / RES-2 / RES-4）。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_config
from app.db.mysql import get_session
from app.models import User
from app.schemas.common import BizError, ok
from app.schemas.result import Evidence, KeyMetric
from app.schemas.task import TaskItem
from app.services import result_service, task_service

router = APIRouter(tags=["results"])


@router.get("/api/tasks/{task_id}")
async def route_get_task(
    task_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    task = await task_service.get_owned(session, user, task_id)
    return ok(TaskItem(
        task_id=task.id, task_status=task.task_status, current_step=task.current_step,
        started_at=task.started_at, finished_at=task.finished_at,
        error_message=task.error_message,
    ).model_dump(mode="json"))


@router.get("/api/results/{task_id}")
async def route_get_result(
    task_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await result_service.get_by_task(session, user, task_id)
    metrics = [KeyMetric(**m) for m in (json.loads(row.key_metrics_json) if isinstance(row.key_metrics_json, str) else row.key_metrics_json)]
    evidences = [Evidence(**e) for e in (json.loads(row.evidence_list_json) if isinstance(row.evidence_list_json, str) else row.evidence_list_json)]
    return ok({
        "problem_definition": row.problem_definition,
        "key_metrics": [m.model_dump() for m in metrics],
        "evidence_list": [e.model_dump() for e in evidences],
        "conclusion_text": row.conclusion_text,
        "missing_data_text": row.missing_data_text,
        "next_action_text": row.next_action_text,
        "result_markdown": row.result_markdown,
        "exported": row.result_file_path is not None,
    })


@router.get("/api/results/{task_id}/download")
async def route_download(
    task_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    if not get_config().export_enabled:  # CFG-5 开关
        raise BizError(40301, "导出功能已关闭")
    path = await result_service.ensure_export_file(session, user, task_id)
    return FileResponse(
        path, filename=f"result_{task_id}.md", media_type="text/markdown; charset=utf-8"
    )
