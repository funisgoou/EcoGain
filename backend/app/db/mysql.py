"""MySQL 异步引擎与会话工厂（基础设施）。

连接串来自环境变量（DB 连接不能存 DB 里）；pool_size 按 POC 并发 ≤5 设 10。
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (AsyncEngine, AsyncSession,
                                    async_sessionmaker, create_async_engine)
from sqlalchemy.orm import DeclarativeBase

from app.core.env import get_env


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_mysql() -> AsyncEngine:
    """进程级单例引擎（lifespan 调用）。"""
    global _engine, _session_factory
    if _engine is not None:
        return _engine
    _engine = create_async_engine(get_env().mysql_url, pool_size=10, pool_pre_ping=True, echo=False)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("MySQL 引擎未初始化（init_mysql 未调用）")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("MySQL 会话工厂未初始化（init_mysql 未调用）")
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：请求级会话，请求成功自动 COMMIT、异常自动 ROLLBACK。"""
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            yield session


async def new_session() -> AsyncSession:
    """后台任务/服务层自管事务用的裸会话（不自动 begin，由调用方控制）。"""
    factory = get_session_factory()
    return factory()


async def mysql_ping() -> bool:
    try:
        if _engine is None:
            return False
        async with _engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 —— 健康检查吞异常
        return False
