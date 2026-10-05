"""收藏与分享模型（§5.1 favorite/share/share_access，FR-HIS-04~07）。"""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.models.base import Base, IntPkMixin


class Favorite(IntPkMixin, Base):
    """收藏查询：存「问题 + 配置」，重执行以自身权限（FR-HIS-04，§2.3 分享不扩权）。

    params.dynamic_time = true 时，时间条件在每次执行时按当前日期重算（FR-HIS-05，
    时间解析器天然支持相对表述重算，见 AC-10）。
    """

    __tablename__ = "favorite"

    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(128))
    question: Mapped[str] = mapped_column(String(1000))
    datasource_id: Mapped[int] = mapped_column(BigInteger)
    params: Mapped[dict | None] = mapped_column(JSON)
    group_name: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(String(256))
    conversation_id: Mapped[int | None] = mapped_column(BigInteger)  # 重执行时复用会话上下文


class Share(Base):
    """分享：只含问题/SQL 模板/图表配置，不含结果数据（§3.5）；token 不可枚举（SEC-09）。"""

    __tablename__ = "share"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    question: Mapped[str] = mapped_column(String(1000))
    conversation_id: Mapped[int | None] = mapped_column(BigInteger)
    datasource_id: Mapped[int] = mapped_column(BigInteger)
    share_type: Mapped[str] = mapped_column(String(16), default="link")  # link / direct
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    target_user_ids: Mapped[str | None] = mapped_column(String(256))  # 定向分享：逗号分隔
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShareAccess(Base):
    """分享访问记录（FR-HIS-07）。"""

    __tablename__ = "share_access"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    share_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("share.id"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
