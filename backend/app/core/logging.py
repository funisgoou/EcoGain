"""结构化日志（loguru）+ trace 上下文。

方案（SPEC §7 / IMPL §5）：
- 自定义 JSON sink 平铺字段输出 stdout（loguru 原生 serialize=True 会把上下文
  藏在 record.extra 嵌套层，不满足平铺字段约定，故自定义 sink）；
- InterceptHandler 把 uvicorn/sqlalchemy 标准库日志接管进同一管道；
- TraceCtx 纯 ContextVar 实现，logger patcher 每条日志自动合入
  trace_id/task_id/conversation_id/user_id（等价 structlog bind_contextvars）。
"""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

from loguru import logger

# ---- 标准库拦截：uvicorn access/error 同管道输出 ----


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = sys._getframe(6), 6  # noqa: SLF001 —— loguru 官方推荐写法
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _json_sink(message: Any) -> None:
    """平铺 JSON sink：ts/level/msg 顶层字段 + extra 平铺。"""
    r = message.record
    entry = {
        "ts": r["time"].isoformat(timespec="milliseconds"),
        "level": r["level"].name,
        "msg": r["message"],
        **r["extra"],
    }
    sys.stdout.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


# ---- trace 上下文（contextvars 随 asyncio 任务传播）----
_trace_id: ContextVar[str] = ContextVar("trace_id", default="")
_task_id: ContextVar[int] = ContextVar("task_id", default=0)
_conversation_id: ContextVar[int] = ContextVar("conversation_id", default=0)
_user_id: ContextVar[int] = ContextVar("user_id", default=0)


def _patch(record: Any) -> None:
    record["extra"].setdefault("trace_id", _trace_id.get())
    record["extra"].setdefault("task_id", _task_id.get())
    record["extra"].setdefault("conversation_id", _conversation_id.get())
    record["extra"].setdefault("user_id", _user_id.get())


class TraceCtx:
    """链路上下文。WS user_message 入口 start() 生成 trace_id，
    后续同协程（含 spawn 出的任务）所有日志自动携带。"""

    @staticmethod
    def start() -> str:
        import uuid

        tid = uuid.uuid4().hex[:12]  # trace_id 生成规则（SPEC §7）
        _trace_id.set(tid)
        return tid

    @staticmethod
    def bind_task(task_id: int) -> None:
        _task_id.set(task_id)

    @staticmethod
    def bind_conversation(cid: int) -> None:
        _conversation_id.set(cid)

    @staticmethod
    def bind_user(uid: int) -> None:
        _user_id.set(uid)

    @staticmethod
    def current_trace_id() -> str:
        return _trace_id.get()


def setup_logging() -> None:
    logger.remove()  # 去掉默认 stderr handler
    logger.configure(patcher=_patch)
    logger.add(_json_sink, level="INFO")
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    # uvicorn 的 logger 也交给 InterceptHandler
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = [InterceptHandler()]
        logging.getLogger(name).propagate = False


def get_logger(name: str):
    """统一入口：log = get_logger(__name__)；name 经 bind 进 extra 平铺。"""
    return logger.bind(name=name)
