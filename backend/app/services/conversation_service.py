"""会话业务（CONV-1~5，级联删除见 delete_many）。"""
from __future__ import annotations

import asyncio
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.env import get_env
from app.core.logging import get_logger
from app.db.duckdb import get_duckdb
from app.models import (AnalysisResult, AnalysisTask, Attachment, ContextSummary,
                        Conversation, Message, TaskLog)
from app.schemas.common import BizError
from app.services import task_service

log = get_logger(__name__)


async def create(session: AsyncSession, user_id: int, title: str) -> Conversation:
    conv = Conversation(user_id=user_id, title=title, status="active", next_seq_no=0)
    session.add(conv)
    await session.flush()
    return conv


async def list_by_user(
    session: AsyncSession, user_id: int, statuses: tuple[str, ...]
) -> list[Conversation]:
    """按 COALESCE(last_message_at, created_at) 倒序。"""
    order = Conversation.last_message_at.desc()
    result = await session.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.status.in_(statuses))
        .order_by(order, Conversation.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_many(session: AsyncSession, user_id: int, conversation_ids: list[int]) -> int:
    """CONV-4 级联删除（SPEC 4.2 / DATA §7.1）。

    顺序：取消进行中任务 → 收集附件元数据 → DB 物理删除（日志→结果→任务→摘要→附件→消息）
    → 会话行软删 → 提交后清磁盘与 DuckDB 表（失败仅记日志不回滚）。
    """
    result = await session.execute(
        select(Conversation).where(Conversation.id.in_(conversation_ids))
    )
    convs = list(result.scalars().all())
    if len(convs) != len(set(conversation_ids)):
        raise BizError(40401, "部分会话不存在")
    if any(c.user_id != user_id for c in convs):
        raise BizError(40301, "包含无权限的会话")  # 整批拒绝不部分执行

    # 0) 进行中任务先取消（不等待终态——删除本身会清理任务行）
    for conv in convs:
        await task_service.cancel_if_active(session, conv.id)

    # 1) 收集附件元数据（磁盘/DuckDB 清理用）
    att_meta: list[tuple[int, str | None, str]] = []  # (uid, duckdb_table, file_path)
    for conv in convs:
        rows = await session.execute(
            select(Attachment.duckdb_table, Attachment.file_path).where(
                Attachment.conversation_id == conv.id
            )
        )
        for table, file_path in rows.all():
            att_meta.append((conv.user_id, table, file_path))

    # 2) DB 物理删除
    for conv in convs:
        task_ids = select(AnalysisTask.id).where(AnalysisTask.conversation_id == conv.id)
        await session.execute(delete(TaskLog).where(TaskLog.task_id.in_(task_ids)))
        await session.execute(delete(AnalysisResult).where(AnalysisResult.conversation_id == conv.id))
        await session.execute(delete(AnalysisTask).where(AnalysisTask.conversation_id == conv.id))
        await session.execute(delete(ContextSummary).where(ContextSummary.conversation_id == conv.id))
        await session.execute(delete(Attachment).where(Attachment.conversation_id == conv.id))
        await session.execute(delete(Message).where(Message.conversation_id == conv.id))
        conv.status = "deleted"
        conv.updated_at = datetime.now()
    await session.flush()
    log.info("conversations_deleted", count=len(convs))

    # 3) 磁盘清理（提交后语义——本方法在请求事务内，目录清理失败不回滚 DB）
    duck = get_duckdb()
    drop_tables = [t for (_, t, _) in att_meta if t]

    async def _cleanup_side_effects() -> None:
        for conv in convs:
            for d in ("uploads", "exports", "workspace"):
                path = Path(get_env().data_dir) / d / str(conv.user_id) / str(conv.id)
                await asyncio.to_thread(shutil.rmtree, path, True)
        if drop_tables:
            try:
                async with duck.write_txn():
                    for table in drop_tables:
                        await asyncio.to_thread(
                            duck._conn.execute,  # noqa: SLF001 —— 单例内部连接
                            f'DROP TABLE IF EXISTS "attachments"."{table}"',
                        )
            except Exception as e:  # noqa: BLE001 —— DuckDB 清理失败仅记日志
                log.error("duckdb_drop_failed", error=str(e), tables=drop_tables)

    # 注册提交后执行（get_session 的 begin 块 commit 后回调）
    import sqlalchemy.event

    @sqlalchemy.event.listens_for(session, "after_commit", once=True)
    def _on_commit(_conn_session) -> None:  # 回调运行于事件循环线程内，可安全派生清理任务
        asyncio.get_running_loop().create_task(_cleanup_side_effects())

    return len(convs)
