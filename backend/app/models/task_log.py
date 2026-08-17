"""task_logs — 任务运行日志。"""

from datetime import datetime

from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy import BigInteger, DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mysql import Base


class TaskLog(Base):
    """任务运行日志。"""

    __tablename__ = "task_logs"
    __table_args__ = (
        Index("idx_task_created", "task_id", "created_at"),
        # CHECK 约束 chk_log_level 由 Alembic DDL 层实现；模型层不写
        # CheckConstraint，log_level 枚举值由应用层校验（与 DDL CHECK 双保险）。
        {"comment": "任务运行日志"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    log_level: Mapped[str] = mapped_column(String(16), nullable=False, comment="info | warn | error")
    log_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="llm_call | tool_exec | status | summary"
    )
    log_content: Mapped[str] = mapped_column(Text, nullable=False, comment="≤2000 字，含结构化摘要")
    created_at: Mapped[datetime] = mapped_column(
        MySQLDateTime(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )
