"""数据源模型（§5.1 datasource）。

凭据仅存 AES-GCM 密文（credential_enc，KEY-02），
接口层永不回显明文；连接一律使用只读账号（FR-SCH-06、FR-SEC-03）。
"""

from sqlalchemy import BigInteger, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.models.base import Base, IntPkMixin


class Datasource(IntPkMixin, Base):
    """已接入的业务数据源。db_type 本期固定 postgres（FR-SQL-02 方言唯一目标）。"""

    __tablename__ = "datasource"

    name: Mapped[str] = mapped_column(String(128))
    db_type: Mapped[str] = mapped_column(String(32), default="postgres")
    host: Mapped[str] = mapped_column(String(256))
    port: Mapped[int] = mapped_column(BigInteger, default=5432)
    db_name: Mapped[str] = mapped_column(String(128))
    readonly_user: Mapped[str] = mapped_column(String(128))
    credential_enc: Mapped[str] = mapped_column(String(1024))  # AES-GCM 密文
    status: Mapped[int] = mapped_column(SmallInteger, default=1)  # 1=启用 0=停用
    created_by: Mapped[int | None] = mapped_column(BigInteger)  # 接入操作人
