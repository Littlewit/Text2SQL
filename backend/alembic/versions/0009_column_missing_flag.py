"""M2-T5：column_meta 增加 missing 标记（FR-SCH-04 增量同步影响提示）。

Revision ID: 0009
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "column_meta",
        sa.Column("missing", sa.Boolean(), nullable=False, server_default=sa.text("false"),
                  comment="源库扫描时该字段已不存在（FR-SCH-04）"),
    )


def downgrade() -> None:
    op.drop_column("column_meta", "missing")
