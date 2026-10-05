"""集成测试：M2-T5 运营看板与治理（FR-ADM-06、FR-SEC-33/43、FR-SCH-04）。"""

import json

import pytest

from app.core.quota import reset_quotas
from app.core.rate_limit import reset_rate_limits
from app.llm.client import clear_fake_routes, reset_breaker, set_fake_routes
from app.services.nlu.intent import NLU_MARKER
from app.services.sql_gen.generator import SQL_GEN_MARKER
from tests.integration.conftest import auth_header as _auth

pytestmark = pytest.mark.integration

_NLU_OK = json.dumps({
    "intent": "stat", "out_of_scope": False, "refuse_reason": None, "confidence": 0.95,
    "clarify": None,
    "entities": {"time_expression": "上个月", "metrics": ["GMV"], "dimensions": ["店铺"],
                 "filters": [], "order": "desc", "limit": 1, "time_granularity": "按月"},
}, ensure_ascii=False)

_SQL_OK = json.dumps({
    "sql": ("SELECT s.name AS shop_name, SUM(o.amount) AS gmv "
            "FROM orders o JOIN shop s ON s.id = o.shop_id "
            "WHERE o.order_date >= '2026-09-01' AND o.order_date <= '2026-09-30' "
            "GROUP BY s.name ORDER BY gmv DESC LIMIT 5"),
    "assumptions": ["GMV 按实付金额"], "confidence": 0.9, "explain": "x",
}, ensure_ascii=False)


@pytest.fixture(autouse=True)
def _fake_routes():
    reset_breaker()
    reset_rate_limits()
    reset_quotas()
    set_fake_routes({NLU_MARKER: _NLU_OK, SQL_GEN_MARKER: _SQL_OK})
    yield
    clear_fake_routes()
    reset_breaker()
    reset_rate_limits()
    reset_quotas()


def _run_query(client, token, ds_id, question="上个月哪个店铺GMV最高？"):
    conv = client.post("/api/v1/conversations", headers=_auth(token), json={}).json()["data"]["id"]
    return client.post("/api/v1/query", headers=_auth(token), json={
        "question": question, "conversation_id": conv, "datasource_id": ds_id})


def test_dashboard_aggregates_queries(client, admin_token, biz_ready):
    """运营看板（FR-ADM-06）：与查询历史同源聚合，指标一致。"""
    headers = _auth(admin_token)
    resp = _run_query(client, admin_token, biz_ready)
    assert resp.status_code == 200

    board = client.get("/api/v1/admin/ops/dashboard", headers=headers,
                       params={"days": 7}).json()["data"]
    assert board["summary"]["total"] >= 1
    assert board["summary"]["success"] >= 1
    assert 0 < board["summary"]["success_rate"] <= 1
    assert board["summary"]["llm_tokens"] >= 0
    assert board["duration_buckets"]["<1s"] >= 0
    assert any(q[0] == "上个月哪个店铺GMV最高？" for q in board["top_questions"])


def test_quota_blocks_after_limit(client, admin_token, biz_ready):
    """每日配额（FR-SEC-33）：超限查询被 429 拦截；重置后恢复。"""
    headers = _auth(admin_token)
    # 配额置为 1 次（sys_config 热更新）
    r = client.patch("/api/v1/admin/configs/quota.user_daily_queries",
                     headers=headers, json={"value": 1})
    assert r.status_code == 200, r.text

    first = _run_query(client, admin_token, biz_ready)
    assert first.status_code == 200, first.text
    second = _run_query(client, admin_token, biz_ready)
    assert second.status_code == 429
    assert second.json()["code"] == 42902

    # 配额回 0（不限），可继续查询
    client.patch("/api/v1/admin/configs/quota.user_daily_queries",
                 headers=headers, json={"value": 0})
    third = _run_query(client, admin_token, biz_ready)
    assert third.status_code == 200


def test_cleanup_dry_run_and_execute(client, admin_token):
    """保留期清理（FR-SEC-43）：dry_run 只统计，实删后记录审计。"""
    headers = _auth(admin_token)
    # 保留期设为 0 天 → 全部历史均超期
    client.patch("/api/v1/admin/configs/history.retention_days",
                 headers=headers, json={"value": 0})

    dry = client.post("/api/v1/admin/ops/cleanup", headers=headers,
                      json={"dry_run": True}).json()["data"]
    assert dry["dry_run"] is True
    assert dry["history_to_delete"] >= 1

    real = client.post("/api/v1/admin/ops/cleanup", headers=headers,
                       json={"dry_run": False}).json()["data"]
    assert real["history_to_delete"] >= 1

    # 清理动作留审计
    logs = client.get("/api/v1/admin/audit-logs", headers=headers,
                      params={"action": "admin.maintenance.cleanup"}).json()["data"]
    assert logs["total"] >= 1
    # 恢复保留期，避免影响后续用例
    client.patch("/api/v1/admin/configs/history.retention_days",
                 headers=headers, json={"value": 90})


def test_scan_flags_removed_columns(client, admin_token, biz_ready):
    """增量同步影响提示（FR-SCH-04）：字段删除被标记 missing，受影响指标被点名。

    biz_ready 返回本用例组接入的 demo_business 数据源 id（避免依赖固定 id=1）。
    """
    import psycopg

    headers = _auth(admin_token)
    ds_id = biz_ready
    # 1. 在示例库建临时表并扫描入库
    with psycopg.connect("host=localhost port=5433 dbname=demo_business user=t2s password=t2s",
                         autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS t2s_tmp_impact")
        conn.execute("CREATE TABLE t2s_tmp_impact (id int primary key, note text, drop_col text)")
    try:
        r = client.post(f"/api/v1/admin/schema/datasources/{ds_id}/scan", headers=headers)
        assert r.status_code == 200, r.text
        # 2. 建指标引用 drop_col，用于验证受影响提示
        tables = client.get("/api/v1/admin/schema/tables", headers=headers,
                            params={"datasource_id": ds_id}).json()["data"]
        tmp = next(t for t in tables if t["table_name"] == "t2s_tmp_impact")
        m = client.post("/api/v1/admin/metrics", headers=headers, json={
            "datasource_id": ds_id, "name": "临时指标", "code": "tmp_metric",
            "description": "t", "formula": {"expr": "COUNT(t2s_tmp_impact.drop_col)"},
            "agg_type": "count", "status": 1,
        })
        assert m.status_code == 201, m.text
        # 3. 源库删除字段后再扫描 → missing 标记 + 受影响指标
        with psycopg.connect("host=localhost port=5433 dbname=demo_business user=t2s password=t2s",
                             autocommit=True) as conn:
            conn.execute("ALTER TABLE t2s_tmp_impact DROP COLUMN drop_col")
        r2 = client.post(f"/api/v1/admin/schema/datasources/{ds_id}/scan", headers=headers)
        data = r2.json()["data"]
        assert any(c["column"] == "drop_col" for c in data["removed_columns"])
        assert "tmp_metric" in data["affected_metrics"]
        # 4. 表元数据仍可查（missing 标记保留业务标注，供管理员确认后清理）
        cols = client.get("/api/v1/admin/schema/tables", headers=headers,
                          params={"datasource_id": ds_id}).json()["data"]
        assert next(t for t in cols if t["id"] == tmp["id"])
        # 停用临时指标（无删除端点，置为停用状态）
        client.patch(f"/api/v1/admin/metrics/{m.json()['data']['id']}",
                     headers=headers, json={"status": 0})
    finally:
        with psycopg.connect("host=localhost port=5433 dbname=demo_business user=t2s password=t2s",
                             autocommit=True) as conn:
            conn.execute("DROP TABLE IF EXISTS t2s_tmp_impact")
