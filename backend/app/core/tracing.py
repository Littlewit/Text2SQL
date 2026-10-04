"""trace_id 中间件。

为每个请求生成/继承 trace_id，贯穿全链路日志与审计（NFR-M-04、NFR-O-04）。
上游（如 Nginx）传入的 X-Request-ID 会被沿用，便于网关侧关联。
"""

import contextvars
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# 进程级上下文变量：日志过滤器据此取出当前请求的 trace_id
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")

TRACE_HEADER = "X-Request-ID"


class TraceIdMiddleware(BaseHTTPMiddleware):
    """为每个 HTTP 请求分配 trace_id 并写入响应头。"""

    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get(TRACE_HEADER) or uuid.uuid4().hex
        trace_id_var.set(trace_id)
        response = await call_next(request)
        response.headers[TRACE_HEADER] = trace_id
        return response


def get_trace_id() -> str:
    """供日志/审计代码读取当前请求的 trace_id。"""
    return trace_id_var.get()
