"""Alembic 迁移环境（异步引擎版）。

URL 统一取自应用配置，保证迁移与运行时连接同一数据库（ENV-04/05）。
迁移脚本只针对 PostgreSQL 编写，可使用 jsonb/vector 等原生类型（ENV-05）。
"""

import asyncio
import sys
from logging.config import fileConfig

# Windows 默认的 ProactorEventLoop 与 psycopg 异步模式不兼容，需切换 Selector 事件循环
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 将应用配置中的数据库 URL 注入 alembic；
# 若调用方（如测试）已显式配置 URL，则不覆盖，保证注入优先
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", get_settings().metadata_db_url)

target_metadata = None  # T1 引入 ORM models 后改为 Base.metadata


def run_migrations_offline() -> None:
    """离线模式：仅生成 SQL 脚本，不连接数据库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """在线模式：使用异步引擎执行迁移。"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
