"""初始化：启用 pgvector 扩展

Revision ID: 0001
Revises:
Create Date: 2026-10-04

启用 pgvector 向量扩展（FR-SCH-20、DR-07）。
要求数据库由 pgvector/pgvector 系列镜像提供，或已在实例上安装扩展文件。
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 容器内默认用户为超级用户，可安装扩展；生产元数据库需授权相应权限
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # 不执行 DROP EXTENSION：删除扩展会级联删除所有向量数据，风险过高
    pass
