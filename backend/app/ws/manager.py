"""WS 连接管理器（WS-3 连接注册 / WS-4 心跳巡检）。

POC 单实例内存版（SPEC 4.4）：dict[cid, dict[uid, WebSocket]] 注册表 + 每连接一把发送锁。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from fastapi import WebSocket

from app.core.logging import get_logger

log = get_logger(__name__)

HEARTBEAT_TOLERANCE = 60  # 秒：last_active 距今超过即判死连接（WS-4）
HEARTBEAT_INTERVAL = 15  # 秒：巡检周期


@dataclass
class ConnMeta:
    last_active: datetime = field(default_factory=datetime.now)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ConnectionManager:
    def __init__(self) -> None:
        self._conns: dict[int, dict[int, WebSocket]] = {}
        self._meta: dict[tuple[int, int], ConnMeta] = {}

    async def connect(self, cid: int, uid: int, ws: WebSocket) -> None:
        # 同 (cid,uid) 已有连接 → 关旧留新（多标签页）
        old = self._conns.get(cid, {}).get(uid)
        if old is not None:
            try:
                await old.close(code=1000)
            except Exception:  # noqa: BLE001 —— 旧连接可能已死
                pass
        self._conns.setdefault(cid, {})[uid] = ws
        self._meta[(cid, uid)] = ConnMeta()

    def disconnect(self, cid: int, uid: int) -> None:
        self._conns.get(cid, {}).pop(uid, None)
        if self._conns.get(cid) == {}:
            self._conns.pop(cid, None)
        self._meta.pop((cid, uid), None)

    async def broadcast(self, cid: int, message: dict) -> None:
        """对该会话所有连接推送；send 前取该连接的锁串行化（防两协程交织半帧 JSON）。"""
        for uid, ws in list(self._conns.get(cid, {}).items()):
            meta = self._meta.get((cid, uid))
            try:
                if meta is None:
                    continue
                async with meta.send_lock:
                    await ws.send_json(message)
            except Exception:  # noqa: BLE001 —— 死连接静默摘除
                log.warning("ws_dead_connection_dropped", conversation_id=cid, user_id=uid)
                self.disconnect(cid, uid)

    def touch(self, cid: int, uid: int) -> None:
        meta = self._meta.get((cid, uid))
        if meta is not None:
            meta.last_active = datetime.now()

    @property
    def active_conversations(self) -> list[int]:
        return list(self._conns.keys())


MANAGER = ConnectionManager()


async def heartbeat_monitor() -> None:
    """后台协程（lifespan 启动）：每 15s 扫描，last_active 距今 > 60s → close(4408)。"""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        now = datetime.now()
        for (cid, uid), meta in list(MANAGER._meta.items()):  # noqa: SLF001 —— 单例内部巡检
            if now - meta.last_active > timedelta(seconds=HEARTBEAT_TOLERANCE):
                ws = MANAGER._conns.get(cid, {}).get(uid)  # noqa: SLF001
                log.info("ws_heartbeat_timeout", conversation_id=cid, user_id=uid)
                if ws is not None:
                    try:
                        await ws.close(code=4408)  # 前端见 4408 立即重连
                    except Exception:  # noqa: BLE001
                        MANAGER.disconnect(cid, uid)
