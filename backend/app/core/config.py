"""应用配置。

所有配置项通过环境变量 / .env 注入（DEP-03），镜像内不含任何密钥（KEY-01）。
命名规则：环境变量名 = 字段名大写，例如 METADATA_DB_URL。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置项。默认值仅供本地开发使用，生产必须通过 .env 覆盖。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- 应用 ---
    app_name: str = "Text2SQL 智能数据分析平台"
    debug: bool = False
    api_prefix: str = "/api/v1"

    # --- 元数据库（PostgreSQL + pgvector，全环境统一，DR-07）---
    metadata_db_url: str = "postgresql+psycopg://t2s:t2s@localhost:5432/text2sql_meta"
    db_echo: bool = False
    db_pool_size: int = 10

    # --- Redis（Celery broker + 限流计数器）---
    redis_url: str = "redis://localhost:6379/0"

    # --- LLM（DeepSeek，Q-07 确认前默认云端 API）---
    llm_api_key: str = ""  # 仅环境变量注入，禁止写入代码仓库（KEY-01）
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_timeout_s: float = 30.0

    # --- Embedding（维度须与模型一致，DR-04）---
    embedding_model: str = ""
    embedding_dim: int = 1024

    # --- 时区（DEP-09：相对时间解析基准）---
    timezone: str = "Asia/Shanghai"


@lru_cache
def get_settings() -> Settings:
    """返回全局单例配置；lru_cache 保证进程内只解析一次环境变量。"""
    return Settings()
