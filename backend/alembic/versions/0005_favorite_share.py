"""T4 收藏与分享表

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-05
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "favorite",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, nullable=False, index=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("question", sa.String(1000), nullable=False),
        sa.Column("datasource_id", sa.BigInteger, nullable=False),
        sa.Column("params", sa.JSON),
        sa.Column("group_name", sa.String(64)),
        sa.Column("note", sa.String(256)),
        sa.Column("conversation_id", sa.BigInteger),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "share",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.BigInteger, nullable=False, index=True),
        sa.Column("question", sa.String(1000), nullable=False),
        sa.Column("conversation_id", sa.BigInteger),
        sa.Column("datasource_id", sa.BigInteger, nullable=False),
        sa.Column("share_type", sa.String(16), server_default="link"),
        sa.Column("token", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("target_user_ids", sa.String(256)),
        sa.Column("expire_at", sa.DateTime(timezone=True)),
        sa.Column("revoked", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "share_access",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("share_id", sa.BigInteger, sa.ForeignKey("share.id"), nullable=False, index=True),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("accessed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("share_access")
    op.drop_table("share")
    op.drop_table("favorite")
