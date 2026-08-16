"""context_summaries — 历史消息 LLM 摘要。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mysql import Base


class ContextSummary(Base):
    """历史消息 LLM 摘要（区间互不重叠，由应用层保证）。"""

    __tablename__ = "context_summaries"
    __table_args__ = (
        Index("idx_conv", "conversation_id"),
        Index("idx_conv_range", "conversation_id", "start_seq_no", "end_seq_no"),
        {"comment": "历史消息 LLM 摘要（区间互不重叠，由应用层保证）"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    start_seq_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="覆盖消息区间起（含）")
    end_seq_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="覆盖消息区间止（含）")
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )
