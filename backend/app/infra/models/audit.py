"""审计日志模型（§5.1 audit_log、FR-SEC-42/43）。

审计记录只增不改不删：不提供任何更新/删除 API；
保留期由定时清理任务管理（T5），应用层无删除入口。
"""


from sqlalchemy import JSON, BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.models.base import Base, IntPkMixin


class AuditLog(IntPkMixin, Base):
    """全量审计日志：登录、提问、SQL、导出、分享、权限与元数据变更等。"""

    __tablename__ = "audit_log"

    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    # 动作标识，如 auth.login / admin.config.update
    action: Mapped[str] = mapped_column(String(64), index=True)
    object_type: Mapped[str | None] = mapped_column(String(64))
    object_id: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict | None] = mapped_column(JSON)  # 变更摘要；敏感值须先脱敏（FR-SEC-44）
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(256))
