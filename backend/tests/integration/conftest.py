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
    """在 dev 实例上重建 text2sql_test 库，返回其 SQLAlchemy 连接串。

    必须在迁移执行前注入环境变量：alembic env.py 通过 app 配置读取 URL，
    若仍保留单测默认值（不可达端口），Windows 上拒绝连接的重试会拖满数百秒。
    """
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

    url = f"postgresql+psycopg://{TEST_USER}:{TEST_PASSWORD}@{TEST_HOST}:{TEST_PORT}/{TEST_DB}"
    os.environ["METADATA_DB_URL"] = url
    os.environ["SECRET_KEY"] = "test-secret"
    return url


@pytest.fixture(scope="session")
def migrated(test_db_url):
    """对测试库执行全部迁移（会话级一次）。"""
    from alembic.config import Config

    from alembic import command

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", test_db_url)
    command.upgrade(cfg, "head")
    return test_db_url


@pytest.fixture()
def client(migrated):
    """每个测试一个全新引擎与 TestClient（同一事件循环上下文）。"""
    # LLM_API_KEY 置空 → get_llm() 返回 FakeLLM（单测 conftest 注入了假 key，此处覆盖）
    os.environ["METADATA_DB_URL"] = migrated
    os.environ["SECRET_KEY"] = "test-secret"
    os.environ["LLM_API_KEY"] = ""

    from app.core.config import get_settings
    from app.infra.db import reset_engine

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


# ---------- 共享业务夹具（T2/T3 用例复用）----------

def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_token(client) -> str:
    """admin 登录令牌（种子账号）。"""
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["token"]


@pytest.fixture()
def datasource_id(client, admin_token) -> int:
    """接入 demo_business 示例数据源（dev 容器同实例的另一库）。"""
    resp = client.post(
        "/api/v1/admin/datasources",
        headers=auth_header(admin_token),
        json={
            "name": "零售演示库",
            "host": "localhost",
            "port": 5433,
            "db_name": "demo_business",
            "readonly_user": "t2s",
            "password": "t2s",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


@pytest.fixture()
def scanned(client, admin_token, datasource_id) -> int:
    """已扫描的示例数据源：需要表元数据的用例使用本夹具。"""
    resp = client.post(
        f"/api/v1/admin/schema/datasources/{datasource_id}/scan", headers=auth_header(admin_token)
    )
    assert resp.status_code == 200, resp.text
    return datasource_id


@pytest.fixture()
def biz_ready(client, admin_token, scanned) -> int:
    """shop/orders 已纳入白名单的数据源（T3 查询链路前置，FR-SCH-03）。"""
    headers = auth_header(admin_token)
    tables = client.get(
        "/api/v1/admin/schema/tables", headers=headers, params={"datasource_id": scanned}
    ).json()["data"]
    by_name = {t["table_name"]: t for t in tables}
    for name, cn, desc in (
        ("shop", "店铺", "店铺主数据，含所属区域（华东/华南/华北）"),
        ("orders", "订单表", "订单主表，含订单日期、状态与实付金额"),
    ):
        r = client.patch(
            f"/api/v1/admin/schema/tables/{by_name[name]['id']}",
            headers=headers, json={"cn_name": cn, "description": desc, "included": True},
        )
        assert r.status_code == 200, r.text
    return scanned
