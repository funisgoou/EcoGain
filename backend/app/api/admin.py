"""管理路由（CFG-2 配置热更新 / CFG-3 任务日志）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.mysql import get_engine, get_session
from app.models import User
from app.core.config import reload_config
from app.schemas.admin import ReloadResp, TaskLogItem
from app.schemas.common import ok
from app.services import task_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/reload")
async def route_reload(
    _user: User = Depends(require_admin),
    _session: AsyncSession = Depends(get_session),
) -> dict:
    result = await reload_config(get_engine())
    return ok(ReloadResp(status=result.status, message=result.message).model_dump())


@router.get("/tasks/{task_id}/logs")
async def route_task_logs(
    task_id: int,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _ = user
    logs = await task_service.get_logs(session, task_id)
    return ok([
        TaskLogItem(
            log_level=l.log_level, log_type=l.log_type,
            log_content=l.log_content, created_at=l.created_at,
        ).model_dump(mode="json") for l in logs
    ])
