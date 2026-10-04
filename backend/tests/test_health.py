"""健康探针接口测试。"""

import httpx
from fastapi.testclient import TestClient

from app.main import create_app

client = TestClient(create_app())


def test_healthz_returns_ok():
    """存活探针：200 + ok。"""
    resp = client.get("/api/v1/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


def test_trace_id_injected():
    """每个响应都应携带 trace_id（NFR-M-04），未传时自动生成。"""
    resp = client.get("/api/v1/healthz")
    assert resp.headers.get("X-Request-ID")

    # 上游传入的 X-Request-ID 应被沿用（便于网关关联）
    resp2 = client.get("/api/v1/healthz", headers={"X-Request-ID": "abc123"})
    assert resp2.headers["X-Request-ID"] == "abc123"


def test_readyz_down_returns_503():
    """数据库不可达时，就绪探针应返回 503 而非抛 500（§9.1 最小暴露）。"""
    # conftest 注入的测试 URL 不可达，readyz 应优雅降级
    resp = client.get("/api/v1/readyz")
    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"
