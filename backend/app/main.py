"""FastAPI 应用工厂（§2.3）。"""

import asyncio
import sys

# Windows 默认 ProactorEventLoop 与 psycopg 异步模式不兼容（生产 Linux 容器不受影响）
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI

from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.tracing import TraceIdMiddleware

settings = get_settings()


def create_app() -> FastAPI:
    """创建应用实例。生产关闭 docs 公网暴露（DEP-08）。"""
    app = FastAPI(
        title=settings.app_name,
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
    )
    app.add_middleware(TraceIdMiddleware)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
