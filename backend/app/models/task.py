"""analysis_tasks — 分析任务。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mysql import Base


class AnalysisTask(Base):
    """分析任务（一条用户消息一个任务）。"""

    # 并发检查用（TASK-2）：单会话单任务与全局 ≤5 并发由应用层保证（SPEC 4.5）。
    ACTIVE_STATUSES: tuple[str, ...] = ("queued", "running")

    __tablename__ = "analysis_tasks"
    __table_args__ = (
        Index("idx_conv", "conversation_id"),
        Index("idx_status", "task_status"),
        Index("idx_trace", "trace_id"),
        # CHECK 约束 chk_task_status 由 Alembic DDL 层实现；模型层不写
        # CheckConstraint，枚举值由应用层校验（与 DDL CHECK 双保险）。
        {"comment": "分析任务（一条用户消息一个任务）"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_ids: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, comment="本轮引用的附件 id 逗号分隔（实现扩展）"
    )
    task_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'queued'"),
        comment="queued | running | success | failed | cancelled",
    )
    current_step: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="planning | querying | summarizing"
    )
    trace_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="链路追踪（实现扩展，日志关联）"
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(3), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(3), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )
