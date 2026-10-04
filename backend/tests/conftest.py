"""pytest 全局 fixture。

单测不依赖数据库；需要真实 PostgreSQL+pgvector 的集成测试标记 @pytest.mark.integration，
由 testcontainers 启动容器（ENV-03：禁止用内存数据库替代）。
"""

import os

import pytest

# 单测环境强制注入测试配置，避免读取开发者本地 .env 造成结果不确定
os.environ.setdefault("METADATA_DB_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("LLM_API_KEY", "test-key")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
