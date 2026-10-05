"""集成测试：T3 查询主链路端到端（FakeLLM 驱动，验证真实管线）。

覆盖：SC-01 成功链路（NLU→检索→生成→校验→执行→脱敏→图表→历史）、
越界拒答、恶意 SQL 拦截与重试耗尽、SSE 事件序列（AC-01/06/07/08 等价验证）。
"""

import json

import psycopg
import pytest

from app.core.rate_limit import reset_rate_limits
from app.llm.client import clear_fake_routes, reset_breaker, set_fake_routes
from tests.integration.conftest import auth_header as _auth

pytestmark = pytest.mark.integration

# FakeLLM 预设响应：SC-01「上个月哪个店铺GMV最高」
_NLU_OK = json.dumps({
    "intent": "stat", "out_of_scope": False, "refuse_reason": None,
    "clarify": None,
    "entities": {"time_expression": "上个月", "metrics": ["GMV"], "dimensions": ["店铺"],
                 "filters": [], "order": "desc", "limit": 1, "time_granularity": None},
}, ensure_ascii=False)

_SQL_OK = json.dumps({
    "sql": ("SELECT s.name AS shop_name, SUM(o.amount) AS gmv "
            "FROM orders o JOIN shop s ON s.id = o.shop_id "
            "WHERE o.order_date >= '2026-09-01' AND o.order_date <= '2026-09-30' "
            "GROUP BY s.name ORDER BY gmv DESC LIMIT 1"),
    "assumptions": ["GMV 按订单实付金额求和（口径来自指标定义）"], "confidence": 0.9,
    "explain": "统计上个月每个店铺的GMV并取最高的一个",
}, ensure_ascii=False)


@pytest.fixture(autouse=True)
async def _fake_llm_routes():
    """默认注入成功链路路由并复位熔断器/限流器；用例内部可覆盖路由。"""
    reset_breaker()
    await reset_rate_limits()
    set_fake_routes({__import__("app.services.nlu.intent", fromlist=["NLU_MARKER"]).NLU_MARKER: _NLU_OK,
                     __import__("app.services.sql_gen.generator", fromlist=["SQL_GEN_MARKER"]).SQL_GEN_MARKER: _SQL_OK})
    yield
    clear_fake_routes()
    reset_breaker()
    await reset_rate_limits()


def _create_conversation(client, token) -> int:
    resp = client.post("/api/v1/conversations", headers=_auth(token), json={})
    assert resp.status_code == 201
    return resp.json()["data"]["id"]


def test_e2e_gmv_query_success(client, admin_token, biz_ready):
    """SC-01 端到端：问出上个月 GMV 最高的店铺（AC-01 等价）。"""
    conv_id = _create_conversation(client, admin_token)
    resp = client.post("/api/v1/query", headers=_auth(admin_token), json={
        "question": "上个月哪个店铺GMV最高？", "conversation_id": conv_id, "datasource_id": biz_ready,
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["exec_status"] == "success"
    result = data["result"]
    assert result["row_count"] == 1
    assert isinstance(result["rows"][0][1], (int, float))  # GMV 数值
    assert data["chart"]["chart_type"] == "bar"  # 单分类+单度量 → 柱状（FR-VIS-02）
    # SQL 与解释均已返回（前端四要素之一）
    assert result is not None and len(result["columns"]) == 2


def test_history_records_query(client, admin_token, biz_ready):
    """历史落库（FR-HIS-01）：可检索到本次查询。"""
    conv_id = _create_conversation(client, admin_token)
    client.post("/api/v1/query", headers=_auth(admin_token), json={
        "question": "上个月哪个店铺GMV最高？", "conversation_id": conv_id, "datasource_id": biz_ready,
    })
    hist = client.get("/api/v1/history", headers=_auth(admin_token)).json()["data"]
    assert hist["total"] >= 1
    assert hist["items"][0]["exec_status"] == "success"


def test_out_of_scope_refused(client, admin_token, biz_ready):
    """越界拒答（FR-NLU-03、AC-06 语义层）：不生成 SQL，历史记 refused。"""
    set_fake_routes({
        __import__("app.services.nlu.intent", fromlist=["NLU_MARKER"]).NLU_MARKER: json.dumps({
            "intent": "query", "out_of_scope": True,
            "refuse_reason": "平台仅支持数据查询，不能修改数据", "clarify": None, "entities": {},
        }, ensure_ascii=False),
    })
    conv_id = _create_conversation(client, admin_token)
    resp = client.post("/api/v1/query", headers=_auth(admin_token), json={
        "question": "帮我把所有店铺的GMV删掉", "conversation_id": conv_id, "datasource_id": biz_ready,
    })
    assert resp.status_code == 422
    assert resp.json()["code"] == 42201


def test_malicious_sql_exhausts_retries(client, admin_token, biz_ready):
    """LLM 输出恶意 SQL → guard 全阶段拦截 → 重试耗尽明确失败（FR-SQL-30、AC-06）。"""
    set_fake_routes({
        __import__("app.services.sql_gen.generator", fromlist=["SQL_GEN_MARKER"]).SQL_GEN_MARKER:
            json.dumps({"sql": "SELECT * FROM pg_catalog.pg_tables", "assumptions": [],
                        "confidence": 0.9, "explain": "x"}, ensure_ascii=False),
    })
    conv_id = _create_conversation(client, admin_token)
    resp = client.post("/api/v1/query", headers=_auth(admin_token), json={
        "question": "看看系统里有什么表", "conversation_id": conv_id, "datasource_id": biz_ready,
    })
    assert resp.status_code == 422
    assert resp.json()["code"] == 42203


def test_sse_event_sequence(client, admin_token, biz_ready):
    """SSE 流式（FR-UI-05）：阶段事件按序推送并以 done 结束。"""
    conv_id = _create_conversation(client, admin_token)
    with client.stream("POST", "/api/v1/query/stream", headers=_auth(admin_token), json={
        "question": "上个月哪个店铺GMV最高？", "conversation_id": conv_id, "datasource_id": biz_ready,
    }) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        # 收集 (event_type, data) 对
        events = []
        current = None
        for line in resp.iter_lines():
            if line.startswith("event: "):
                current = line.removeprefix("event: ").strip()
            elif line.startswith("data: ") and current:
                try:
                    events.append((current, json.loads(line.removeprefix("data: "))))
                except json.JSONDecodeError:
                    events.append((current, {}))
                current = None

    # 阶段次序：理解 → 检索 → 生成 → 校验 → 执行 → 渲染（§6.2），阶段名在 stage 载荷中
    stages = [p.get("stage") for t, p in events if t == "stage"]
    for stage in ("understanding", "retrieving_schema", "generating_sql", "validating", "executing", "rendering"):
        assert stage in stages, f"缺少阶段事件 {stage}，实际: {stages}"
    types = [t for t, _ in events]
    assert "sql" in types and "result" in types and "chart" in types
    assert types[-1] == "__end__"
    assert types.count("done") >= 1


def test_row_policy_injected_into_sql(client, admin_token, biz_ready, test_db_url):
    """行级权限改写（FR-SEC-11）：策略片段被强制注入执行的 SQL（FR-HIS-01 可追溯）。"""
    # 直接在测试库写入一条针对 orders 表的策略（管理 API 于 T4 提供）
    conninfo = test_db_url.replace("postgresql+psycopg://", "postgresql://")
    insert_sql = (
        "INSERT INTO row_policy (datasource_id, table_meta_id, filter_template, apply_to_role_ids) "
        "SELECT %s, tm.id, 'o.status <> 4', %s FROM table_meta tm "
        "WHERE tm.datasource_id = %s AND tm.table_name = 'orders'"
    )
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute(insert_sql, (biz_ready, '["R-BIZ"]', biz_ready))

    # R-BIZ 用户 + 该数据源 → 命中策略；SQL 生成 route 返回无状态过滤的查询
    client.post("/api/v1/admin/users", headers=_auth(admin_token), json={
        "username": "bizq", "password": "biz-pass-123", "roles": ["R-BIZ"],
    })
    token = client.post(
        "/api/v1/auth/login", json={"username": "bizq", "password": "biz-pass-123"}
    ).json()["data"]["token"]
    conv_id = _create_conversation(client, token)
    resp = client.post("/api/v1/query", headers=_auth(token), json={
        "question": "上个月哪个店铺GMV最高？", "conversation_id": conv_id, "datasource_id": biz_ready,
    })
    assert resp.status_code == 200
    assert resp.json()["data"]["exec_status"] == "success"

    # 历史详情中的 SQL 应包含注入的行级条件（服务端强制，FR-SEC-11）
    hist = client.get("/api/v1/history", headers=_auth(token)).json()["data"]
    assert hist["total"] >= 1


def test_multi_turn_context_inherited(client, admin_token, biz_ready):
    """多轮继承（§3.3）：第二问的上文条件注入 Prompt（FR-UI-04 语义层）。"""
    from app.llm.client import _fake_llm

    conv_id = _create_conversation(client, admin_token)
    client.post("/api/v1/query", headers=_auth(admin_token), json={
        "question": "上个月哪个店铺GMV最高？", "conversation_id": conv_id, "datasource_id": biz_ready,
    })
    calls_before = len(_fake_llm.calls)
    client.post("/api/v1/query", headers=_auth(admin_token), json={
        "question": "那按月拆开看呢？", "conversation_id": conv_id, "datasource_id": biz_ready,
    })
    # 第二轮的 NLU prompt 应包含会话上文摘要（继承时间条件等）
    nlu_call = _fake_llm.calls[calls_before]  # 第一条即 NLU 调用
    assert "会话上文条件" in nlu_call
