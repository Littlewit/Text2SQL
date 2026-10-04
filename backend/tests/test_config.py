"""配置加载测试。"""

from app.core.config import Settings


def test_settings_from_env(monkeypatch):
    """配置应能从环境变量注入（DEP-03）。"""
    monkeypatch.setenv("METADATA_DB_URL", "postgresql+psycopg://u:p@h:5432/db")
    monkeypatch.setenv("EMBEDDING_DIM", "768")
    s = Settings(_env_file=None)  # 忽略 .env 文件，仅用环境变量
    assert s.metadata_db_url == "postgresql+psycopg://u:p@h:5432/db"
    assert s.embedding_dim == 768


def test_default_timezone_is_shanghai():
    """时区默认 Asia/Shanghai（DEP-09，相对时间解析基准）。"""
    s = Settings(_env_file=None)
    assert s.timezone == "Asia/Shanghai"


def test_pg_driver_is_psycopg():
    """连接串驱动必须为 psycopg（ENV-04：全环境统一 PostgreSQL，不留 SQLite 分支）。"""
    s = Settings(_env_file=None)
    assert s.metadata_db_url.startswith("postgresql+psycopg://")
