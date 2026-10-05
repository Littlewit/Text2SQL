"""评测执行器（EV-02/04/05）：按用例类别执行并产出分维度报告。

- 离线类别（time_parse / guard_reject / guard_pass）不依赖 LLM，作为 CI 强制门禁；
- LLM 类别（sql_exec / refused / clarify / intent）需配置 LLM_API_KEY，未配置时记 skip；
- EX 比对：生成 SQL 与标准 SQL 在 demo 库执行，结果集（排序后）一致记通过；
- 报告 JSON 含分维度（tag）统计，供回归对比（EV-05）。
"""

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

OFFLINE_KINDS = {"time_parse", "guard_reject", "guard_pass"}
LLM_KINDS = {"sql_exec", "refused", "clarify", "intent"}


@dataclass
class EvalReport:
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    duration_ms: int = 0
    by_tag: dict = field(default_factory=dict)
    failures: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total": self.total, "passed": self.passed, "failed": self.failed,
            "skipped": self.skipped, "duration_ms": self.duration_ms,
            "pass_rate": round(self.passed / max(self.passed + self.failed, 1), 4),
            "by_tag": self.by_tag, "failures": self.failures[:50],
        }


def load_cases(path: str | None = None) -> list[dict]:
    p = path or str(Path(__file__).parent / "cases_v1.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _record(report: EvalReport, case: dict, ok: bool, detail: str = "") -> None:
    report.total += 1
    if ok:
        report.passed += 1
    else:
        report.failed += 1
        report.failures.append({"id": case["id"], "kind": case["kind"],
                                "question": case["question"][:100], "detail": detail[:200]})
    tag = case["tag"]
    stat = report.by_tag.setdefault(tag, {"total": 0, "passed": 0})
    stat["total"] += 1
    if ok:
        stat["passed"] += 1


def run_eval(cases: list[dict], offline_only: bool = False, limit: int | None = None) -> EvalReport:
    """执行评测。offline_only=True 仅跑离线类别（CI 门禁模式）。"""
    report = EvalReport()
    start = time.monotonic()

    llm_available = bool(os.environ.get("LLM_API_KEY"))
    selected = [c for c in cases if not offline_only or c["kind"] in OFFLINE_KINDS]
    if limit:
        selected = selected[:limit]

    # 导入放函数内：离线模式无需加载应用
    for case in selected:
        kind = case["kind"]
        try:
            if kind == "time_parse":
                _run_time_parse(case, report)
            elif kind in ("guard_reject", "guard_pass"):
                _run_guard(case, report)
            elif kind in LLM_KINDS:
                if not llm_available:
                    report.total += 1
                    report.skipped += 1
                elif kind == "sql_exec":
                    _run_sql_exec(case, report)
                else:
                    _run_nlu_case(case, report)
        except Exception as e:  # noqa: BLE001 —— 单用例异常记失败，不中断评测
            _record(report, case, False, f"exception: {e}")

    report.duration_ms = int((time.monotonic() - start) * 1000)
    return report


def _run_time_parse(case: dict, report: EvalReport) -> None:
    from datetime import date

    from app.services.nlu.time_parser import parse_time_expression

    exp = case["expected"]
    got = parse_time_expression(exp["expression"], date.fromisoformat(exp["today"]))
    if exp["start"] is None:
        _record(report, case, got is None, f"期望无法解析，实际 {got}")
        return
    want = (date.fromisoformat(exp["start"]), date.fromisoformat(exp["end"]))
    _record(report, case, got == want, f"期望 {want}，实际 {got}")


def _run_guard(case: dict, report: EvalReport) -> None:
    from app.services.sql_guard import GuardContext, validate

    ctx = GuardContext(
        allowed_tables={
            "orders": {"id", "shop_id", "order_no", "order_date", "status", "amount"},
            "shop": {"id", "name", "region", "city", "open_date"},
            "product": {"id", "name", "category", "price"},
            "order_item": {"id", "order_id", "product_id", "quantity", "unit_price", "amount"},
            "return_order": {"id", "order_item_id", "return_date", "return_amount", "reason"},
        },
        row_limit=1000,
    )
    sql = case["expected"].get("sql") or case["question"]
    result, _ = validate(sql, ctx)
    should_pass = case["kind"] == "guard_pass"
    _record(report, case, result.ok == should_pass,
            f"期望{'通过' if should_pass else '拦截'}，实际 {'通过' if result.ok else '拦截'}")


def _run_sql_exec(case: dict, report: EvalReport) -> None:
    """EX 评测（NFR-A-01）：生成 SQL 与标准 SQL 执行结果集比对（排序归一）。"""
    import psycopg

    from eval.ex_utils import eval_connection_info, run_text2sql

    conninfo = eval_connection_info()
    question = case["question"]

    generated_sql = run_text2sql(question, case["datasource"])
    if generated_sql is None:
        _record(report, case, False, "未能生成 SQL")
        return

    with psycopg.connect(conninfo, connect_timeout=5) as conn:
        def rows(sql: str):
            cur = conn.execute(sql)
            return sorted(map(repr, cur.fetchall()))

        actual = rows(generated_sql)
        expected = rows(case["expected"]["standard_sql"])

    _record(report, case, actual == expected,
            f"结果集不一致：生成 {len(actual)} 行 vs 标准 {len(expected)} 行")


def _run_nlu_case(case: dict, report: EvalReport) -> None:
    """refused / clarify / intent 评测：仅 NLU 阶段（无需执行 SQL）。"""
    import asyncio

    from eval.ex_utils import eval_nlu_only

    result = asyncio.run(eval_nlu_only(case["question"]))
    kind = case["kind"]
    if kind == "refused":
        _record(report, case, result.out_of_scope, f"期望拒答，实际 intent={result.intent}")
    elif kind == "clarify":
        _record(report, case, result.clarify_question is not None, "期望澄清，实际未澄清")
    elif kind == "intent":
        want = case["expected"]["intent"]
        _record(report, case, result.intent == want, f"期望 {want}，实际 {result.intent}")
