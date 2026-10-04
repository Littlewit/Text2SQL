"""T1 基础表：用户/角色/数据范围/数据源/审计/系统配置 + 内置角色与管理员种子

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04

- 表结构对应系统设计 §4.2 DDL；
- 内置角色 R-BIZ/R-DA/R-AD/R-AU/R-DEV（§2.1）；
- 内置管理员 admin（首启密码 admin123，must_change_password=true 强制改密，DEP-07）；
- 系统配置默认值（建议基线，P-xx 待定项）。
"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# admin 初始密码 admin123 的 argon2id 哈希（盐固定为迁移期生成值）
_ADMIN_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$dBLOoOjuIun68DjRM3drkw$"
    "YYPGeKfwhHU8zpYmnQ16T1nkAp2WgELDRUwUzsDDkc4"
)

_BUILTIN_ROLES = [
    {"code": "R-BIZ", "name": "业务查询用户"},
    {"code": "R-DA", "name": "数据管理员"},
    {"code": "R-AD", "name": "系统管理员"},
    {"code": "R-AU", "name": "审计员"},
    {"code": "R-DEV", "name": "研发/运维"},
]

_DEFAULT_CONFIGS = [
    ("query.row_limit", "1000", "查询结果集强制行数上限（P-20 待定）"),
    ("query.timeout_s", "30", "单条 SQL 执行超时秒数（P-24，建议 30s）"),
    ("sql_gen.max_retry", "2", "SQL 生成失败最大自动重试次数（P-19）"),
    ("schema.top_k", "10", "Schema 检索 Top-K（P-15 待定）"),
    ("security.login_lockout_threshold", "5", "登录失败锁定阈值（P-32 待定）"),
]


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("display_name", sa.String(128)),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("must_change_password", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("status", sa.SmallInteger, nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "role",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(16), nullable=False, unique=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "user_role",
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("app_user.id"), primary_key=True),
        sa.Column("role_id", sa.BigInteger, sa.ForeignKey("role.id"), primary_key=True),
    )
    op.create_table(
        "data_scope",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("scope_type", sa.String(32), nullable=False),
        sa.Column("scope_value", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "datasource",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("db_type", sa.String(32), nullable=False, server_default="postgres"),
        sa.Column("host", sa.String(256), nullable=False),
        sa.Column("port", sa.BigInteger, nullable=False),
        sa.Column("db_name", sa.String(128), nullable=False),
        sa.Column("readonly_user", sa.String(128), nullable=False),
        sa.Column("credential_enc", sa.String(1024), nullable=False),
        sa.Column("status", sa.SmallInteger, nullable=False, server_default=sa.text("1")),
        sa.Column("created_by", sa.BigInteger),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, index=True),
        sa.Column("action", sa.String(64), nullable=False, index=True),
        sa.Column("object_type", sa.String(64)),
        sa.Column("object_id", sa.String(64)),
        sa.Column("detail", sa.JSON),
        sa.Column("ip", sa.String(64)),
        sa.Column("user_agent", sa.String(256)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "sys_config",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.JSON, nullable=False),
        sa.Column("description", sa.String(256)),
        sa.Column("updated_by", sa.String(64)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- 种子数据：内置角色、管理员、默认配置 ---
    conn = op.get_bind()
    for r in _BUILTIN_ROLES:
        conn.execute(
            sa.text("INSERT INTO role (code, name) VALUES (:code, :name)"),
            r,
        )
    conn.execute(
        sa.text(
            "INSERT INTO app_user (username, display_name, password_hash, must_change_password) "
            "VALUES ('admin', '系统管理员', :h, true)"
        ),
        {"h": _ADMIN_HASH},
    )
    conn.execute(
        sa.text(
            "INSERT INTO user_role (user_id, role_id) "
            "SELECT u.id, r.id FROM app_user u, role r "
            "WHERE u.username = 'admin' AND r.code = 'R-AD'"
        )
    )
    for k, v, d in _DEFAULT_CONFIGS:
        conn.execute(
            sa.text(
                "INSERT INTO sys_config (key, value, description) "
                "VALUES (:k, CAST(:v AS jsonb), :d)"
            ),
            {"k": k, "v": v, "d": d},
        )


def downgrade() -> None:
    op.drop_table("sys_config")
    op.drop_table("audit_log")
    op.drop_table("datasource")
    op.drop_table("data_scope")
    op.drop_table("user_role")
    op.drop_table("role")
    op.drop_table("app_user")
