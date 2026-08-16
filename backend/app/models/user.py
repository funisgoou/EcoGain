"""users — 平台用户。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, UniqueConstraint, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db.mysql import Base


class User(Base):
    """平台用户（登录回调时 upsert）。"""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("external_user_id", name="uk_external_user_id"),
        Index("idx_username", "username"),
        # CHECK 约束 chk_users_role / chk_users_status 由 Alembic DDL 层实现；
        # 模型层不写 CheckConstraint，枚举值由应用层校验（与 DDL CHECK 双保险）。
        {"comment": "平台用户（登录回调时 upsert）"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    external_user_id: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="认证中心用户唯一标识（auth_users.id）"
    )
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False, server_default=text("''"))
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'analyst'"), comment="analyst | admin"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'active'"), comment="active | disabled"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(3), nullable=False, server_default=text("CURRENT_TIMESTAMP(3)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(3),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(3)"),
        server_onupdate=text("CURRENT_TIMESTAMP(3)"),
    )

    @classmethod
    async def upsert_from_oauth(
        cls,
        session: AsyncSession,
        external_id: str,
        username: str,
        display_name: str,
        role: str,
    ) -> "User":
        """按 external_user_id upsert（AUTH-5 用）。

        不存在则插入（status 默认 active）；存在则更新 username/display_name/role。
        """
        result = await session.execute(select(User).where(User.external_user_id == external_id))
        user: User | None = result.scalar_one_or_none()
        if user is None:
            user = User(
                external_user_id=external_id,
                username=username,
                display_name=display_name,
                role=role,
                status="active",
            )
            session.add(user)
        else:
            user.username = username
            user.display_name = display_name
            user.role = role
        await session.flush()
        return user
