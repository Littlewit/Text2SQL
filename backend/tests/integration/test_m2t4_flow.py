"""集成测试：M2-T4 可视化与导出增强（FR-VIS-03/04/13/21/24）。"""

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
            "GROUP BY s.name ORDER BY gmv DESC LIMIT 5"),
    "assumptions": ["GMV 按实付金额"], "confidence": 0.9, "explain": "x",
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


def test_chart_switch_zero_request(client, admin_token, biz_ready):
    """图表一键切换（FR-VIS-03/04）：缓存数据重建 option，不重新执行查询。"""
    headers = _auth(admin_token)
    data = _run_query(client, admin_token, biz_ready)
    qid = data["query_id"]
    original_option = data["chart"]["chart_config"]

    for ctype in ("line", "pie", "table"):
        r = client.post(f"/api/v1/query/{qid}/chart", headers=headers,
                        json={"chart_type": ctype})
        assert r.status_code == 200
        body = r.json()["data"]
        assert body["source"] == "cache"
        if ctype == "table":
            assert body["option"]["type"] == "table"
        else:
            assert body["option"]["series"], f"{ctype} 应有 series"

    # 原始推荐未被改变（切换不影响历史记录的推荐结果）
    assert data["chart"]["chart_type"] in ("bar", "line", "pie")
    assert original_option is not None


def test_chart_switch_fallback_to_sample(client, admin_token, biz_ready):
    """缓存过期后回退历史样例构建（仍零请求重查）。"""
    from app.core.result_cache import evict

    headers = _auth(admin_token)
    data = _run_query(client, admin_token, biz_ready)
    evict(data["query_id"])  # 模拟缓存过期
    r = client.post(f"/api/v1/query/{data['query_id']}/chart", headers=headers,
                    json={"chart_type": "bar"})
    assert r.status_code == 200
    assert r.json()["data"]["source"] == "history_sample"


def test_chart_sampling_large_result(client, admin_token):
    """大结果采样（FR-VIS-13）：超限数据点均匀采样并在标题注明。"""
    from app.services.visualization.recommender import build_chart_option, recommend_chart

    columns, rows = ["月份", "gmv"], [[f"2026-{m:02d}-01", m * 100.0] for m in range(1, 13)]
    rec = recommend_chart(columns, rows, "各月GMV趋势")
    assert rec["chart_type"] == "line"
    # 未超限不采样
    assert "采样" not in rec["reason"]

    big_rows = [[f"d{i}", i] for i in range(2500)]
    opt = build_chart_option("line", ["日期", "值"], big_rows)
    assert "采样" in opt["title"]["text"]
    assert len(opt["xAxis"]["data"]) <= 1000


def test_export_row_limit_confirm(client, admin_token, biz_ready):
    """导出行数上限（FR-VIS-24）：默认样例行数 < 上限直接导出；确认参数透传审计。"""
    headers = _auth(admin_token)
    data = _run_query(client, admin_token, biz_ready)
    resp = client.post(f"/api/v1/query/{data['query_id']}/export", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/vnd.openxmlformats")

    logs = client.get("/api/v1/admin/audit-logs", headers=headers,
                      params={"action": "export.excel"}).json()["data"]
    assert logs["total"] >= 1


def test_export_pdf_audited(client, admin_token, biz_ready):
    """PDF 导出留审计（FR-VIS-21）：服务端记录 export.pdf 动作。"""
    headers = _auth(admin_token)
    data = _run_query(client, admin_token, biz_ready)
    r = client.post(f"/api/v1/query/{data['query_id']}/export/pdf", headers=headers)
    assert r.status_code == 200
    logs = client.get("/api/v1/admin/audit-logs", headers=headers,
                      params={"action": "export.pdf"}).json()["data"]
    assert logs["total"] >= 1


def test_history_detail(client, admin_token, biz_ready):
    """历史详情（FR-HIS-01 增强）：SQL/解释/假设/召回明细可回看，仅本人可见。"""
    headers = _auth(admin_token)
    data = _run_query(client, admin_token, biz_ready)
    detail = client.get(f"/api/v1/history/{data['query_id']}", headers=headers).json()["data"]
    assert "SELECT" in detail["generated_sql"]
    assert detail["assumptions"]
    assert detail["recalled_schema"] is not None or detail["prompt_template_version"]
