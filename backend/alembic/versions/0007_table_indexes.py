"""M2-T2 表索引元数据

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-05

索引信息支撑 FR-SQL-21（索引友好提示）：扫描时采集 pg_indexes，
以 [{name, columns: [...]}] 形式存 JSONB。
"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("table_meta", sa.Column("indexes", sa.JSON))


def downgrade() -> None:
    op.drop_column("table_meta", "indexes")
