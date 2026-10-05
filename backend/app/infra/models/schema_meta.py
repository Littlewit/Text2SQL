"""Schema 元数据模型（§5.1 table_meta/column_meta/metric/synonym/enum_dict/join_path/
schema_embedding/meta_revision，对应系统设计 §4.2 DDL）。"""

from datetime import datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import get_settings
from app.infra.models.base import Base, IntPkMixin


class TableMeta(IntPkMixin, Base):
    """表元数据：扫描结果 + 业务标注。included=true 才进入检索候选池（FR-SCH-03）。"""

    __tablename__ = "table_meta"
    __table_args__ = (UniqueConstraint("datasource_id", "schema_name", "table_name"),)

    datasource_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("datasource.id"), index=True)
    schema_name: Mapped[str] = mapped_column(String(128))
    table_name: Mapped[str] = mapped_column(String(128))
    cn_name: Mapped[str | None] = mapped_column(String(128))  # 中文名标注（FR-SCH-10）
    description: Mapped[str | None] = mapped_column(Text)  # 业务含义标注
    row_estimate: Mapped[int] = mapped_column(BigInteger, default=0)
    included: Mapped[bool] = mapped_column(Boolean, default=False)  # 白名单纳入
    annotation_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))  # 完整度（FR-SCH-15）
    indexes: Mapped[dict | list | None] = mapped_column(JSON)  # 索引元数据 [{name, columns}]（FR-SQL-21）
    scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    columns: Mapped[list["ColumnMeta"]] = relationship(
        back_populates="table_meta", lazy="selectin", cascade="all, delete-orphan"
    )


class ColumnMeta(IntPkMixin, Base):
    """字段元数据：物理信息（扫描）+ 业务语义（标注）。"""

    __tablename__ = "column_meta"
    __table_args__ = (UniqueConstraint("table_meta_id", "column_name"),)

    table_meta_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("table_meta.id"), index=True)
    column_name: Mapped[str] = mapped_column(String(128))
    cn_name: Mapped[str | None] = mapped_column(String(128))
    data_type: Mapped[str] = mapped_column(String(64))
    nullable: Mapped[bool] = mapped_column(Boolean, default=True)
    is_pk: Mapped[bool] = mapped_column(Boolean, default=False)
    is_fk: Mapped[bool] = mapped_column(Boolean, default=False)
    fk_ref: Mapped[str | None] = mapped_column(String(256))  # 如 "shop.id"
    description: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(32))  # 单位：元/%/件
    usage_type: Mapped[str | None] = mapped_column(String(16))  # dimension / metric / both
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)  # 敏感标记（FR-SEC-20）
    hidden_roles: Mapped[dict | list | None] = mapped_column(JSON)  # 对这些角色不可见（FR-SEC-15）
    sample_values: Mapped[dict | list | None] = mapped_column(JSON)  # 低基数枚举采样（FR-SCH-05）

    table_meta: Mapped["TableMeta"] = relationship(back_populates="columns")


class Metric(IntPkMixin, Base):
    """指标定义：口径由业务方给出，生成链路必须引用而非让 LLM 自造（FR-SCH-12、R-01）。"""

    __tablename__ = "metric"

    datasource_id: Mapped[int | None] = mapped_column(BigInteger, index=True)  # 空表示全局指标
    name: Mapped[str] = mapped_column(String(128))  # 中文名，如 GMV
    code: Mapped[str] = mapped_column(String(64), unique=True)  # 如 gmv
    description: Mapped[str | None] = mapped_column(Text)  # 业务口径说明
    formula: Mapped[dict | None] = mapped_column(JSON)  # 结构化公式，如 {"expr": "SUM(orders.amount)"}
    agg_type: Mapped[str | None] = mapped_column(String(16))  # sum/count/avg/...
    default_time_column: Mapped[str | None] = mapped_column(String(256))  # 默认时间字段
    unit: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[int] = mapped_column(SmallInteger, default=1)  # 1=启用


class Synonym(IntPkMixin, Base):
    """同义词映射：「销售额」→ metric:gmv 等（FR-SCH-13）。"""

    __tablename__ = "synonym"

    term: Mapped[str] = mapped_column(String(128), index=True)  # 业务词
    target_type: Mapped[str] = mapped_column(String(16))  # metric / column / dimension_value
    target_id: Mapped[int] = mapped_column(BigInteger)
    datasource_id: Mapped[int | None] = mapped_column(BigInteger, index=True)


class EnumDict(IntPkMixin, Base):
    """枚举字典：原始值 → 业务名（FR-SCH-11）。生成 SQL 用原始值，展示用业务名。"""

    __tablename__ = "enum_dict"
    __table_args__ = (UniqueConstraint("column_meta_id", "raw_value"),)

    column_meta_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("column_meta.id"))
    raw_value: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(String(128))


class JoinPath(IntPkMixin, Base):
    """表关联路径：业务关联显式维护，避免笛卡尔积（FR-SCH-14）。"""

    __tablename__ = "join_path"

    datasource_id: Mapped[int] = mapped_column(BigInteger, index=True)
    left_table_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("table_meta.id"))
    right_table_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("table_meta.id"))
    left_column: Mapped[str] = mapped_column(String(128))
    right_column: Mapped[str] = mapped_column(String(128))
    join_type: Mapped[str] = mapped_column(String(16), default="inner")
    description: Mapped[str | None] = mapped_column(Text)


class SchemaEmbedding(Base):
    """向量索引：表/字段/指标/同义词的语义表示（FR-SCH-20，pgvector）。"""

    __tablename__ = "schema_embedding"
    __table_args__ = (UniqueConstraint("object_type", "object_id", "model_version"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    object_type: Mapped[str] = mapped_column(String(16), index=True)  # table/column/metric/synonym
    object_id: Mapped[int] = mapped_column(BigInteger)
    datasource_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    content_text: Mapped[str] = mapped_column(Text)  # 参与向量化的文本（可解释，FR-SCH-24）
    embedding = mapped_column(Vector(get_settings().embedding_dim))  # 维度须与模型一致（DR-04）
    model_version: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MetaRevision(IntPkMixin, Base):
    """元数据变更历史：写前快照，支持回滚（DR-03、FR-ADM-03）。"""

    __tablename__ = "meta_revision"

    object_type: Mapped[str] = mapped_column(String(32), index=True)  # table/column/metric/...
    object_id: Mapped[int] = mapped_column(BigInteger, index=True)
    snapshot: Mapped[dict] = mapped_column(JSON)  # 变更前完整快照
    op: Mapped[str] = mapped_column(String(16))  # update / delete
    operator_id: Mapped[int | None] = mapped_column(BigInteger)
