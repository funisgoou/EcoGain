"""会话与消息 DTO（API 文档 §4）。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CreateChatReq(BaseModel):
    title: str | None = Field(default=None, max_length=200, description="≤200 字；缺省「新分析」")


class CreateChatResp(BaseModel):
    conversation_id: int
    title: str
    status: str


class UpdateChatReq(BaseModel):
    conversation_id: int
    title: str = Field(min_length=1, max_length=200)
    status: str | None = Field(default=None, description="可选：active↔archived 归档切换（CONV-5）")


class DeleteChatReq(BaseModel):
    conversation_ids: list[int] = Field(min_length=1, max_length=50)


class ChatListItem(BaseModel):
    conversation_id: int
    title: str
    status: str
    last_message_at: datetime | None = None


class AttachmentBrief(BaseModel):
    """历史消息里聚合的附件摘要（API 文档 §4.5 示例）。"""

    attachment_id: int
    file_name: str
    file_type: str
    file_size: int
    parse_status: str


class MessageItem(BaseModel):
    message_id: int
    role: str  # user | assistant | tool
    message_type: str  # text | tool_call | result
    content: str
    tool_name: str | None = None
    tool_status: str | None = None  # running | success | failed
    task_id: int | None = None
    attachments: list[AttachmentBrief] = Field(default_factory=list)
    created_at: datetime


class WsTokenReq(BaseModel):
    conversation_id: int
