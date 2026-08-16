"""messages — 会话消息。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mysql import Base


class Message(Base):
    """会话消息。"""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq_no", name="uk_conv_seq"),
        Index("idx_conv_created", "conversation_id", "created_at"),
        Index("idx_task", "task_id"),
        # CHECK 约束 chk_msg_role / chk_msg_type / chk_msg_tstat 由 Alembic DDL
        # 层实现；模型层不写 CheckConstraint，枚举值由应用层校验（与 DDL CHECK 双保险）。
        {"comment": "会话消息"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, comment="user | assistant | tool")
    message_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="text | tool_call | result")
    content: Mapped[str] = mapped_column(
        MEDIUMTEXT, nullable=False, comment="正文；tool_call 存参数/结果摘要"
    )
    tool_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="running | success | failed（仅 tool_call 消息）"
    )
    # 实现扩展字段：支撑「历史回放时按任务分组」与「删除任务级联定位」。
    task_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="产生本条消息的任务（assistant/tool 消息回溯）"
    )
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="会话内单调递增")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )
