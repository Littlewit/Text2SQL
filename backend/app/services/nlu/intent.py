"""意图识别与实体抽取（FR-NLU-01~03、FR-NLU-10~17）。

单次 LLM 调用输出结构化 JSON（意图 + 实体 + 越界/澄清标记）；
时间实体由 time_parser 确定性解析；指标名经同义词/指标表归一化（FR-NLU-11）。
"""

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.infra.models import Metric, Synonym
from app.llm.client import LLMClient
from app.services.nlu.time_parser import parse_time_expression

# NLU prompt 标记：FakeLLM 按此路由；也便于日志诊断（FR-NLU-04）
NLU_MARKER = "[NLU_TASK]"

_INTENT_SYSTEM = (
    "你是数据分析平台的意图理解模块。只输出 JSON，不输出其他内容。\n"
    "JSON 结构：\n"
    '{"intent":"query|stat|compare|trend","out_of_scope":false,"refuse_reason":null,'
    '"clarify":{"question":null,"options":[]},'
    '"entities":{"time_expression":null,"metrics":[],"dimensions":[],'
    '"filters":[],"order":null,"limit":null,"time_granularity":null}}\n'
    "规则：\n"
    "1. 要求写库/改数/删数/导出全库/他人隐私/与数据查询无关的闲聊 → out_of_scope=true 并给 refuse_reason；\n"
    "2. 缺少指标或时间或维度值不明，无法生成有意义的查询 → 填 clarify（给出反问与候选项）；\n"
    "3. 时间表述输出原文（如「上个月」），不要换算；\n"
    "4. metrics/dimensions 使用问题中的业务词汇；filters 提取筛选条件原文。\n"
)


@dataclass
class NluResult:
    """NLU 输出：意图 + 归一化后的实体。"""

    intent: str = "stat"
    out_of_scope: bool = False
    refuse_reason: str | None = None
    clarify_question: str | None = None
    clarify_options: list[str] = field(default_factory=list)
    time_expression: str | None = None
    time_range: tuple | None = None  # (start_date, end_date) 确定性解析结果
    metrics: list[str] = field(default_factory=list)  # 归一化后的指标 code
    dimensions: list[str] = field(default_factory=list)
    filters: list[dict] = field(default_factory=list)
    order: str | None = None
    limit: int | None = None
    time_granularity: str | None = None
    raw: dict | None = None  # 原始 JSON（落库诊断，FR-NLU-04）


async def understand(
    db: AsyncSession,
    llm: LLMClient,
    question: str,
    context_summary: str | None = None,
) -> NluResult:
    """执行意图识别与实体抽取；越界/澄清在此短路（不进入 SQL 生成）。"""
    user_content = f"{NLU_MARKER}\n"
    if context_summary:
        user_content += f"（会话上文条件：{context_summary}）\n"
    user_content += f"用户问题：{question}"

    resp = await llm.chat(
        [
            {"role": "system", "content": _INTENT_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        json_mode=True,
    )
    data = _parse_json(resp.content)

    result = NluResult(
        intent=data.get("intent", "stat"),
        out_of_scope=bool(data.get("out_of_scope")),
        refuse_reason=data.get("refuse_reason"),
        raw=data,
    )
    if result.out_of_scope:
        return result  # 拒答：不解析实体

    cl = data.get("clarify") or {}
    if cl.get("question"):
        result.clarify_question = cl["question"]
        result.clarify_options = cl.get("options") or []
        return result  # 需要澄清：不强行生成 SQL（FR-NLU-02）

    ent = data.get("entities") or {}
    result.time_expression = ent.get("time_expression")
    if result.time_expression:
        result.time_range = parse_time_expression(result.time_expression)
    result.metrics = await _normalize_metrics(db, ent.get("metrics") or [])
    result.dimensions = ent.get("dimensions") or []
    result.filters = ent.get("filters") or []
    result.order = ent.get("order")
    result.limit = ent.get("limit")
    result.time_granularity = ent.get("time_granularity")
    return result


async def _normalize_metrics(db: AsyncSession, names: list[str]) -> list[str]:
    """指标归一化（FR-NLU-11）：精确匹配指标名/编码 → 同义词表 → 保留原词（后续澄清）。"""
    codes: list[str] = []
    for name in names:
        m = (
            await db.execute(
                db_bind(Metric).where((Metric.name == name) | (Metric.code == name.lower()))
            )
        ).scalar_one_or_none()
        if m:
            codes.append(m.code)
            continue
        s = (
            await db.execute(db_bind(Synonym).where(Synonym.term == name))
        ).scalar_one_or_none()
        if s and s.target_type == "metric":
            target = await db.get(Metric, s.target_id)
            if target:
                codes.append(target.code)
                continue
        codes.append(name)  # 未归一化，交由澄清/生成阶段处理
    return codes


def db_bind(model):
    """select(model) 的简写（避免循环导入的延迟绑定）。"""
    from sqlalchemy import select

    return select(model)


def _parse_json(raw: str) -> dict:
    """健壮 JSON 解析：容忍 markdown 包裹与前后杂文（FR-SQL-04 同源逻辑）。"""
    import json
    import re

    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            return json.loads(match.group())
        raise AppError(42201, "无法理解该问题，请换个说法", 422) from None
