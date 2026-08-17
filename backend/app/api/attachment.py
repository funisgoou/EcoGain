"""附件路由（ATT-1 上传 / ATT-6 删除 / ATT-7 下载）。"""
from __future__ import annotations

from fastapi import (APIRouter, Depends, File, Form, UploadFile)
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import assert_conversation_owned, get_current_user
from app.core.config import get_config
from app.db.mysql import get_session
from app.models import User
from app.schemas.attachment import DeleteAttachmentReq, UploadResp
from app.schemas.common import BizError, ok
from app.services import attachment_service

router = APIRouter(prefix="/api/attachment", tags=["attachment"])

MEDIA_TYPES = {
    "csv": "text/csv", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "txt": "text/plain", "md": "text/markdown",
}


@router.post("/upload")
async def route_upload(
    conversation_id: int = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if not get_config().attachment_enabled:  # CFG-5 开关
        raise BizError(40301, "附件功能已关闭")
    await assert_conversation_owned(session, user, conversation_id)
    att = await attachment_service.save_upload(session, user.id, conversation_id, file)
    return ok(UploadResp(
        attachment_id=att.id, file_name=att.file_name,
        file_path=f"uploads/{att.file_path}", parse_status=att.parse_status,
    ).model_dump())


@router.post("/delete")
async def route_delete(
    body: DeleteAttachmentReq,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    att = await attachment_service.get_owned(session, user.id, body.attachment_id)
    if att.parse_status == "parsing":
        raise BizError(40001, "解析中的附件暂不可删除")
    await attachment_service.delete_attachment(att)
    return ok({"deleted": True})


@router.get("/get")
async def route_download(
    attachment_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    att = await attachment_service.get_owned(session, user.id, attachment_id)
    path = await attachment_service.get_attachment_file(att)
    if path is None:
        raise BizError(40401, "附件文件不存在")
    return FileResponse(
        path, filename=att.file_name,
        media_type=MEDIA_TYPES.get(att.file_type, "application/octet-stream"),
    )
