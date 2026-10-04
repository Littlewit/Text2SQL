"""集成测试环境供给。

不再使用 testcontainers（其在 Windows 上等待容器就绪的探测会挂起），
改为复用 docker-compose.dev.yml 提供的 PostgreSQL 实例，并在其中
创建一次性的 `text2sql_test` 测试数据库（每次会话重建，保证干净状态）。

前置条件：docker compose -f docker-compose.dev.yml up -d postgres
CI 中由 GitHub Actions 的 services 容器提供同样的连接地址（ENV-03）。
"""

import os

import pytest

# 集成库连接信息：dev 容器把 5432 映射到宿主机 5433
TEST_HOST = os.environ.get("ITEST_DB_HOST", "localhost")
TEST_PORT = os.environ.get("ITEST_DB_PORT", "5433")
TEST_USER = os.environ.get("ITEST_DB_USER", "t2s")
TEST_PASSWORD = os.environ.get("ITEST_DB_PASSWORD", "t2s")
TEST_DB = "text2sql_test"


@pytest.fixture(scope="session")
def test_db_url():
    """在 dev 实例上重建 text2sql_test 库，返回其 SQLAlchemy 连接串。"""
    import psycopg

    conninfo = f"host={TEST_HOST} port={TEST_PORT} dbname=text2sql_meta user={TEST_USER} password={TEST_PASSWORD}"
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (TEST_DB,),
        )
        conn.execute(f'DROP DATABASE IF EXISTS {TEST_DB}')
        conn.execute(f'CREATE DATABASE {TEST_DB}')

    return f"postgresql+psycopg://{TEST_USER}:{TEST_PASSWORD}@{TEST_HOST}:{TEST_PORT}/{TEST_DB}"


@pytest.fixture(scope="session")
def migrated(test_db_url):
    """对测试库执行全部迁移（会话级一次）。"""
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", test_db_url)
    command.upgrade(cfg, "head")
    return test_db_url


@pytest.fixture()
def client(migrated):
    """每个测试一个全新引擎与 TestClient（同一事件循环上下文）。"""
    os.environ["METADATA_DB_URL"] = migrated
    os.environ["SECRET_KEY"] = "test-secret"

    from app.core.config import get_settings
    from app.infra.db import reset_engine
    from app.main import create_app

    get_settings.cache_clear()
    reset_engine()
    with TestClientWrapper() as tc:
        yield tc


class TestClientWrapper:
    """延迟导入的 TestClient 上下文包装，避免模块导入期引入 app。"""

    def __enter__(self):
        from starlette.testclient import TestClient

        from app.main import create_app

        self._client = TestClient(create_app())
        self._client.__enter__()
        return self._client

    def __exit__(self, *args):
        return self._client.__exit__(*args)
