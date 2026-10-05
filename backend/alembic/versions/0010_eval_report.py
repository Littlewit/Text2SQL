"""M2-T6：评测报告表（FR-ADM-07 评测管理）。

Revision ID: 0010
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eval_report",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("mode", sa.String(16), nullable=False, comment="offline / full"),
        sa.Column("status", sa.String(16), nullable=False, server_default="running",
                  comment="running / done / failed"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pass_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("by_tag", sa.JSON(), comment="分维度统计"),
        sa.Column("failures", sa.JSON(), comment="失败用例明细（截断）"),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("model_version", sa.String(64), comment="评测时的 LLM 模型标识"),
        sa.Column("operator_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("eval_report")
