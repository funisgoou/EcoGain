"""统一响应包与公共 DTO。

路由层唯一出口：ok(data) / err(code, msg)；HTTP 状态码 = code 前三位。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ApiResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: Any = None


def ok(data: Any = None) -> dict:
    return {"code": 0, "message": "ok", "data": data}


def err(code: int, msg: str) -> dict:
    return {"code": code, "message": msg, "data": None}


class BizError(Exception):
    """业务异常：路由/服务层抛出，全局异常处理器翻译为统一响应包。"""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")
