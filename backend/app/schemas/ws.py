"""WS 上行/下行消息模型（API 文档 §8）。

上行解析失败 → 忽略该帧并 warn（协议健壮性），不炸连接。
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter, field_validator


class UserMessageUp(BaseModel):
    type: Literal["user_message"]
    text: str = Field(min_length=1, max_length=4000)
    attachment_ids: list[int] = Field(default_factory=list)

    @field_validator("attachment_ids")
    @classmethod
    def dedup(cls, v: list[int]) -> list[int]:
        return list(dict.fromkeys(v))  # 去重保序


class CancelUp(BaseModel):
    type: Literal["cancel"]
    task_id: int


class PingUp(BaseModel):
    type: Literal["ping"]


WsUp = Union[UserMessageUp, CancelUp, PingUp]
ws_up_adapter: TypeAdapter[WsUp] = TypeAdapter(WsUp)


def parse_ws_up(raw: dict) -> WsUp | None:
    """非法帧返回 None（调用方 warn 后忽略）。"""
    try:
        return ws_up_adapter.validate_python(raw)
    except Exception:
        return None


# ---- 下行构造器（各服务直接调用，保持字段名与 API 文档 §8.3 一致）----


def msg_message_start(task_id: int, conversation_id: int, message_id: int) -> dict:
    return {"type": "message_start", "task_id": task_id,
            "conversation_id": conversation_id, "message_id": message_id}


def msg_message_delta(task_id: int, message_id: int, delta_text: str) -> dict:
    return {"type": "message_delta", "task_id": task_id,
            "message_id": message_id, "delta_text": delta_text}


def msg_tool_start(task_id: int, tool_name: str, tool_input_summary: str) -> dict:
    return {"type": "tool_start", "task_id": task_id, "tool_name": tool_name,
            "tool_input_summary": tool_input_summary[:200]}


def msg_tool_finish(task_id: int, tool_name: str, tool_status: str,
                    tool_result_summary: str) -> dict:
    return {"type": "tool_finish", "task_id": task_id, "tool_name": tool_name,
            "tool_status": tool_status, "tool_result_summary": tool_result_summary[:500]}


def msg_task_status(task_id: int, task_status: str, current_step: str | None) -> dict:
    return {"type": "task_status", "task_id": task_id,
            "task_status": task_status, "current_step": current_step}


def msg_result_ready(task_id: int, result_id: int) -> dict:
    return {"type": "result_ready", "task_id": task_id, "result_id": result_id}


def msg_error(task_id: int, error_code: int, error_message: str) -> dict:
    return {"type": "error", "task_id": task_id,
            "error_code": error_code, "error_message": error_message}


def msg_done(task_id: int, finished_at: str) -> dict:
    return {"type": "done", "task_id": task_id, "finished_at": finished_at}


def msg_attachment_status(attachment_id: int, parse_status: str) -> dict:
    return {"type": "attachment_status", "attachment_id": attachment_id,
            "parse_status": parse_status}
