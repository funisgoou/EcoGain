"""附件 DTO（API 文档 §5）。"""
from __future__ import annotations

from pydantic import BaseModel, field_validator

PARSE_STATUSES = {"pending", "parsing", "ready", "failed"}


class UploadResp(BaseModel):
    attachment_id: int
    file_name: str
    file_path: str
    parse_status: str

    @field_validator("parse_status")
    @classmethod
    def check_status(cls, v: str) -> str:
        if v not in PARSE_STATUSES:
            raise ValueError(f"非法 parse_status：{v}")
        return v


class AttachmentItem(BaseModel):
    attachment_id: int
    file_name: str
    file_type: str
    file_size: int
    parse_status: str
    error_message: str | None = None
    created_at: str | None = None


class DeleteAttachmentReq(BaseModel):
    attachment_id: int
