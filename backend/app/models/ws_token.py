"""websocket_tokens — WebSocket 建连一次性令牌。"""

from datetime import datetime

from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy import BigInteger, DateTime, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mysql import Base


class WsToken(Base):
    """WebSocket 建连一次性令牌（原子消费 SQL 在 service 层，WS-2）。"""

    __tablename__ = "websocket_tokens"
    __table_args__ = (
        UniqueConstraint("token", name="uk_token"),
        Index("idx_expires", "expires_at"),
        {"comment": "WebSocket 建连一次性令牌"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    conversation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    token: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(MySQLDateTime(fsp=3), nullable=False, comment="签发后 60 秒")
    consumed_at: Mapped[datetime | None] = mapped_column(
        MySQLDateTime(fsp=3), nullable=True, comment="一次性消费标记（建连成功即写）"
    )
    created_at: Mapped[datetime] = mapped_column(
        MySQLDateTime(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )
