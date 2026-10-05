"""集成测试：M2-T1 数据质量闭环（FR-UI-08、FR-ADM-04/08）。

核心验收：用户纠错 → 管理员审核采纳 → 自动转启用的 Few-shot 样例
→ 向量化召回命中（反馈驱动准确率提升的完整闭环）。
"""

import json

import pytest

from app.core.rate_limit import reset_rate_limits
from app.llm.client import clear_fake_routes, reset_breaker, set_fake_routes
from app.services.nlu.intent import NLU_MARKER
from app.services.sql_gen.generator import SQL_GEN_MARKER
from tests.integration.conftest import auth_header as _auth

pytestmark = pytest.mark.integration

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
    "assumptions": [], "confidence": 0.9, "explain": "x",
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


def _run_query(client, token, ds_id):
    conv = client.post("/api/v1/conversations", headers=_auth(token), json={}).json()["data"]["id"]
    resp = client.post("/api/v1/query", headers=_auth(token), json={
        "question": "上个月哪个店铺GMV最高？", "conversation_id": conv, "datasource_id": ds_id})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_feedback_and_sample_closed_loop(client, admin_token, biz_ready):
    """纠错 → 审核采纳 → 自动建样例 → 召回命中（R-10 闭环验证）。"""
    headers = _auth(admin_token)
    data = _run_query(client, admin_token, biz_ready)
    qid = data["query_id"]

    # 1) 用户提交 down + 纠错 SQL
    fb = client.post(f"/api/v1/query/{qid}/feedback", headers=headers, json={
        "rating": "down",
        "correction_sql": ("SELECT s.name, SUM(o.amount) FROM orders o "
                           "JOIN shop s ON s.id = o.shop_id GROUP BY s.name"),
        "comment": "应该看所有店铺而不是第一名",
    })
    assert fb.status_code == 201
    assert fb.json()["data"]["review_status"] == "pending"

    # 2) 重复提交被拒（同用户同查询一次）
    assert client.post(f"/api/v1/query/{qid}/feedback", headers=headers, json={
        "rating": "up"}).status_code == 409

    # 3) 管理员审核采纳 → 自动生成启用的样例
    pending = client.get("/api/v1/admin/feedbacks", headers=headers).json()["data"]
    assert len(pending) >= 1
    review = client.post(
        f"/api/v1/admin/feedbacks/{pending[0]['id']}/review",
        headers=headers, params={"approve": True},
    )
    assert review.status_code == 200
    assert review.json()["data"]["review_status"] == "approved"
    sample_id = review.json()["data"]["sample_id"]
    assert sample_id is not None

    # 4) 样例库中可见且启用、有命中计数
    shots = client.get("/api/v1/admin/few-shots", headers=headers,
                       params={"status": 1}).json()["data"]
    hit = next(s for s in shots if s["id"] == sample_id)
    assert hit["status"] == 1

    # 5) 召回闭环：再次查询（相似问题）后样例命中计数增加
    _run_query(client, admin_token, biz_ready)
    after = client.get("/api/v1/admin/few-shots", headers=headers).json()["data"]
    assert next(s for s in after if s["id"] == sample_id)["hit_count"] >= 1


def test_feedback_rejected_no_sample(client, admin_token, biz_ready):
    """驳回的纠错反馈不生成样例。"""
    headers = _auth(admin_token)
    data = _run_query(client, admin_token, biz_ready)
    fb = client.post(f"/api/v1/query/{data['query_id']}/feedback", headers=headers, json={
        "rating": "down", "correction_sql": "SELECT 1", "comment": "随便写的"})
    fb_id = fb.json()["data"]["id"]
    review = client.post(f"/api/v1/admin/feedbacks/{fb_id}/review",
                         headers=headers, params={"approve": False})
    assert review.json()["data"]["review_status"] == "rejected"
    assert review.json()["data"]["sample_id"] is None


def test_biz_cannot_review_feedback(client, admin_token, biz_ready):
    """审核是 R-DA/R-AD 专属（§2.2），R-BIZ 不可审核。"""
    client.post("/api/v1/admin/users", headers=_auth(admin_token), json={
        "username": "bizfb", "password": "biz-pass-123", "roles": ["R-BIZ"]})
    token = client.post("/api/v1/auth/login",
                        json={"username": "bizfb", "password": "biz-pass-123"}).json()["data"]["token"]
    resp = client.get("/api/v1/admin/feedbacks", headers=_auth(token))
    assert resp.status_code == 403


def test_uncaptured_questions(client, admin_token):
    """未覆盖问题分析（FR-ADM-08）：澄清/拒答/失败问题聚合统计。"""
    headers = _auth(admin_token)
    # 注入澄清与拒答路由制造未覆盖记录
    set_fake_routes({
        NLU_MARKER: json.dumps({
            "intent": "stat", "out_of_scope": False, "refuse_reason": None,
            "clarify": {"question": "想看什么指标？", "options": ["GMV"]}, "entities": {},
        }, ensure_ascii=False)})
    conv = client.post("/api/v1/conversations", headers=headers, json={}).json()["data"]["id"]
    client.post("/api/v1/query", headers=headers, json={
        "question": "看看销售情况", "conversation_id": conv, "datasource_id": 1})
    clear_fake_routes()

    data = client.get("/api/v1/admin/uncaptured", headers=headers).json()["data"]
    assert data["total_uncovered"] >= 1
    assert any(i["question"] == "看看销售情况" for i in data["items"])


def test_fewshot_crud_and_review(client, admin_token):
    """样例 CRUD：录入→待审核→审核启用→更新→删除（FR-ADM-04）。"""
    headers = _auth(admin_token)
    created = client.post("/api/v1/admin/few-shots", headers=headers, json={
        "question": "这个季度卖了多少", "sql_text": "SELECT COUNT(*) FROM orders",
        "intent": "stat", "explanation": "季度订单计数"})
    assert created.status_code == 201
    fs_id = created.json()["data"]["id"]
    assert created.json()["data"]["status"] == 2  # 待审核

    # 待审核样例审核后启用
    client.post(f"/api/v1/admin/few-shots/{fs_id}/review", headers=headers, params={"approve": True})
    enabled = client.get("/api/v1/admin/few-shots", headers=headers,
                         params={"status": 1}).json()["data"]
    assert any(s["id"] == fs_id for s in enabled)

    # 更新（触发重新向量化）
    patched = client.patch(f"/api/v1/admin/few-shots/{fs_id}", headers=headers,
                           json={"explanation": "更新说明"})
    assert patched.json()["data"]["explanation"] == "更新说明"

    # 删除
    assert client.delete(f"/api/v1/admin/few-shots/{fs_id}", headers=headers).status_code == 200
    assert all(s["id"] != fs_id for s in client.get(
        "/api/v1/admin/few-shots", headers=headers).json()["data"])
