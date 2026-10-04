"""声明式 Base。全部模型使用 SQLAlchemy 2.0 typed style（NFR-M-05）。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """全部 ORM 模型的基类。"""

    def to_dict(self) -> dict:
        """通用序列化：排除内部字段，datetime 转 ISO 字符串。"""
        result = {}
        for c in self.__table__.columns:
            v = getattr(self, c.name)
            result[c.name] = v.isoformat() if isinstance(v, datetime) else v
        return result


class IntPkMixin:
    """统一主键与创建时间。"""

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
