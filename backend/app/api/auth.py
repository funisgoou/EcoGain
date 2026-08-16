"""登录/回调/登出（AUTH-4~7，SPEC 4.1 OAuth2 授权码链路）。"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (create_session_token, get_current_user,
                          pop_session_token)
from app.core.env import get_env
from app.core.logging import get_logger
from app.db.mysql import get_session
from app.models import User
from app.schemas.common import BizError, ok

log = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# OAuth state 暂存（60s TTL，单实例内存）
PENDING_STATES: dict[str, datetime] = {}
STATE_TTL = timedelta(seconds=60)


def _frontend(path: str) -> str:
    return f"{get_env().frontend_base_url}{path}"


@router.get("/login")
async def route_login() -> RedirectResponse:
    """AUTH-4：生成 state → 302 跳认证中心 /authorize。"""
    state = secrets.token_urlsafe(16)
    PENDING_STATES[state] = datetime.now() + STATE_TTL
    # 顺手清理过期 state
    now = datetime.now()
    for k in [k for k, v in PENDING_STATES.items() if v < now]:
        PENDING_STATES.pop(k, None)
    env = get_env()
    url = (
        f"{env.auth_base_url}/authorize?client_id=ecogain-web"
        f"&redirect_uri={env.public_base_url}/auth/callback"
        f"&response_type=code&state={state}"
    )
    return RedirectResponse(url)


async def _exchange_code(code: str) -> str:
    """POST auth-server /token（client_secret 走环境变量）。"""
    env = get_env()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{env.auth_base_url}/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": "ecogain-web",
                "client_secret": env.auth_client_secret,
            },
        )
    if resp.status_code != 200:
        raise BizError(40101, f"授权码换 token 失败：{resp.text[:200]}")
    return resp.json()["access_token"]


async def _fetch_userinfo(token: str) -> dict:
    env = get_env()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{env.auth_base_url}/userinfo",
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code != 200:
        raise BizError(40101, "获取用户信息失败")
    return resp.json()


@router.get("/callback")
async def route_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """AUTH-5：state 校验 → code 换 token → userinfo → upsert → 设会话 Cookie → 302 工作台。"""
    if error:
        return RedirectResponse(_frontend(f"/auth/callback?error={error}"))
    now = datetime.now()
    if not code or not state or state not in PENDING_STATES or PENDING_STATES[state] < now:
        return RedirectResponse(_frontend("/auth/callback?error=40101"))  # state 校验失败
    PENDING_STATES.pop(state)  # 一次性
    try:
        token = await _exchange_code(code)
        info = await _fetch_userinfo(token)
        user = await User.upsert_from_oauth(
            session,
            external_id=str(info["sub"]),
            username=info["username"],
            display_name=info.get("display_name", ""),
            role=info.get("role", "analyst"),
        )
    except BizError as e:
        return RedirectResponse(_frontend(f"/auth/callback?error={e.code}&message={e.message}"))
    if user.status == "disabled":
        return RedirectResponse(_frontend("/auth/callback?error=40301"))
    session_token = create_session_token(user.id)
    resp = RedirectResponse(_frontend("/workbench"))
    resp.set_cookie(
        "ecogain_session", session_token,
        httponly=True, samesite="lax", max_age=int(timedelta(hours=24).total_seconds()),
    )
    log.info("user_logged_in", user_id=user.id, username=user.username)
    return resp


@router.post("/logout")
async def route_logout(
    request: Request, _user: User = Depends(get_current_user)
) -> dict:
    """AUTH-7：删内存会话 + 清 Cookie。"""
    pop_session_token(request.cookies.get("ecogain_session"))
    resp = ok({"ok": True})
    return resp
