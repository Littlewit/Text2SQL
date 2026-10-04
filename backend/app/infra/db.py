"""数据库基础设施（惰性初始化）。

引擎在首次使用时创建而非 import 时创建：
一是避免未配置环境下的导入副作用，二是允许测试在导入后注入连接串。
业务库与元数据库使用独立连接池（FR-SEC-35）；业务库只读池在 T3 实现。
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """获取元数据库引擎（惰性单例）；pool_pre_ping 防长连接失效。"""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.metadata_db_url,
            echo=settings.db_echo,
            pool_size=settings.db_pool_size,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """获取会话工厂；expire_on_commit=False 便于提交后序列化。"""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：每请求一个会话，请求结束自动关闭。"""
    async with get_session_factory()() as session:
        yield session


def reset_engine() -> None:
    """测试辅助：丢弃缓存的引擎/工厂，使下一次访问按新配置重建。"""
    global _engine, _session_factory
    _engine = None
    _session_factory = None
