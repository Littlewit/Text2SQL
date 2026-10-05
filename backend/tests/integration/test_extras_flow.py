"""集成测试：T4 收藏 / 分享 / 导出 / 建议追问（FR-HIS-04~07、FR-VIS-20、FR-UI-04）。

依赖 FakeLLM 成功链路路由（同 test_query_flow）与已标注数据源。
"""

import json

import pytest

from app.core.rate_limit import reset_rate_limits
from app.llm.client import clear_fake_routes, reset_breaker, set_fake_routes
from app.services.nlu.intent import NLU_MARKER
from app.services.sql_gen.generator import SQL_GEN_MARKER
from tests.integration.conftest import auth_header as _auth

pytestmark = pytest.mark.integration


async def _reset_state():
    """复位熔断器与限流器（跨用例状态隔离）。"""
    reset_breaker()
    await reset_rate_limits()

_NLU_OK = json.dumps({
    "intent": "stat", "out_of_scope": False, "refuse_reason": None, "clarify": None,
    "entities": {"time_expression": "上个月", "metrics": ["GMV"], "dimensions": ["店铺"],
                 "filters": [], "order": "desc", "limit": 1, "time_granularity": None},
}, ensure_ascii=False)

_SQL_OK = json.dumps({
    "sql": ("SELECT s.name AS shop_name, SUM(o.amount) AS gmv "
            "FROM orders o JOIN shop s ON s.id = o.shop_id "
            "WHERE o.order_date >= '2026-09-01' AND o.order_date <= '2026-09-30' "
            "GROUP BY s.name ORDER BY gmv DESC LIMIT 1"),
    "assumptions": ["GMV 按订单实付金额求和"], "confidence": 0.9, "explain": "统计上个月各店铺GMV取最高",
}, ensure_ascii=False)


@pytest.fixture(autouse=True)
def _fake_routes():
    reset_breaker()
    reset_rate_limits()
    set_fake_routes({NLU_MARKER: _NLU_OK, SQL_GEN_MARKER: _SQL_OK})
    yield
    clear_fake_routes()
    reset_breaker()
    reset_rate_limits()


def _run_query(client, token, conv_id, ds_id, question="上个月哪个店铺GMV最高？"):
    resp = client.post("/api/v1/query", headers=_auth(token), json={
        "question": question, "conversation_id": conv_id, "datasource_id": ds_id,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_favorite_create_run_delete(client, admin_token, biz_ready):
    """收藏创建 → 重执行（时间按当前日期重算，AC-10）→ 删除（FR-HIS-04/05）。"""
    headers = _auth(admin_token)
    resp = client.post("/api/v1/favorites", headers=headers, json={
        "name": "店铺GMV月报", "question": "上个月哪个店铺GMV最高？",
        "datasource_id": biz_ready, "params": {"dynamic_time": True},
    })
    assert resp.status_code == 201
    fav_id = resp.json()["data"]["id"]

    conv_id = client.post("/api/v1/conversations", headers=headers, json={}).json()["data"]["id"]
    _run_query(client, admin_token, conv_id, biz_ready)  # 先跑一次确保链路可用

    run = client.post(f"/api/v1/favorites/{fav_id}/run", headers=headers)
    assert run.status_code == 200, run.text
    assert run.json()["data"]["exec_status"] == "success"
    assert run.json()["data"]["result"]["row_count"] == 1

    # 列表与删除
    favs = client.get("/api/v1/favorites", headers=headers).json()["data"]
    assert any(f["id"] == fav_id for f in favs)
    assert client.delete(f"/api/v1/favorites/{fav_id}", headers=headers).status_code == 200


def test_share_open_and_revoke(client, admin_token, biz_ready):
    """分享创建 → 他人打开（重执行语义）→ 撤销后失效（FR-HIS-06/07、SEC-09）。"""
    headers = _auth(admin_token)
    conv_id = client.post("/api/v1/conversations", headers=headers, json={}).json()["data"]["id"]
    data = _run_query(client, admin_token, conv_id, biz_ready)

    share = client.post("/api/v1/shares", headers=headers, json={
        "datasource_id": biz_ready, "query_history_id": data["query_id"],
    })
    assert share.status_code == 201
    token = share.json()["data"]["token"]

    # 创建接收方账号并以接收方身份打开分享
    client.post("/api/v1/admin/users", headers=headers, json={
        "username": "receiver", "password": "rcv-pass-123", "roles": ["R-BIZ"]})
    rcv_token = client.post(
        "/api/v1/auth/login", json={"username": "receiver", "password": "rcv-pass-123"}
    ).json()["data"]["token"]
    opened = client.get(f"/api/v1/shares/{token}", headers=_auth(rcv_token))
    assert opened.status_code == 200
    assert opened.json()["data"]["question"] == "上个月哪个店铺GMV最高？"

    # 接收方以自身权限重新执行分享的问题（§3.5）
    rcv_conv = client.post("/api/v1/conversations", headers=_auth(rcv_token), json={}).json()["data"]["id"]
    rerun = client.post("/api/v1/query", headers=_auth(rcv_token), json={
        "question": opened.json()["data"]["question"],
        "conversation_id": rcv_conv, "datasource_id": opened.json()["data"]["datasource_id"],
    })
    assert rerun.status_code == 200
    assert rerun.json()["data"]["exec_status"] == "success"

    # 撤销 → 再打开 403
    share_id = share.json()["data"]["id"]
    assert client.delete(f"/api/v1/shares/{share_id}", headers=headers).status_code == 200
    denied = client.get(f"/api/v1/shares/{token}", headers=_auth(rcv_token))
    assert denied.status_code == 403


def test_export_excel(client, admin_token, biz_ready):
    """Excel 导出（FR-VIS-20/23）：可下载、内容为已脱敏数据、导出留审计。"""
    headers = _auth(admin_token)
    conv_id = client.post("/api/v1/conversations", headers=headers, json={}).json()["data"]["id"]
    data = _run_query(client, admin_token, conv_id, biz_ready)

    resp = client.post(f"/api/v1/query/{data['query_id']}/export", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/vnd.openxmlformats")

    # 导出行为入审计（FR-VIS-23）
    logs = client.get(
        "/api/v1/admin/audit-logs", headers=headers, params={"action": "export.excel"}
    ).json()["data"]
    assert logs["total"] >= 1


def test_suggest_followups(client, admin_token, biz_ready):
    """建议追问（FR-UI-04）：按问题与图表类型规则生成。"""
    headers = _auth(admin_token)
    conv_id = client.post("/api/v1/conversations", headers=headers, json={}).json()["data"]["id"]
    data = _run_query(client, admin_token, conv_id, biz_ready)

    resp = client.get(
        "/api/v1/suggest/followups", headers=headers, params={"query_id": data["query_id"]}
    ).json()["data"]
    assert resp["suggestions"], "应给出建议追问"
    assert all(isinstance(s, str) for s in resp["suggestions"])
