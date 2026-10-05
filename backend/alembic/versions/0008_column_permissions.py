"""M2-T3 角色级列权限

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-05

column_meta.hidden_roles: 对该字段不可见的角色编码列表（FR-SEC-15）。
不可见列从 Schema 注入源头剔除，并从白名单校验中移除——双重保障。
"""

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("column_meta", sa.Column("hidden_roles", sa.JSON))
    # combine_mode 需要容纳 "intersect"（9 字符），原 varchar(8) 不够
    op.alter_column("row_policy", "combine_mode", type_=sa.String(16))


def downgrade() -> None:
    op.alter_column("row_policy", "combine_mode", type_=sa.String(8))
    op.drop_column("column_meta", "hidden_roles")
