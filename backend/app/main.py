"""FastAPI 应用工厂（§2.3）。"""

import asyncio
import logging
import sys

# Windows 默认 ProactorEventLoop 与 psycopg 异步模式不兼容（生产 Linux 容器不受影响）
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI

from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.errors import AppError, app_error_handler
from app.core.obs import MetricsMiddleware, setup_logging
from app.core.tracing import TraceIdMiddleware

settings = get_settings()
setup_logging(settings.debug)


def create_app() -> FastAPI:
    """创建应用实例。生产关闭 docs 公网暴露（DEP-08）。"""
    app = FastAPI(
        title=settings.app_name,
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
    )
    app.add_middleware(TraceIdMiddleware)
    app.add_middleware(MetricsMiddleware)  # 注意：后添加的中间件先执行（包裹外层）
    app.include_router(api_router, prefix=settings.api_prefix)
    # 业务异常统一转响应包络（§6.4），堆栈不进响应体
    app.add_exception_handler(AppError, app_error_handler)

    # 未捕获异常兜底（M3）：记录完整堆栈到日志（NFR-O-02），对外返回统一包络
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request, exc):  # noqa: ANN001
        logging.getLogger("t2s.unhandled").exception(
            "unhandled error: %s %s", request.method, request.url.path
        )
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=500,
            content={"code": 50000, "message": "服务器内部错误", "data": None},
        )

    # Prometheus 指标端点（NFR-O-01）：挂载在根路径，生产仅供内网抓取（Nginx 限制）
    from prometheus_client import make_asgi_app

    app.mount("/metrics", make_asgi_app())
    return app


app = create_app()
