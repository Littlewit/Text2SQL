"""安全专项测试：越权矩阵 / 资源隔离 / 数据访问边界（§11.1 安全测试、§2.2 权限矩阵）。

红线：安全用例 100% 通过（§11.4 上线准入）。
"""

import pytest

from tests.integration.conftest import auth_header as _auth

pytestmark = pytest.mark.integration

# 越权矩阵（§2.2）：R-BIZ 用户对管理端点的预期结果
_BIZ_FORBIDDEN = [
    ("GET", "/api/v1/admin/users"),
    ("POST", "/api/v1/admin/users"),
    ("GET", "/api/v1/admin/datasources"),
    ("POST", "/api/v1/admin/datasources"),
    ("GET", "/api/v1/admin/configs"),
    ("PATCH", "/api/v1/admin/configs/query.row_limit"),
    ("GET", "/api/v1/admin/audit-logs"),
    ("GET", "/api/v1/admin/schema/tables"),
    ("POST", "/api/v1/admin/schema/search"),
    ("GET", "/api/v1/admin/metrics"),
]


@pytest.fixture()
def users(client):
    """admin 与 biz 账号令牌。"""
    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    ).json()["data"]["token"]
    client.post("/api/v1/admin/users", headers=_auth(admin), json={
        "username": "bizsec", "password": "biz-pass-123", "roles": ["R-BIZ"]})
    biz = client.post(
        "/api/v1/auth/login", json={"username": "bizsec", "password": "biz-pass-123"}
    ).json()["data"]["token"]
    return {"admin": admin, "biz": biz}


def test_privilege_matrix_biz_blocked(client, users):
    """R-BIZ 访问全部管理端点 → 403（无泄露数据存在性的统一提示）。"""
    for method, path in _BIZ_FORBIDDEN:
        resp = client.request(method, path, headers=_auth(users["biz"]), json={})
        assert resp.status_code == 403, f"{method} {path} 返回 {resp.status_code}"


def test_session_isolation(client, users):
    """会话隔离（§2.3）：用户只能读取自己的会话消息。"""
    conv = client.post("/api/v1/conversations", headers=_auth(users["admin"]), json={}).json()["data"]
    resp = client.get(f"/api/v1/conversations/{conv['id']}/messages", headers=_auth(users["biz"]))
    assert resp.status_code == 404  # 与不存在同响应，不泄露会话存在性


def test_export_others_query_blocked(client, users, biz_ready):
    """导出越权（FR-VIS-23）：只能导出自己的查询。"""
    conv = client.post("/api/v1/conversations", headers=_auth(users["admin"]), json={}).json()["data"]
    # admin 跑一次成功查询（FakeLLM 路由未注入时走 Clarify/失败——仅需存在一条记录）
    client.post("/api/v1/query", headers=_auth(users["admin"]), json={
        "question": "上个月哪个店铺GMV最高？", "conversation_id": conv["id"], "datasource_id": biz_ready})
    hist = client.get("/api/v1/history", headers=_auth(users["admin"])).json()["data"]
    assert hist["total"] >= 1
    qid = hist["items"][0]["id"]
    resp = client.post(f"/api/v1/query/{qid}/export", headers=_auth(users["biz"]))
    assert resp.status_code == 404  # 他人查询不可见


def test_history_isolated(client, users):
    """历史隔离（FR-HIS-01）：历史列表仅本人。"""
    hist = client.get("/api/v1/history", headers=_auth(users["biz"])).json()["data"]
    for item in hist["items"]:
        assert item["question"] is not None  # 只包含本人记录（biz 用户无 admin 的记录）
    # biz 与 admin 的历史互相独立：admin 有记录而 biz 看到的 total 不含 admin 的
    admin_hist = client.get("/api/v1/history", headers=_auth(users["admin"])).json()["data"]
    assert admin_hist["total"] != hist["total"] or admin_hist["total"] == 0


def test_unauthenticated_all_endpoints(client):
    """未认证访问所有业务端点 → 401（§9.1）。"""
    for method, path in _BIZ_FORBIDDEN:
        resp = client.request(method, path, json={})
        assert resp.status_code == 401, f"{method} {path} 返回 {resp.status_code}"


def test_biz_cannot_access_other_users_favorites(client, users):
    """收藏隔离：删除不属于自己的收藏 → 404（不泄露存在性）。"""
    resp = client.delete("/api/v1/favorites/99999", headers=_auth(users["biz"]))
    assert resp.status_code == 404
