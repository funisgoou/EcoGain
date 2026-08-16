"""EcoGain OAuth2 认证中心（AUTH-1~3）。

独立 FastAPI 进程 :8001。三端点 + 登录页；表结构见 DATA §4。
"""
from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from starlette.datastructures import FormData

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

MYSQL_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = os.environ.get("MYSQL_PORT", "3306")
MYSQL_USER = os.environ.get("MYSQL_USER", "ecogain")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "ecogain_pass")
MYSQL_AUTH_DATABASE = os.environ.get("MYSQL_AUTH_DATABASE", "ecogain_auth")
AUTH_JWT_SECRET = os.environ.get("AUTH_JWT_SECRET", "change-me-in-prod")
AUTH_CLIENT_SECRET = os.environ.get("AUTH_CLIENT_SECRET", "ecogain-web-secret")
JWT_TTL = timedelta(hours=8)

_engine = create_async_engine(
    f"mysql+asyncmy://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_AUTH_DATABASE}?charset=utf8mb4",
    pool_size=5, pool_pre_ping=True,
)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)


async def get_db():
    async with _session_factory() as session:
        async with session.begin():
            yield session


async def seed() -> None:
    """建两演示账号 + 一个 client（幂等：存在即跳过）。"""
    async with _session_factory() as session, session.begin():
        # 表由 docker/mysql/init SQL 预建；此处仅灌账号
        for username, role in (("analyst", "analyst"), ("admin", "admin")):
            exists = (await session.execute(
                text("SELECT id FROM auth_users WHERE username = :u"), {"u": username}
            )).scalar_one_or_none()
            if exists is None:
                pw_hash = bcrypt.hashpw(b"EcoGain@2026", bcrypt.gensalt(rounds=12)).decode()
                await session.execute(text(
                    "INSERT INTO auth_users (username, password_hash, display_name, role, status) "
                    "VALUES (:u, :p, :d, :r, 'active')"
                ), {"u": username, "p": pw_hash, "d": username.title(), "r": role})
        client_exists = (await session.execute(
            text("SELECT id FROM auth_clients WHERE client_id = 'ecogain-web'")
        )).scalar_one_or_none()
        if client_exists is None:
            public_base = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")
            await session.execute(text(
                "INSERT INTO auth_clients (client_id, client_secret, client_name, redirect_uri) "
                "VALUES ('ecogain-web', :s, 'EcoGain Web', :r)"
            ), {"s": AUTH_CLIENT_SECRET, "r": f"{public_base}/auth/callback"})


@asynccontextmanager
async def lifespan(app: FastAPI):
    await seed()
    yield
    await _engine.dispose()


app = FastAPI(title="EcoGain Auth Server", lifespan=lifespan)


def issue_jwt(sub: str, username: str, display_name: str, role: str) -> str:
    payload = {
        "sub": sub, "username": username, "display_name": display_name,
        "role": role, "exp": datetime.now() + JWT_TTL,
    }
    return jwt.encode(payload, AUTH_JWT_SECRET, algorithm="HS256")


def verify_jwt(token: str) -> dict | None:
    try:
        return jwt.decode(token, AUTH_JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def _oauth_error(code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message, "error_code": code}, status_code=code)


ERROR_PAGE = """<html><body style="font-family:sans-serif;text-align:center;padding-top:80px">
<h2>授权请求无效（{{ code }}）</h2><p>{{ reason }}</p></body></html>"""


@app.get("/authorize")
async def authorize_page(
    request: Request,
    client_id: str = "",
    redirect_uri: str = "",
    response_type: str = "",
    state: str = "",
    db: AsyncSession = Depends(get_db),
):
    """AUTH-1（GET）：渲染账密页；四参数校验任一不符返回 400 错误页（不回跳）。"""
    client = (await db.execute(
        text("SELECT client_name, redirect_uri FROM auth_clients WHERE client_id = :c"),
        {"c": client_id},
    )).first()
    if (client is None or client.redirect_uri != redirect_uri
            or response_type != "code" or not state):
        return HTMLResponse(
            ERROR_PAGE.replace("{{ code }}", "400").replace("{{ reason }}", "client_id / redirect_uri / response_type / state 校验失败"),
            status_code=400,
        )
    return templates.TemplateResponse(request, "login.html", {
        "client_name": client.client_name, "state": state,
        "client_id": client_id, "redirect_uri": redirect_uri, "error": None,
    })


@app.post("/authorize")
async def authorize_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    client_id: str = Form(""),
    redirect_uri: str = Form(""),
    state: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """AUTH-1（POST）：账密校验 → 发一次性 code → 302 回 redirect_uri。"""
    row = (await db.execute(
        text("SELECT id, password_hash, status FROM auth_users WHERE username = :u"),
        {"u": username},
    )).first()
    ok = row is not None and row.status == "active" and bcrypt.checkpw(
        password.encode(), row.password_hash.encode()
    )
    if not ok:
        return templates.TemplateResponse(request, "login.html", {
            "client_name": client_id, "state": state, "client_id": client_id,
            "redirect_uri": redirect_uri, "error": "账号或密码错误",
        })
    code = secrets.token_urlsafe(32)
    await db.execute(text(
        "INSERT INTO auth_codes (code, client_id, user_id, redirect_uri, expires_at) "
        "VALUES (:c, :cid, :uid, :r, :e)"
    ), {"c": code, "cid": client_id, "uid": row.id, "r": redirect_uri,
        "e": datetime.now() + timedelta(seconds=300)})
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}code={code}&state={state}")


@app.post("/token")
async def token(
    grant_type: str = Form(""),
    code: str = Form(""),
    client_id: str = Form(""),
    client_secret: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """AUTH-2：授权码换 JWT。code 原子消费（UPDATE 四条件）。"""
    if grant_type != "authorization_code":
        return _oauth_error(400, "unsupported_grant_type")
    client = (await db.execute(
        text("SELECT client_secret FROM auth_clients WHERE client_id = :c"), {"c": client_id}
    )).first()
    if client is None or client.client_secret != client_secret:
        return _oauth_error(401, "invalid_client")
    r = await db.execute(text("""
        UPDATE auth_codes SET consumed_at = NOW(3)
        WHERE code = :c AND client_id = :cid AND consumed_at IS NULL AND expires_at > NOW(3)
    """), {"c": code, "cid": client_id})
    if r.rowcount != 1:
        return _oauth_error(400, "invalid_grant")  # 已用/过期/不存在
    row = (await db.execute(text(
        "SELECT u.id, u.username, u.display_name, u.role FROM auth_codes c "
        "JOIN auth_users u ON u.id = c.user_id WHERE c.code = :c"
    ), {"c": code})).first()
    if row is None:
        return _oauth_error(400, "invalid_grant")
    jwt_token = issue_jwt(str(row.id), row.username, row.display_name, row.role)
    return {"access_token": jwt_token, "token_type": "Bearer", "expires_in": int(JWT_TTL.total_seconds())}


@app.get("/userinfo")
async def userinfo(authorization: str = ""):
    """AUTH-3：Bearer JWT 验签 → 用户信息。"""
    if not authorization.startswith("Bearer "):
        return _oauth_error(401, "invalid_token")
    payload = verify_jwt(authorization.removeprefix("Bearer "))
    if payload is None:
        return _oauth_error(401, "invalid_token")
    return {
        "sub": payload["sub"], "username": payload["username"],
        "display_name": payload["display_name"], "role": payload["role"],
    }
