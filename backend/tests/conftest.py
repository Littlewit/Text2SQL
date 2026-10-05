"""pytest 全局 fixture。

- 单元测试不依赖数据库；
- 集成测试标记 @pytest.mark.integration，由 testcontainers 启动真实 PostgreSQL+pgvector
  （ENV-03：禁止用内存数据库替代，保证与生产同构）。
"""

import os

import pytest

# 单测环境强制注入测试配置：
# - 端口 54399 保证不可达（本机可能运行原生 PG，避免误连）
# - 固定 SECRET_KEY 使令牌测试可复现
os.environ.setdefault("METADATA_DB_URL", "postgresql+psycopg://test:test@localhost:54399/test")
os.environ.setdefault("SECRET_KEY", "test-secret")
# 强制走 FakeLLM 替身：即使本机配了 DEEPSEEK_API_KEY/LLM_API_KEY 也禁用真实调用
# （避免测试产生真实 API 计费与不确定性；AliasChoices 下置空串即视为未配置）
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["LLM_API_KEY"] = ""


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
