"""系统配置模型（§5.1 sys_config、FR-ADM-05）。

全部待定参数以建议基线落为默认值，业务方确认后经管理 API 调整，变更留痕。
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.models.base import Base


class SysConfig(Base):
    """key-value 系统配置，value 为 JSONB 以容纳数值/字符串/对象。"""

    __tablename__ = "sys_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | list | int | float | str | None] = mapped_column(JSON)
    description: Mapped[str | None] = mapped_column(String(256))
    updated_by: Mapped[int | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
