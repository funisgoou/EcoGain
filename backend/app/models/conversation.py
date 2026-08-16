"""conversations — 分析会话。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mysql import Base


class Conversation(Base):
    """分析会话。"""

    __tablename__ = "conversations"
    __table_args__ = (
        Index("idx_user_status_last", "user_id", "status", "last_message_at"),
        # CHECK 约束 chk_conv_status 由 Alembic DDL 层实现；模型层不写
        # CheckConstraint，status 枚举值由应用层校验（与 DDL CHECK 双保险）。
        {"comment": "分析会话"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, server_default=text("'新分析'"))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'active'"), comment="active | archived | deleted"
    )
    next_seq_no: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
        comment="消息序号分配计数器（实现扩展，PRD 附录 B 之外补充）",
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(3),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(3)"),
        server_onupdate=text("CURRENT_TIMESTAMP(3)"),
    )
