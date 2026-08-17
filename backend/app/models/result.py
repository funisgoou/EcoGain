"""analysis_results — 六段结构化分析结果。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime, JSON, MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mysql import Base


class AnalysisResult(Base):
    """六段结构化分析结果（一任务一行）。"""

    __tablename__ = "analysis_results"
    __table_args__ = (
        UniqueConstraint("task_id", name="uk_task"),
        Index("idx_conv", "conversation_id"),
        {"comment": "六段结构化分析结果（一任务一行）"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    conversation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    problem_definition: Mapped[str] = mapped_column(Text, nullable=False)
    key_metrics_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="数组，元素结构见 §6.3")
    evidence_list_json: Mapped[list] = mapped_column(JSON, nullable=False, comment="数组，元素结构见 §6.3")
    conclusion_text: Mapped[str] = mapped_column(Text, nullable=False)
    missing_data_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action_text: Mapped[str] = mapped_column(Text, nullable=False)
    result_markdown: Mapped[str] = mapped_column(
        MEDIUMTEXT, nullable=False, comment="完整 Markdown 渲染（复制/展示用）"
    )
    result_file_path: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="exports 相对路径；未导出为 NULL"
    )
    created_at: Mapped[datetime] = mapped_column(
        MySQLDateTime(fsp=3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )
