"""可观测性（NFR-O-01~04）：JSON 结构化日志 + Prometheus 指标。

- 日志输出 stdout（DEP-06），生产 JSON 行格式，trace_id 贯穿（NFR-O-04）；
- 日志中不得包含明文敏感数据（NFR-O-02）——敏感值由调用方脱敏后再记；
- /metrics 由 prometheus_client 暴露（NFR-O-01），生产仅供内网抓取。
"""

import json
import logging
from datetime import datetime, timezone

from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.tracing import get_trace_id

# --- 指标定义（模块级单例，避免重复注册）---
HTTP_REQUESTS = Counter(
    "t2s_http_requests_total", "HTTP 请求总数", ["method", "path", "status"]
)
HTTP_DURATION = Histogram(
    "t2s_http_request_duration_seconds", "HTTP 请求耗时", ["method", "path"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 15, 30, 60),
)
QUERIES = Counter(
    "t2s_queries_total", "查询总数", ["status"]  # success/failed/clarify/refused
)
LLM_TOKENS = Counter("t2s_llm_tokens_total", "LLM token 用量")
RETRIES = Counter("t2s_sql_gen_retries_total", "SQL 生成自愈重试次数")


class JsonFormatter(logging.Formatter):
    """生产日志格式：单行 JSON，便于容器日志采集与检索（DEP-06、NFR-O-02）。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": get_trace_id(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(debug: bool = False) -> None:
    """应用日志初始化：debug 用人类可读格式，生产用 JSON。"""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    handler = logging.StreamHandler()
    if debug:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    else:
        handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    # 第三方库降噪
    for noisy in ("uvicorn.access", "httpx", "httpcore", "alembic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class MetricsMiddleware(BaseHTTPMiddleware):
    """请求指标中间件（NFR-O-01）：计数 + 耗时直方图。"""

    async def dispatch(self, request: Request, call_next):
        method = request.method
        # 路径模板化，避免高基数（/query/123 → /query/{id}）
        path = "/" + "/".join(
            seg if not seg.isdigit() else "{id}" for seg in request.url.path.strip("/").split("/")
        )
        with HTTP_DURATION.labels(method, path).time():
            response = await call_next(request)
        HTTP_REQUESTS.labels(method, path, str(response.status_code)).inc()
        return response
