"""任务业务（TASK-1~7）：五态机、取消/超时熔断、僵尸恢复、运行日志。"""
from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_config
from app.core.logging import TraceCtx, get_logger
from app.db.mysql import get_engine, new_session
from app.models import AnalysisTask, TaskLog
from app.schemas import ws as wsmsg
from app.schemas.common import BizError
from app.ws.manager import MANAGER

log = get_logger(__name__)

MAX_GLOBAL_CONCURRENT = 5  # TASK-2：全局 queued+running 上限（POC 约定）


async def start_task(user_id: int, conversation_id: int, text: str,
                     attachment_ids: list[int]) -> AnalysisTask:
    """TASK-1：建任务 → 落 user 消息 → 推 message_start/queued → spawn run_task。"""
    from app.services import message_service

    async with new_session() as session, session.begin():
        task = AnalysisTask(
            conversation_id=conversation_id,
            user_id=user_id,
            input_text=text,
            attachment_ids=",".join(map(str, attachment_ids)) if attachment_ids else None,
            task_status="queued",
            trace_id=TraceCtx.current_trace_id() or TraceCtx.start(),
        )
        session.add(task)
        await session.flush()
        msg = await message_service.append_message(
            session, conversation_id, "user", "text", text,
            task_id=task.id, attachment_ids=attachment_ids,
        )
        task_id, msg_id = task.id, msg.id

    await MANAGER.broadcast(conversation_id, wsmsg.msg_message_start(task_id, conversation_id, msg_id))
    await MANAGER.broadcast(conversation_id, wsmsg.msg_task_status(task_id, "queued", None))
    RUNNING[task_id] = asyncio.create_task(run_task(task_id))
    return task


# 运行中任务表（task_id → asyncio.Task），供取消（TASK-3）
RUNNING: dict[int, asyncio.Task] = {}


async def run_task(task_id: int) -> None:
    """TASK-1 状态机 + TASK-4 超时 + TASK-6 日志。asyncio.wait_for 包整体。"""
    from app.analysis.graph import execute_analysis

    async with new_session() as session:
        task = await session.get(AnalysisTask, task_id)
    if task is None:
        log.error("task_not_found", task_id=task_id)
        return
    cid, uid = task.conversation_id, task.user_id
    TraceCtx.bind_task(task_id)
    TraceCtx.bind_conversation(cid)
    try:
        task.task_status = "running"
        task.started_at = datetime.now()
        await _commit_task(task)
        await MANAGER.broadcast(cid, wsmsg.msg_task_status(task_id, "running", "planning"))
        await log_record(task_id, "info", "status", "queued → running")
        async with new_session() as session:
            fresh = await session.get(AnalysisTask, task_id)
        result = await asyncio.wait_for(
            execute_analysis(fresh), timeout=get_config().task_timeout_seconds
        )
        task.task_status = "success"
        task.finished_at = datetime.now()
        await _commit_task(task)
        await MANAGER.broadcast(cid, wsmsg.msg_task_status(task_id, "success", None))
        await log_record(task_id, "info", "status", "task success")
        _ = result  # 结果落库在 execute_analysis 内完成（RES-1）
    except asyncio.TimeoutError:
        aio_task = RUNNING.get(task_id)
        if aio_task and aio_task is not asyncio.current_task():
            aio_task.cancel()  # 掐内部协程
        await _finish_failed(task, 50003, "任务执行超时")
    except asyncio.CancelledError:
        task.task_status = "cancelled"
        task.finished_at = datetime.now()
        await _commit_task(task)
        await MANAGER.broadcast(cid, wsmsg.msg_task_status(task_id, "cancelled", None))
        await log_record(task_id, "info", "status", "task cancelled")
        RUNNING.pop(task_id, None)
        raise
    except BizError as e:  # 如结构化输出不合规（AGENT-7）
        await _finish_failed(task, e.code, e.message)
    except Exception as e:  # noqa: BLE001 —— 任务级兜底
        log.error("task_failed_unexpected", task_id=task_id, error=str(e))
        await _finish_failed(task, 50000, f"任务执行失败：{e}")
    finally:
        RUNNING.pop(task_id, None)
        await MANAGER.broadcast(cid, wsmsg.msg_done(task_id, datetime.now().isoformat(timespec="milliseconds")))


async def _commit_task(task: AnalysisTask) -> None:
    async with new_session() as session, session.begin():
        await session.merge(task)


async def _finish_failed(task: AnalysisTask, code: int, message: str) -> None:
    task.task_status = "failed"
    task.finished_at = datetime.now()
    task.error_message = message
    await _commit_task(task)
    await MANAGER.broadcast(
        task.conversation_id, wsmsg.msg_error(task.id, code, message)
    )
    await MANAGER.broadcast(
        task.conversation_id, wsmsg.msg_task_status(task.id, "failed", None)
    )
    await log_record(task.id, "error", "status", f"task failed[{code}]: {message}")


async def cancel_task(session: AsyncSession, user_id: int, task_id: int) -> None:
    """TASK-3（WS cancel 上行）：归属校验 → asyncio.cancel；已终态任务忽略（幂等）。"""
    task = await get_owned(session, user_id, task_id)
    if task.task_status in AnalysisTask.ACTIVE_STATUSES:
        aio_task = RUNNING.get(task_id)
        if aio_task is not None:
            aio_task.cancel()  # CancelledError 在 await 点中断执行链


async def cancel_if_active(session: AsyncSession, conversation_id: int) -> None:
    """会话删除前调用（CONV-4 步骤 0）：取消该会话的运行中任务。"""
    async with new_session() as s:
        rows = await s.execute(
            select(AnalysisTask.id).where(
                AnalysisTask.conversation_id == conversation_id,
                AnalysisTask.task_status.in_(AnalysisTask.ACTIVE_STATUSES),
            )
        )
        for (tid,) in rows.all():
            aio_task = RUNNING.get(tid)
            if aio_task is not None:
                aio_task.cancel()
    # 等待取消传播到终态（run_task 的 CancelledError 分支写库）
    await asyncio.sleep(0.2)


async def has_active_task(session: AsyncSession, conversation_id: int) -> bool:
    """MSG-3：单会话单任务检查。"""
    n = (
        await session.execute(
            select(func.count()).select_from(AnalysisTask).where(
                AnalysisTask.conversation_id == conversation_id,
                AnalysisTask.task_status.in_(AnalysisTask.ACTIVE_STATUSES),
            )
        )
    ).scalar_one()
    return n > 0


async def count_active_global(session: AsyncSession) -> int:
    """TASK-2：全局 queued+running 计数，≥5 拒绝（42901）。"""
    return (
        await session.execute(
            select(func.count()).select_from(AnalysisTask).where(
                AnalysisTask.task_status.in_(AnalysisTask.ACTIVE_STATUSES)
            )
        )
    ).scalar_one()


async def recover_zombie_tasks() -> None:
    """TASK-5 启动恢复：queued/running → failed。"""
    async with new_session() as session, session.begin():
        await session.execute(text("""
            UPDATE analysis_tasks SET task_status = 'failed',
                error_message = '服务重启导致任务中断', finished_at = NOW(3)
            WHERE task_status IN ('queued', 'running')
        """))
    log.info("zombie_tasks_recovered")


async def get_owned(session: AsyncSession, user_id: int, task_id: int) -> AnalysisTask:
    task = await session.get(AnalysisTask, task_id)
    if task is None:
        raise BizError(40401, "任务不存在")
    if task.user_id != user_id:
        raise BizError(40301, "无权访问该任务")
    return task


async def get_logs(session: AsyncSession, task_id: int) -> list[TaskLog]:
    result = await session.execute(
        select(TaskLog).where(TaskLog.task_id == task_id).order_by(TaskLog.created_at.asc())
    )
    return list(result.scalars().all())


async def log_record(task_id: int, level: str, log_type: str, content: str) -> None:
    """TASK-6 全路径埋点（后台链路用，自管会话）。"""
    async with new_session() as session, session.begin():
        session.add(TaskLog(task_id=task_id, log_level=level, log_type=log_type,
                            log_content=str(content)[:2000]))
    log.log("INFO" if level == "info" else level.upper(), "task_log",
            task_id=task_id, log_type=log_type, content=str(content)[:200])


async def cleanup_expired_tokens() -> None:
    """后台协程（lifespan）：每小时清理过期 1h 以上的 WS 令牌（DATA §7.3）。"""
    while True:
        await asyncio.sleep(3600)
        try:
            async with new_session() as session, session.begin():
                await session.execute(text(
                    "DELETE FROM websocket_tokens WHERE expires_at < NOW(3) - INTERVAL 1 HOUR"
                ))
        except Exception as e:  # noqa: BLE001 —— 清理协程不能死
            log.error("token_cleanup_failed", error=str(e))
