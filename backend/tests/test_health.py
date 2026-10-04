"""健康探针接口测试。"""

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


def test_readyz_down_returns_503(monkeypatch):
    """数据库不可达时，就绪探针应返回 503 而非抛 500（§9.1 最小暴露）。

    用桩模拟连接失败而非真实连接不可达地址：Windows 对关闭端口的 TCP 超时可达分钟级，
    会拖慢单元测试；连接失败行为已在集成测试中用真实容器覆盖。
    """
    import sqlalchemy.exc

    class _BrokenConn:
        def __init__(self, exc):
            self._exc = exc

        async def __aenter__(self):
            raise self._exc

        async def __aexit__(self, *args):
            return False

    def _broken_engine():
        class _E:
            def connect(self):
                return _BrokenConn(sqlalchemy.exc.OperationalError("down", {}, None))

        return _E()

    monkeypatch.setattr("app.api.v1.health.get_engine", _broken_engine)
    resp = client.get("/api/v1/readyz")
    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"
