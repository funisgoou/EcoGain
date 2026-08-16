"""应用入口：装配、启停恢复（TASK-5/ATT-8）、优雅停机、健康检查。"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import admin, attachment, auth, chat, results
from app.core.config import get_config, load_configs
from app.core.logging import get_logger, setup_logging
from app.db.duckdb import duckdb_ping, get_duckdb, init_duckdb
from app.db.mysql import init_mysql, mysql_ping
from app.schemas.common import BizError
from app.services import attachment_service, task_service
from app.ws import router as ws_router
from app.ws.manager import heartbeat_monitor

log = get_logger(__name__)

# 会话校验白名单（AuthSessionMiddleware）
AUTH_WHITELIST = ("/auth/login", "/auth/callback", "/healthz", "/docs", "/openapi.json",
                  "/redoc", "/favicon.ico")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- 启动 ----
    setup_logging()
    engine = init_mysql()
    await load_configs(engine)
    duck = init_duckdb(get_config().duckdb_path)
    await task_service.recover_zombie_tasks()          # TASK-5
    await attachment_service.recover_stuck_attachments()  # ATT-8
    cleaners = [
        asyncio.create_task(task_service.cleanup_expired_tokens()),  # DATA §7.3
        asyncio.create_task(heartbeat_monitor()),                    # WS-4
    ]
    log.info("app_started", duckdb=get_config().duckdb_path)
    yield
    # ---- 优雅停机 ----
    for t in cleaners:
        t.cancel()
    # 等待运行中任务（≤30s），超时者由下次启动的僵尸恢复处置
    for _ in range(60):
        if not task_service.RUNNING:
            break
        await asyncio.sleep(0.5)
    for t in list(task_service.RUNNING.values()):
        t.cancel()
    duck.close()
    await engine.dispose()
    log.info("app_stopped")


def create_app() -> FastAPI:
    app = FastAPI(title="EcoGain Backend", version="0.1.0", lifespan=lifespan)

    # 跨域联调（API 文档 §2.1）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(attachment.router)
    app.include_router(results.router)
    app.include_router(admin.router)
    app.include_router(ws_router.router)

    # 会话校验中间件：白名单外全部要求登录态
    @app.middleware("http")
    async def auth_session_middleware(request: Request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or path.startswith(AUTH_WHITELIST):
            return await call_next(request)
        from app.api.deps import SESSION_STORE

        token = request.cookies.get("ecogain_session")
        if not token or token not in SESSION_STORE:
            return JSONResponse(status_code=401, content={"code": 40101, "message": "登录态无效", "data": None})
        return await call_next(request)

    # 业务异常 → 统一响应包（HTTP 状态 = code 前三位）
    @app.exception_handler(BizError)
    async def biz_error_handler(request: Request, exc: BizError):
        return JSONResponse(
            status_code=int(str(exc.code)[:3]), content={"code": exc.code, "message": exc.message, "data": None}
        )

    # 未预期异常：不向前端透出内部细节
    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.error("unhandled_exception", path=request.url.path, error=str(exc))
        return JSONResponse(
            status_code=500, content={"code": 50000, "message": "服务器内部错误", "data": None}
        )

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        ok_mysql = await mysql_ping()
        ok_duck = duckdb_ping()
        ok_llm = get_config().llm_model is not None
        status = "ok" if all([ok_mysql, ok_duck, ok_llm]) else "degraded"
        return {"status": status, "mysql": ok_mysql, "duckdb": ok_duck, "llm_config": ok_llm}

    return app


app = create_app()
