"""数据库基础设施。

业务库与元数据库使用独立连接池（FR-SEC-35）；
本模块当前仅承载元数据库引擎，业务库只读池在 T3（executor）中实现。
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

settings = get_settings()

# 元数据库异步引擎；pool_pre_ping 防止长连接被数据库侧断开后报错
engine = create_async_engine(
    settings.metadata_db_url,
    echo=settings.db_echo,
    pool_size=settings.db_pool_size,
    pool_pre_ping=True,
)

# 会话工厂：expire_on_commit=False 使提交后对象仍可读取，适配 API 序列化场景
session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：每请求一个会话，请求结束自动关闭。"""
    async with session_factory() as session:
        yield session
