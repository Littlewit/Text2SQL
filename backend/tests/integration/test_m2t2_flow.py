"""集成测试：M2-T2 SQL 链路增强（FR-SQL-32/22/21/16、FR-HIS-09、FR-SCH-14 生成注入）。"""

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


def _manual_sql(client, token, ds_id, sql):
    return client.post("/api/v1/query/execute-sql", headers=_auth(token), json={
        "sql": sql, "datasource_id": ds_id})


def test_manual_sql_success_and_warnings(client, admin_token, biz_ready):
    """手工 SQL 成功执行（FR-SQL-32）；索引列函数包裹出提示（FR-SQL-21，非阻断）。"""
    resp = _manual_sql(client, admin_token, biz_ready,
                       "SELECT id, amount FROM orders WHERE amount > 100 LIMIT 5")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["row_count"] <= 5
    assert "LIMIT" in data["sql"].upper()  # 强制行数上限注入

    # order_date 建有索引（demo 库 idx_orders_date），函数包裹 → 非阻断提示
    resp2 = _manual_sql(client, admin_token, biz_ready,
                        "SELECT id FROM orders WHERE DATE(order_date) = '2026-09-01'")
    assert resp2.status_code == 200
    assert any("索引" in w for w in resp2.json()["data"]["warnings"])


def test_manual_sql_blocked_by_guard(client, admin_token, biz_ready):
    """手工 SQL 同权同责（FR-SQL-32、FR-SEC-05）：写操作/越权/系统表全部拦截。"""
    for sql in ("DROP TABLE orders", "SELECT * FROM pg_catalog.pg_tables",
                "SELECT id FROM secret_table"):
        resp = _manual_sql(client, admin_token, biz_ready, sql)
        assert resp.status_code == 422, f"{sql} → {resp.status_code}"


def test_result_rows_pagination(client, admin_token, biz_ready):
    """结果分页取数（FR-SQL-22）：缓存来源翻页零查询。"""
    headers = _auth(admin_token)
    conv = client.post("/api/v1/conversations", headers=headers, json={}).json()["data"]["id"]
    data = client.post("/api/v1/query", headers=headers, json={
        "question": "上个月哪个店铺GMV最高？", "conversation_id": conv, "datasource_id": biz_ready,
    }).json()["data"]
    qid = data["query_id"]

    page1 = client.get(f"/api/v1/query/{qid}/rows", headers=headers,
                       params={"page": 1, "page_size": 1}).json()["data"]
    assert page1["source"] == "cache"
    assert page1["total"] >= 1


def test_history_delete(client, admin_token, biz_ready):
    """历史逻辑删除（FR-HIS-09）：列表不再显示，审计不受影响。"""
    headers = _auth(admin_token)
    conv = client.post("/api/v1/conversations", headers=headers, json={}).json()["data"]["id"]
    client.post("/api/v1/query", headers=headers, json={
        "question": "上个月哪个店铺GMV最高？", "conversation_id": conv, "datasource_id": biz_ready})
    qid = client.get("/api/v1/history", headers=headers).json()["data"]["items"][0]["id"]

    assert client.delete(f"/api/v1/history/{qid}", headers=headers).status_code == 200
    hist = client.get("/api/v1/history", headers=headers).json()["data"]
    assert all(i["id"] != qid for i in hist["items"])


def test_join_paths_injected_into_prompt(client, admin_token, biz_ready):
    """JOIN 路径注入 Prompt（FR-SCH-14）：多表生成的关联关系有据可依。"""
    from app.llm.client import _fake_llm

    headers = _auth(admin_token)
    # 创建 shop↔orders 关联路径
    tables = client.get("/api/v1/admin/schema/tables", headers=headers,
                        params={"datasource_id": biz_ready}).json()["data"]
    by_name = {t["table_name"]: t["id"] for t in tables}
    jp = client.post("/api/v1/admin/join-paths", headers=headers, json={
        "datasource_id": biz_ready, "left_table_id": by_name["orders"],
        "right_table_id": by_name["shop"], "left_column": "shop_id", "right_column": "id"})
    assert jp.status_code == 201

    calls_before = len(_fake_llm.calls)
    conv = client.post("/api/v1/conversations", headers=headers, json={}).json()["data"]["id"]
    client.post("/api/v1/query", headers=headers, json={
        "question": "上个月哪个店铺GMV最高？", "conversation_id": conv, "datasource_id": biz_ready})
    sql_prompt = _fake_llm.calls[calls_before + 1]  # 第二次调用为 SQL 生成
    assert "表关联关系" in sql_prompt and "shop_id" in sql_prompt


def test_guard_blocked_functions_configurable(client, admin_token):
    """校验规则配置化（FR-SQL-16）：sys_config 注入自定义黑名单。"""
    from app.services.sql_guard import GuardContext, validate

    ctx = GuardContext(
        allowed_tables={"orders": {"id", "amount"}},
        row_limit=100,
        blocked_functions={"abs", "pg_sleep"},  # 管理员经 sys_config 扩展
    )
    result, errs = validate("SELECT ABS(amount) FROM orders", ctx)
    assert not result.ok and errs[0].stage == "sensitive"
