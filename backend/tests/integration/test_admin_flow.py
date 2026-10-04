"""集成测试：认证与管理底座全链路（T1）。

依赖 docker-compose.dev.yml 提供的 PostgreSQL（见本目录 conftest.py）。
运行方式：pytest -m integration
"""

import pytest

pytestmark = pytest.mark.integration


def _login(client, username, password) -> dict | None:
    """登录辅助：返回 data 或 None。"""
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    return resp.json()["data"] if resp.status_code == 200 else None


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_login_and_me(client):
    """admin 使用种子密码登录 → /me 返回 R-AD 角色 → 强制改密标记为真。"""
    data = _login(client, "admin", "admin123")
    assert data is not None
    assert data["user"]["must_change_password"] is True
    assert "R-AD" in data["user"]["roles"]

    me = client.get("/api/v1/auth/me", headers=_auth(data["token"]))
    assert me.status_code == 200
    assert me.json()["data"]["username"] == "admin"


def test_login_wrong_password(client):
    """错误密码 → 40102；响应不泄露用户是否存在。"""
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401
    assert resp.json()["code"] == 40102


def test_admin_permission_guard(client):
    """R-BIZ 用户访问 R-AD 专属接口 → 403（权限矩阵 §2.2 服务端强制）。"""
    admin_token = _login(client, "admin", "admin123")["token"]

    resp = client.post(
        "/api/v1/admin/users",
        headers=_auth(admin_token),
        json={
            "username": "zhang运营",
            "password": "biz-pass-123",
            "roles": ["R-BIZ"],
            "scopes": [{"scope_type": "shop", "scope_value": "华东一店"}],
        },
    )
    assert resp.status_code == 201
    biz_token = _login(client, "zhang运营", "biz-pass-123")["token"]

    denied = client.get("/api/v1/admin/users", headers=_auth(biz_token))
    assert denied.status_code == 403
    # 登录用户仍可访问自己的 /me
    me = client.get("/api/v1/auth/me", headers=_auth(biz_token))
    assert me.status_code == 200


def test_unauthenticated_rejected(client):
    """无 token 访问受保护接口 → 40101。"""
    resp = client.get("/api/v1/admin/users")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40101


def test_datasource_create_and_test(client):
    """数据源接入 → 连通性测试用 dev 容器 PG 真实验证；凭据不回显（KEY-02）。"""
    admin_token = _login(client, "admin", "admin123")["token"]
    headers = _auth(admin_token)

    resp = client.post(
        "/api/v1/admin/datasources",
        headers=headers,
        json={
            "name": "零售演示库",
            "host": "localhost",
            "port": 5433,  # 测试运行于宿主机：dev 容器映射 5432→5433
            "db_name": "text2sql_meta",
            "readonly_user": "t2s",
            "password": "t2s",
        },
    )
    assert resp.status_code == 201
    ds_id = resp.json()["data"]["id"]
    assert "password" not in resp.json()["data"]  # 凭据不回显

    test_resp = client.post(f"/api/v1/admin/datasources/{ds_id}/test", headers=headers)
    assert test_resp.status_code == 200
    assert test_resp.json()["data"]["ok"] is True


def test_config_update_and_audit(client):
    """配置变更留痕：旧值/新值均可在审计日志中追溯（DR 变更留痕要求）。"""
    admin_token = _login(client, "admin", "admin123")["token"]
    headers = _auth(admin_token)

    resp = client.patch(
        "/api/v1/admin/configs/query.row_limit", headers=headers, json={"value": 500}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["value"] == 500

    logs = client.get(
        "/api/v1/admin/audit-logs", headers=headers, params={"action": "admin.config.update"}
    ).json()["data"]
    assert logs["total"] >= 1
    assert logs["items"][0]["detail"]["old"] == 1000  # 种子默认值
    assert logs["items"][0]["detail"]["new"] == 500


def test_audit_log_immune_to_normal_user(client):
    """R-BIZ 用户无法检索审计日志（矩阵：仅 R-AD/R-AU）。"""
    token = _login(client, "zhang运营", "biz-pass-123")["token"]
    resp = client.get("/api/v1/admin/audit-logs", headers=_auth(token))
    assert resp.status_code == 403
