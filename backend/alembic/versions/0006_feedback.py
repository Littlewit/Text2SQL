"""M2-T1 反馈表

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-05
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 查询历史补充数据源归属（样例库创建/统计需要）
    op.add_column(
        "query_history",
        sa.Column("datasource_id", sa.BigInteger, nullable=True, index=True),
    )
    op.create_table(
        "feedback",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("query_history_id", sa.BigInteger, sa.ForeignKey("query_history.id"), nullable=False, index=True),
        sa.Column("user_id", sa.BigInteger, nullable=False, index=True),
        sa.Column("rating", sa.String(8), nullable=False),
        sa.Column("correction_sql", sa.Text),
        sa.Column("comment", sa.Text),
        sa.Column("review_status", sa.String(16), nullable=False, server_default="pending", index=True),
        sa.Column("reviewer_id", sa.BigInteger),
        sa.Column("sample_id", sa.BigInteger),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("feedback")
    op.drop_column("query_history", "datasource_id")
