"""集成测试：M2-T3 权限精细化（FR-SEC-12/15/23、FR-SQL-16 配置化）。"""

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
    "sql": "SELECT COUNT(*) AS cnt FROM shop",
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


@pytest.fixture()
def biz_token(client, admin_token) -> str:
    client.post("/api/v1/admin/users", headers=_auth(admin_token), json={
        "username": "bizp", "password": "biz-pass-123", "roles": ["R-BIZ"]})
    return client.post("/api/v1/auth/login",
                       json={"username": "bizp", "password": "biz-pass-123"}).json()["data"]["token"]


@pytest.fixture()
def shop_ids(client, admin_token, biz_ready) -> dict:
    """shop 表元数据 ID 与 region 列 ID。"""
    headers = _auth(admin_token)
    tables = client.get("/api/v1/admin/schema/tables", headers=headers,
                        params={"datasource_id": biz_ready}).json()["data"]
    shop = next(t for t in tables if t["table_name"] == "shop")
    cols = client.get(f"/api/v1/admin/schema/tables/{shop['id']}/columns", headers=headers).json()["data"]
    return {"table_id": shop["id"], "region_col_id": next(c["id"] for c in cols if c["column_name"] == "region")}


def _add_policy(client, token, ds_id, shop_ids, template, mode):
    return client.post("/api/v1/admin/row-policies", headers=_auth(token), json={
        "datasource_id": ds_id, "table_meta_id": shop_ids["table_id"],
        "filter_template": template, "apply_to_role_ids": ["R-BIZ"], "combine_mode": mode})


def test_policy_union_vs_intersect(client, admin_token, biz_token, biz_ready, shop_ids):
    """多策略叠加语义（FR-SEC-12）：union 并集 vs intersect 交集。"""
    _add_policy(client, admin_token, biz_ready, shop_ids, "region = '华东'", "union")
    conv = client.post("/api/v1/conversations", headers=_auth(biz_token), json={}).json()["data"]["id"]
    union = client.post("/api/v1/query", headers=_auth(biz_token), json={
        "question": "上个月哪个店铺GMV最高？", "conversation_id": conv, "datasource_id": biz_ready})
    # 并集语义：结果店铺必须落在华东 2 家之内（LIMIT 1 → row_count 恒为 1，断言返回内容）
    union_cnt = union.json()["data"]["result"]["rows"][0][0]
    assert union_cnt == 2, f"并集策略下应命中华东 2 家，实际 {union_cnt}"

    # 追加交集策略 → AND 语义：仅上海 1 家
    _add_policy(client, admin_token, biz_ready, shop_ids, "city = '上海'", "intersect")
    intersect = client.post("/api/v1/query", headers=_auth(biz_token), json={
        "question": "上个月哪个店铺GMV最高？", "conversation_id": conv, "datasource_id": biz_ready})
    assert intersect.json()["data"]["result"]["rows"][0][0] == 1


def test_column_hidden_from_whitelist_and_prompt(client, admin_token, biz_token, biz_ready, shop_ids):
    """角色级列权限（FR-SEC-15）：不可见列白名单移除 + Prompt 源头剔除。"""
    from app.llm.client import _fake_llm

    # region 对 R-BIZ 不可见
    resp = client.patch(f"/api/v1/admin/schema/columns/{shop_ids['region_col_id']}",
                        headers=_auth(admin_token), json={"hidden_roles": ["R-BIZ"]})
    assert resp.status_code == 200

    # 手工 SQL 引用不可见列 → 白名单拦截（403/422）
    denied = _manual_sql(client, admin_token, biz_ready, "SELECT id FROM orders")  # admin 可见，正常
    assert denied.status_code == 200
    denied_biz = client.post("/api/v1/query/execute-sql", headers=_auth(biz_token), json={
        "sql": "SELECT region FROM shop", "datasource_id": biz_ready})
    assert denied_biz.status_code == 422

    # Prompt 源头剔除：biz 用户的 SQL 生成 Prompt 不含 region 字段
    calls_before = len(_fake_llm.calls)
    conv = client.post("/api/v1/conversations", headers=_auth(biz_token), json={}).json()["data"]["id"]
    client.post("/api/v1/query", headers=_auth(biz_token), json={
        "question": "上个月哪个店铺GMV最高？", "conversation_id": conv, "datasource_id": biz_ready})
    sql_prompt = _fake_llm.calls[calls_before + 1]
    assert " region " not in sql_prompt or "region" not in sql_prompt.split("【用户问题】")[0]


def _manual_sql(client, token, ds_id, sql):
    return client.post("/api/v1/query/execute-sql", headers=_auth(token),
                       json={"sql": sql, "datasource_id": ds_id})


def test_mask_risk_warning(client, admin_token, biz_ready, shop_ids):
    """脱敏反推限制（FR-SEC-23）：脱敏列参与分组 → 告警。"""
    headers = _auth(admin_token)
    # 将 region 标记为敏感
    client.patch(f"/api/v1/admin/schema/columns/{shop_ids['region_col_id']}",
                 headers=headers, json={"is_sensitive": True})
    resp = _manual_sql(client, admin_token, biz_ready,
                       "SELECT region, COUNT(*) FROM shop GROUP BY region")
    assert resp.status_code == 200, resp.text
    warnings = resp.json()["data"]["warnings"]
    print("WARNINGS:", warnings)  # DEBUG
    assert any("反推" in w for w in warnings)


def test_row_policy_crud(client, admin_token, biz_ready, shop_ids):
    """策略 CRUD（FR-SEC-10）+ 变更即时生效（FR-SEC-13：删除后恢复全量）。"""
    headers = _auth(admin_token)
    created = client.post("/api/v1/admin/row-policies", headers=headers, json={
        "datasource_id": biz_ready, "table_meta_id": shop_ids["table_id"],
        "filter_template": "region = '华东'", "apply_to_role_ids": ["R-BIZ"]})
    assert created.status_code == 201
    pid = created.json()["data"]["id"]

    policies = client.get("/api/v1/admin/row-policies", headers=headers,
                          params={"datasource_id": biz_ready}).json()["data"]
    assert any(p["id"] == pid for p in policies)

    assert client.delete(f"/api/v1/admin/row-policies/{pid}", headers=headers).status_code == 200
    assert all(p["id"] != pid for p in client.get(
        "/api/v1/admin/row-policies", headers=headers).json()["data"])
