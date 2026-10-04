"""T2 Schema 元数据表：表/字段标注、指标、同义词、枚举、JOIN 路径、向量索引、变更历史

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "table_meta",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("datasource_id", sa.BigInteger, sa.ForeignKey("datasource.id"), nullable=False, index=True),
        sa.Column("schema_name", sa.String(128), nullable=False),
        sa.Column("table_name", sa.String(128), nullable=False),
        sa.Column("cn_name", sa.String(128)),
        sa.Column("description", sa.Text),
        sa.Column("row_estimate", sa.BigInteger, server_default=sa.text("0")),
        sa.Column("included", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("annotation_score", sa.Numeric(5, 2)),
        sa.Column("scan_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("datasource_id", "schema_name", "table_name", name="uq_table_meta"),
    )
    op.create_table(
        "column_meta",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("table_meta_id", sa.BigInteger, sa.ForeignKey("table_meta.id"), nullable=False, index=True),
        sa.Column("column_name", sa.String(128), nullable=False),
        sa.Column("cn_name", sa.String(128)),
        sa.Column("data_type", sa.String(64), nullable=False),
        sa.Column("nullable", sa.Boolean, server_default=sa.true()),
        sa.Column("is_pk", sa.Boolean, server_default=sa.false()),
        sa.Column("is_fk", sa.Boolean, server_default=sa.false()),
        sa.Column("fk_ref", sa.String(256)),
        sa.Column("description", sa.Text),
        sa.Column("unit", sa.String(32)),
        sa.Column("usage_type", sa.String(16)),
        sa.Column("is_sensitive", sa.Boolean, server_default=sa.false()),
        sa.Column("sample_values", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("table_meta_id", "column_name", name="uq_column_meta"),
    )
    op.create_table(
        "metric",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("datasource_id", sa.BigInteger, index=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("description", sa.Text),
        sa.Column("formula", sa.JSON),
        sa.Column("agg_type", sa.String(16)),
        sa.Column("default_time_column", sa.String(256)),
        sa.Column("unit", sa.String(32)),
        sa.Column("status", sa.SmallInteger, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "synonym",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("term", sa.String(128), nullable=False, index=True),
        sa.Column("target_type", sa.String(16), nullable=False),
        sa.Column("target_id", sa.BigInteger, nullable=False),
        sa.Column("datasource_id", sa.BigInteger, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "enum_dict",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("column_meta_id", sa.BigInteger, sa.ForeignKey("column_meta.id"), nullable=False),
        sa.Column("raw_value", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("column_meta_id", "raw_value", name="uq_enum_dict"),
    )
    op.create_table(
        "join_path",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("datasource_id", sa.BigInteger, nullable=False, index=True),
        sa.Column("left_table_id", sa.BigInteger, sa.ForeignKey("table_meta.id"), nullable=False),
        sa.Column("right_table_id", sa.BigInteger, sa.ForeignKey("table_meta.id"), nullable=False),
        sa.Column("left_column", sa.String(128), nullable=False),
        sa.Column("right_column", sa.String(128), nullable=False),
        sa.Column("join_type", sa.String(16), server_default="inner"),
        sa.Column("description", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "schema_embedding",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("object_type", sa.String(16), nullable=False, index=True),
        sa.Column("object_id", sa.BigInteger, nullable=False),
        sa.Column("datasource_id", sa.BigInteger, index=True),
        sa.Column("content_text", sa.Text, nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("object_type", "object_id", "model_version", name="uq_schema_embedding"),
    )
    # HNSW 向量索引（cosine 距离），支撑 Top-K 语义检索（FR-SCH-21）
    op.execute(
        "CREATE INDEX idx_schema_embedding_hnsw ON schema_embedding "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.create_table(
        "meta_revision",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("object_type", sa.String(32), nullable=False, index=True),
        sa.Column("object_id", sa.BigInteger, nullable=False, index=True),
        sa.Column("snapshot", sa.JSON, nullable=False),
        sa.Column("op", sa.String(16), nullable=False),
        sa.Column("operator_id", sa.BigInteger),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("meta_revision")
    op.drop_table("schema_embedding")
    op.drop_table("join_path")
    op.drop_table("enum_dict")
    op.drop_table("synonym")
    op.drop_table("metric")
    op.drop_table("column_meta")
    op.drop_table("table_meta")
