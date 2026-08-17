"""WS 端点与上行分发（WS-2 令牌原子消费 / WS-5 消息下发 / WS-6 收发循环 / MSG-3 / TASK-1/2/3）。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import text

from app.api.deps import try_get_user_from_cookie
from app.core.logging import TraceCtx, get_logger
from app.db.mysql import new_session
from app.schemas import ws as wsmsg
from app.schemas.ws import parse_ws_up
from app.services import attachment_service, task_service
from app.ws.manager import MANAGER

log = get_logger(__name__)
router = APIRouter(tags=["ws"])

MAX_TEXT_LEN = 4000


async def consume_token(token: str, conversation_id: int, user_id: int) -> bool:
    """WS-2 原子消费：单条 UPDATE 的 WHERE 同时校验存在/未消费/未过期/归属。"""
    async with new_session() as session, session.begin():
        result = await session.execute(text("""
            UPDATE websocket_tokens SET consumed_at = NOW(3)
            WHERE token = :t AND conversation_id = :cid AND user_id = :uid
              AND expires_at > NOW(3) AND consumed_at IS NULL
        """), {"t": token, "cid": conversation_id, "uid": user_id})
        return result.rowcount == 1


@router.websocket("/api/chat/ws/chat")
async def websocket_endpoint(ws: WebSocket, websocket_token: str, conversation_id: int) -> None:
    """WS 主入口：Cookie 鉴权 + 一次性令牌 → 注册 → 收发循环（任何帧都 touch 心跳）。"""
    user = await try_get_user_from_cookie(ws)
    if user is None or not await consume_token(websocket_token, conversation_id, user.id):
        # 必须先 accept 才能 close(code=4401)——握手期直接 close 会以 HTTP 403 拒绝，
        # 前端拿不到约定关闭码；accept 后立即关闭，前端 onclose 可读到 4401
        await ws.accept()
        await ws.close(code=4401)  # 令牌无效/过期/已消费
        return
    uid = user.id
    await ws.accept()
    await MANAGER.connect(conversation_id, uid, ws)
    log.info("ws_connected", conversation_id=conversation_id, user_id=uid)
    try:
        while True:
            try:
                raw = await ws.receive_json()
            except ValueError:
                continue  # 非 JSON 帧忽略
            MANAGER.touch(conversation_id, uid)
            msg = parse_ws_up(raw)
            if msg is None:
                log.warning("ws_invalid_frame_ignored", conversation_id=conversation_id, user_id=uid)
                continue
            if msg.type == "ping":
                await ws.send_json({"type": "pong"})
            elif msg.type == "user_message":
                await handle_user_message(user, conversation_id, msg)
            elif msg.type == "cancel":
                async with new_session() as session:
                    await task_service.cancel_task(session, uid, msg.task_id)
    except WebSocketDisconnect:
        pass
    finally:
        MANAGER.disconnect(conversation_id, uid)
        log.info("ws_disconnected", conversation_id=conversation_id, user_id=uid)


async def handle_user_message(user, conversation_id: int, msg) -> None:
    """三道前置检查后进任务链路；失败经 WS 下发 error（task_id=0）。"""
    TraceCtx.start()  # 生成本轮 trace_id
    TraceCtx.bind_user(user.id)
    TraceCtx.bind_conversation(conversation_id)

    async def reject(code: int, text_: str) -> None:
        await MANAGER.broadcast(conversation_id, wsmsg.msg_error(0, code, text_))

    if not (msg.text or "").strip() or len(msg.text) > MAX_TEXT_LEN:
        return await reject(40001, "问题长度超限或为空")
    async with new_session() as session:
        # 附件归属 + 就绪校验（未 ready 的附件整条拒绝）
        atts = await attachment_service.get_ready_attachments(
            session, conversation_id, msg.attachment_ids
        )
        if atts is None:
            return await reject(40002, "附件不存在或未就绪")
        if await task_service.has_active_task(session, conversation_id):  # MSG-3
            return await reject(40901, "当前会话已有运行中的任务")
        if await task_service.count_active_global(session) >= task_service.MAX_GLOBAL_CONCURRENT:
            return await reject(42901, "并发任务已达上限")  # TASK-2
    await task_service.start_task(user.id, conversation_id, msg.text, msg.attachment_ids)
