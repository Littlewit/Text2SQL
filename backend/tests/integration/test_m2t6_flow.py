"""集成测试：M2-T6 评测管理（FR-ADM-07）——触发、报告入库、历史与对比。"""

import pytest

from tests.integration.conftest import auth_header as _auth

pytestmark = pytest.mark.integration


def _wait_done(client, headers, run_id, timeout_s=60):
    """轮询评测报告直到完成（offline 模式秒级）。"""
    import time

    for _ in range(timeout_s):
        reports = client.get("/api/v1/admin/ops/eval/reports", headers=headers).json()["data"]
        run = next(r for r in reports if r["id"] == run_id)
        if run["status"] in ("done", "failed"):
            return run
        time.sleep(1)
    raise AssertionError("评测超时未完成")


def _biz_token(client, admin_token) -> str:
    """创建 BIZ 用户并登录（权限守卫用例）。"""
    h = _auth(admin_token)
    client.post("/api/v1/admin/users", headers=h, json={
        "username": "evalbiz", "password": "biz-pass-123",
        "roles": ["R-BIZ"], "scopes": [],
    })
    r = client.post("/api/v1/auth/login", json={"username": "evalbiz", "password": "biz-pass-123"})
    return r.json()["data"]["token"]


def test_eval_offline_run_and_report(client, admin_token):
    """触发离线评测：报告入库、分维度统计完整、确定性 100% 通过（EV-04 门禁基线）。"""
    headers = _auth(admin_token)
    resp = client.post("/api/v1/admin/ops/eval/run", headers=headers, json={"mode": "offline"})
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["data"]["run_id"]

    run = _wait_done(client, headers, run_id)
    assert run["status"] == "done"
    assert run["total"] >= 140
    assert run["pass_rate"] == 1.0  # 离线类别（安全/时间解析）红线 100%

    detail = client.get(f"/api/v1/admin/ops/eval/reports/{run_id}", headers=headers)
    d = detail.json()["data"]
    assert d["by_tag"], "分维度统计不能为空"
    assert all(v["passed"] == v["total"] for v in d["by_tag"].values())


def test_eval_reports_list_and_compare(client, admin_token):
    """评测历史列表 + 两份报告分维度对比（EV-05）。"""
    headers = _auth(admin_token)
    ids = []
    for _ in range(2):
        r = client.post("/api/v1/admin/ops/eval/run", headers=headers, json={"mode": "offline"})
        ids.append(r.json()["data"]["run_id"])
        _wait_done(client, headers, ids[-1])

    reports = client.get("/api/v1/admin/ops/eval/reports", headers=headers).json()["data"]
    assert len(reports) >= 2
    assert {r["id"] for r in reports} >= set(ids)

    cmp = client.get("/api/v1/admin/ops/eval/compare", headers=headers,
                     params={"a": ids[0], "b": ids[1]}).json()["data"]
    assert "overall_diff" in cmp and "by_tag" in cmp
    # 两份确定性评测应完全一致
    assert cmp["overall_diff"] == 0


def test_eval_full_requires_llm_key(client, admin_token, monkeypatch):
    """full 模式在无 LLM 密钥时应被拒绝（40001）。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    resp = client.post("/api/v1/admin/ops/eval/run", headers=_auth(admin_token),
                       json={"mode": "full"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 40001


def test_eval_permission_guard(client, admin_token):
    """BIZ 角色不可触发/查看评测管理（SS2.2 权限矩阵）。"""
    bt = _biz_token(client, admin_token)
    assert client.post("/api/v1/admin/ops/eval/run", headers=_auth(bt),
                       json={"mode": "offline"}).status_code == 403
    assert client.get("/api/v1/admin/ops/eval/reports",
                      headers=_auth(bt)).status_code == 403