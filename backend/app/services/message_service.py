"""消息业务（MSG-1 历史 / MSG-2 seq_no 原子分配）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import Attachment, Conversation, Message
from app.schemas.common import BizError

log = get_logger(__name__)


async def allocate_seq_no(session: AsyncSession, conversation_id: int) -> int:
    """MSG-2：FOR UPDATE 锁定读防并发重号；uk_conv_seq 唯一索引兜底 + 一次重试。"""
    for _attempt in range(2):
        try:
            cur = (
                await session.execute(
                    text("SELECT next_seq_no FROM conversations WHERE id = :cid FOR UPDATE"),
                    {"cid": conversation_id},
                )
            ).scalar_one()
            await session.execute(
                text("UPDATE conversations SET next_seq_no = :n WHERE id = :cid"),
                {"n": cur + 1, "cid": conversation_id},
            )
            await session.flush()
            return cur + 1
        except IntegrityError:  # uk_conv_seq 冲突（理论罕见）
            await session.rollback()
            continue
    raise BizError(50000, "消息序号分配失败")


async def append_message(
    session: AsyncSession,
    conversation_id: int,
    role: str,
    message_type: str,
    content: str,
    *,
    tool_name: str | None = None,
    tool_status: str | None = None,
    task_id: int | None = None,
    attachment_ids: list[int] | None = None,
) -> Message:
    """消息落库统一出口。user 消息同时回填 attachment.message_id + 刷新会话 last_message_at。"""
    seq = await allocate_seq_no(session, conversation_id)
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        message_type=message_type,
        content=content,
        tool_name=tool_name,
        tool_status=tool_status,
        task_id=task_id,
        seq_no=seq,
    )
    session.add(msg)
    await session.flush()
    if attachment_ids:  # 附件挂到这条 user 消息
        await session.execute(
            update(Attachment).where(Attachment.id.in_(attachment_ids)).values(message_id=msg.id)
        )
    await session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(last_message_at=datetime.now())
    )
    await session.flush()
    return msg


async def update_message_content(
    session: AsyncSession, message_id: int, content: str, tool_status: str | None = None
) -> None:
    """流式 assistant 文本终态回填 / tool 消息状态更新。"""
    values: dict = {"content": content}
    if tool_status is not None:
        values["tool_status"] = tool_status
    await session.execute(update(Message).where(Message.id == message_id).values(**values))


async def list_messages(session: AsyncSession, conversation_id: int) -> list[Message]:
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.seq_no.asc())
    )
    return list(result.scalars().all())
