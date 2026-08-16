"""attachments — 会话附件。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mysql import Base


class Attachment(Base):
    """会话附件。"""

    __tablename__ = "attachments"
    __table_args__ = (
        Index("idx_conv", "conversation_id"),
        Index("idx_msg", "message_id"),
        # CHECK 约束 chk_att_ftype / chk_att_pstat 由 Alembic DDL 层实现；
        # 模型层不写 CheckConstraint，枚举值由应用层校验（与 DDL CHECK 双保险）。
        {"comment": "会话附件"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="关联的用户消息（发送时回填）"
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="规范化后文件名")
    file_path: Mapped[str] = mapped_column(String(512), nullable=False, comment="相对 uploads 根的路径")
    file_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="csv | xlsx | txt | md")
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="字节")
    parse_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'pending'"),
        comment="pending | parsing | ready | failed",
    )
    # 实现扩展字段：供 Agent 上下文拼装与删除时 DROP 表定位 / 侧栏失败提示。
    duckdb_table: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="csv/xlsx 导入 DuckDB 后的表名 attachment_data_{id}"
    )
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True, comment="解析失败原因")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )
