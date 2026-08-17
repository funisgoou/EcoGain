"""system_configs — 系统配置（热更新）。"""

from datetime import datetime

from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy import BigInteger, DateTime, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mysql import Base


class SystemConfigModel(Base):
    """系统配置（热更新）。"""

    __tablename__ = "system_configs"
    __table_args__ = (
        UniqueConstraint("config_key", name="uk_key"),
        Index("idx_group", "config_group"),
        {"comment": "系统配置（热更新）"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    config_key: Mapped[str] = mapped_column(String(128), nullable=False, comment="如 llm.model")
    config_value: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="敏感项存 key 引用，不明文"
    )
    config_group: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="llm | agent | datasource | feature"
    )
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        MySQLDateTime(fsp=3),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(3)"),
        server_onupdate=text("CURRENT_TIMESTAMP(3)"),
    )
