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
LLM_KINDS = {"sql_exec", "refused", "clarify", "intent", "recall"}

# demo_business 全部物理表（召回评测从 standard_sql 提取目标表的词表）
_PHYSICAL_TABLES = ("orders", "shop", "product", "order_item", "return_order")


def _derive_recall_cases(cases: list[dict]) -> list[dict]:
    """从 EX 用例派生召回评测（NFR-A-04）：standard_sql 中引用的表须被检索 top-k 命中。"""
    import re

    derived = []
    for c in cases:
        if c["kind"] != "sql_exec":
            continue
        sql = c["expected"]["standard_sql"].lower()
        targets = [t for t in _PHYSICAL_TABLES if re.search(rf"\b{t}\b", sql)]
        derived.append({**c, "id": c["id"] + "R", "kind": "recall",
                        "tag": "recall_" + c["tag"].replace("ex_", ""),
                        "expected": {"target_tables": targets}})
    return derived


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


def run_eval(cases: list[dict], offline_only: bool = False, limit: int | None = None,
             kinds: set[str] | None = None) -> EvalReport:
    """执行评测。offline_only=True 仅跑离线类别（CI 门禁模式）；kinds 指定类别过滤。"""
    report = EvalReport()
    start = time.monotonic()

    # 密钥别名兼容：DEEPSEEK_API_KEY（优先）或 LLM_API_KEY 任一存在即可跑 LLM 类别
    llm_available = bool(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY"))
    # 召回用例从 EX 用例派生（目标表 = standard_sql 引用的物理表）
    cases = cases + _derive_recall_cases(cases)
    selected = [c for c in cases if not offline_only or c["kind"] in OFFLINE_KINDS]
    if kinds:
        selected = [c for c in selected if c["kind"] in kinds]
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
                elif kind == "recall":
                    _run_recall(case, report)
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
    """EX 评测（NFR-A-01）：生成 SQL 与标准 SQL 执行结果比对。

    判定采用「行数相等 + 值多重集包含」：标准行的值都出现在某个生成行中即可。
    容忍模型多 SELECT 标识列（如 id），但不容忍聚合值/行数差异。
    """
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
            return [frozenset(map(repr, r)) for r in cur.fetchall()]

        actual, expected = rows(generated_sql), rows(case["expected"]["standard_sql"])

    if len(actual) != len(expected):
        _record(report, case, False,
                f"行数不一致：生成 {len(actual)} 行 vs 标准 {len(expected)} 行")
        return
    # 每个标准行的值集合须被某个生成行覆盖（贪心匹配即可，集合无重复值）
    remaining = list(actual)
    for want in expected:
        for i, got in enumerate(remaining):
            if want <= got:
                remaining.pop(i)
                break
        else:
            _record(report, case, False,
                    f"结果值不一致：标准行 {sorted(want)[:4]} 未被生成结果覆盖")
            return
    _record(report, case, True)


def _run_recall(case: dict, report: EvalReport) -> None:
    """召回评测（NFR-A-04）：检索 top-k 必须命中 standard_sql 引用的全部物理表。"""
    from eval.ex_utils import eval_recall

    hit, detail = eval_recall(case["question"], case["expected"]["target_tables"])
    _record(report, case, hit, detail)


def _run_nlu_case(case: dict, report: EvalReport) -> None:
    """refused / clarify / intent 评测：仅 NLU 阶段（无需执行 SQL）。"""
    from eval.ex_utils import eval_nlu_only

    result = eval_nlu_only(case["question"])  # 同步封装（内部已处理事件循环）
    kind = case["kind"]
    if kind == "refused":
        _record(report, case, result.out_of_scope, f"期望拒答，实际 intent={result.intent}")
    elif kind == "clarify":
        _record(report, case, result.clarify_question is not None, "期望澄清，实际未澄清")
    elif kind == "intent":
        want = case["expected"]["intent"]
        _record(report, case, result.intent == want, f"期望 {want}，实际 {result.intent}")
