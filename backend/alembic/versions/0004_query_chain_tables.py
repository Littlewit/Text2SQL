"""T3 查询链路表：会话/消息/查询历史/Few-shot/行级权限策略

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, nullable=False, index=True),
        sa.Column("title", sa.String(256)),
        sa.Column("context", sa.JSON),
        sa.Column("status", sa.SmallInteger, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "message",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.BigInteger, sa.ForeignKey("conversation.id"), nullable=False, index=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.JSON, nullable=False),
        sa.Column("seq", sa.BigInteger, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "query_history",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.BigInteger, index=True),
        sa.Column("user_id", sa.BigInteger, nullable=False, index=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("intent", sa.String(32)),
        sa.Column("entities", sa.JSON),
        sa.Column("recalled_schema", sa.JSON),
        sa.Column("prompt_template_version", sa.String(64)),
        sa.Column("generated_sql", sa.Text),
        sa.Column("explain_text", sa.Text),
        sa.Column("assumptions", sa.JSON),
        sa.Column("validate_result", sa.JSON),
        sa.Column("exec_status", sa.String(32), nullable=False),
        sa.Column("error_code", sa.BigInteger),
        sa.Column("row_count", sa.BigInteger),
        sa.Column("result_sample", sa.JSON),
        sa.Column("duration_ms", sa.BigInteger),
        sa.Column("llm_tokens", sa.BigInteger),
        sa.Column("chart_config", sa.JSON),
        sa.Column("retry_count", sa.SmallInteger, server_default=sa.text("0")),
        sa.Column("is_deleted", sa.Boolean, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "few_shot",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("datasource_id", sa.BigInteger, index=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("sql_text", sa.Text, nullable=False),
        sa.Column("intent", sa.String(32)),
        sa.Column("explanation", sa.Text),
        sa.Column("status", sa.SmallInteger, server_default=sa.text("1")),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("hit_count", sa.BigInteger, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "row_policy",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("datasource_id", sa.BigInteger, nullable=False, index=True),
        sa.Column("table_meta_id", sa.BigInteger, nullable=False),
        sa.Column("filter_template", sa.Text, nullable=False),
        sa.Column("apply_to_role_ids", sa.JSON, nullable=False),
        sa.Column("combine_mode", sa.String(8), server_default="union"),
        sa.Column("enabled", sa.Boolean, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("row_policy")
    op.drop_table("few_shot")
    op.drop_table("query_history")
    op.drop_table("message")
    op.drop_table("conversation")
