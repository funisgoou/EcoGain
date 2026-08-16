"""公共依赖（AUTH-6 登录态 / CFG-6 admin 守卫 / 会话归属校验）。"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.mysql import get_session
from app.models import Conversation, User
from app.schemas.common import BizError

# 内存会话表（单实例 POC）：token → (user_id, expires_at)
SESSION_STORE: dict[str, tuple[int, datetime]] = {}
SESSION_TTL = timedelta(hours=24)


def create_session_token(user_id: int) -> str:
    import secrets

    token = secrets.token_urlsafe(32)
    SESSION_STORE[token] = (user_id, datetime.now() + SESSION_TTL)
    return token


def pop_session_token(token: str | None) -> None:
    if token:
        SESSION_STORE.pop(token, None)


async def get_current_user(
    request: Request, session: AsyncSession = Depends(get_session)
) -> User:
    token = request.cookies.get("ecogain_session")
    if not token or token not in SESSION_STORE:
        raise BizError(40101, "登录态无效")
    user_id, expires_at = SESSION_STORE[token]
    if datetime.now() > expires_at:
        SESSION_STORE.pop(token, None)
        raise BizError(40101, "登录态无效")
    user = await session.get(User, user_id)
    if user is None or user.status == "disabled":
        SESSION_STORE.pop(token, None)
        raise BizError(40101, "用户不可用")
    return user


async def try_get_user_from_cookie(request: Request) -> User | None:
    """WS 升级请求鉴权（无 Depends 环境，主动查库）。"""
    token = request.cookies.get("ecogain_session")
    if not token or token not in SESSION_STORE:
        return None
    user_id, expires_at = SESSION_STORE[token]
    if datetime.now() > expires_at:
        return None
    from app.db.mysql import new_session

    async with new_session() as session:
        user = await session.get(User, user_id)
    if user is None or user.status == "disabled":
        return None
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise BizError(40301, "需要管理员权限")
    return user


async def assert_conversation_owned(
    session: AsyncSession, user: User, conversation_id: int
) -> Conversation:
    """所有会话级资源的统一前置校验（PRD 4.2 数据隔离）。"""
    conv = await session.get(Conversation, conversation_id)
    if conv is None or conv.status == "deleted":
        raise BizError(40401, "会话不存在")
    if conv.user_id != user.id:
        raise BizError(40301, "无权访问该会话")
    return conv
