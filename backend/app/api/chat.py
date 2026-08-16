"""会话与消息路由（CONV-1~5 / MSG-1 / WS-1）。"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import assert_conversation_owned, get_current_user
from app.db.mysql import get_session
from app.models import Attachment, User, WsToken
from app.schemas.chat import (ChatListItem, CreateChatReq, CreateChatResp,
                              DeleteChatReq, MessageItem, UpdateChatReq,
                              WsTokenReq)
from app.schemas.common import BizError, ok
from app.services import conversation_service, message_service

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/create")
async def route_create(
    body: CreateChatReq,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    title = (body.title or "新分析").strip()[:200] or "新分析"
    conv = await conversation_service.create(session, user.id, title)
    return ok(CreateChatResp(
        conversation_id=conv.id, title=conv.title, status=conv.status
    ).model_dump())


@router.post("/delete")
async def route_delete(
    body: DeleteChatReq,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    n = await conversation_service.delete_many(session, user.id, body.conversation_ids)
    return ok({"deleted_count": n})


@router.post("/update")
async def route_update(
    body: UpdateChatReq,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """CONV-3 重命名 + CONV-5 归档（status 可选，仅 active↔archived）。"""
    conv = await assert_conversation_owned(session, user, body.conversation_id)
    if body.status is not None:
        allowed = {"active": "archived", "archived": "active"}
        if conv.status not in allowed or allowed[conv.status] != body.status:
            raise BizError(40001, "status 仅允许 active↔archived 切换")
        conv.status = body.status
    conv.title = body.title.strip()[:200] or conv.title
    conv.updated_at = datetime.now()
    await session.flush()
    return ok({"conversation_id": conv.id, "title": conv.title, "status": conv.status})


@router.get("/ls")
async def route_list(
    include_archived: bool = False,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    statuses = ("active", "archived") if include_archived else ("active",)
    rows = await conversation_service.list_by_user(session, user.id, statuses)
    return ok([
        ChatListItem(
            conversation_id=c.id, title=c.title, status=c.status,
            last_message_at=c.last_message_at,
        ).model_dump(mode="json") for c in rows
    ])


@router.get("/ls/{conversation_id}")
async def route_history(
    conversation_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """MSG-1：历史消息（seq_no 升序）+ 聚合 user 消息附件。"""
    await assert_conversation_owned(session, user, conversation_id)
    msgs = await message_service.list_messages(session, conversation_id)
    att_rows = await session.execute(
        select(Attachment).where(Attachment.conversation_id == conversation_id)
    )
    atts_by_msg: dict[int, list] = {}
    for att in att_rows.scalars().all():
        if att.message_id:
            atts_by_msg.setdefault(att.message_id, []).append(att)
    items = []
    for m in msgs:
        briefs = [
            {
                "attachment_id": a.id, "file_name": a.file_name,
                "file_type": a.file_type, "file_size": a.file_size,
                "parse_status": a.parse_status,
            }
            for a in atts_by_msg.get(m.id, [])
        ]
        items.append(MessageItem(
            message_id=m.id, role=m.role, message_type=m.message_type,
            content=m.content, tool_name=m.tool_name, tool_status=m.tool_status,
            task_id=m.task_id, attachments=briefs, created_at=m.created_at,
        ).model_dump(mode="json"))
    return ok(items)


@router.post("/ws-token")
async def route_ws_token(
    body: WsTokenReq,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """WS-1：签发 60s 一次性令牌。"""
    await assert_conversation_owned(session, user, body.conversation_id)
    token = secrets.token_urlsafe(32)
    session.add(WsToken(
        user_id=user.id, conversation_id=body.conversation_id, token=token,
        expires_at=datetime.now() + timedelta(seconds=60),
    ))
    await session.flush()
    return ok({"websocket_token": token, "expires_in": 60})
