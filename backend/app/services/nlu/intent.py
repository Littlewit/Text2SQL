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

# 聚合方式抽取规则（FR-NLU-15）：问题关键词 → 归一化聚合标识
_AGG_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("平均", "均值", "avg"), "avg"),
    (("总和", "合计", "总共", "sum"), "sum"),
    (("最大", "最高", "max"), "max"),
    (("最小", "最低", "min"), "min"),
    (("有多少", "数量", "几个", "计数", "count"), "count"),
    (("去重", "唯一", "distinct"), "distinct"),
    (("占比", "比例", "份额"), "ratio"),
)

# 时间粒度归一化映射（FR-NLU-16）：中文表述 → 标准粒度
_GRANULARITY_MAP = {
    "天": "day", "日": "day", "每天": "day", "按天": "day", "按日": "day", "daily": "day",
    "周": "week", "每周": "week", "按周": "week", "weekly": "week",
    "月": "month", "每月": "month", "按月": "month", "月度": "month", "monthly": "month",
    "季度": "quarter", "每季度": "quarter", "按季度": "quarter", "quarterly": "quarter",
    "年": "year", "每年": "year", "按年": "year", "yearly": "year",
}

_INTENT_SYSTEM = (
    "你是数据分析平台的意图理解模块。只输出 JSON，不输出其他内容。\n"
    "JSON 结构：\n"
    '{"intent":"query|stat|compare|trend","out_of_scope":false,"refuse_reason":null,'
    '"confidence":0.9,'
    '"clarify":{"question":null,"options":[]},'
    '"entities":{"time_expression":null,"metrics":[],"dimensions":[],'
    '"filters":[],"order":null,"limit":null,"time_granularity":null}}\n'
    "规则：\n"
    "1. 要求写库/改数/删数/导出全库/他人隐私/与数据查询无关的闲聊 → out_of_scope=true 并给 refuse_reason；\n"
    "2. 仅当确实无法生成有意义查询时才 clarify：指标完全缺失（如「销量如何」没说看什么）"
    "或维度值含糊（如「那个店铺」不知道哪个）；"
    "注意：问题未提时间范围不算缺失（默认查全部历史）；指标能通过常识或同义词对应时不要澄清；\n"
    "3. 时间表述输出原文（如「上个月」），不要换算；\n"
    "4. metrics/dimensions 使用问题中的业务词汇；filters 提取筛选条件原文；\n"
    "5. confidence 为对意图与实体理解的确信度（0~1），不确定时给低分。\n"
    "意图判例：\n"
    "- 「上个月哪个店铺GMV最高」→ intent=stat（单期聚合+TopN）；\n"
    "- 「近6个月每月订单量趋势」→ intent=trend（时间粒度=month）；\n"
    "- 「华南和华东的GMV对比」/「本月比上个月GMV增长多少」→ intent=compare；\n"
    "- 「查一下昨天的订单明细」→ intent=query（明细列表，无聚合）；\n"
    "- 「店铺详情页在哪看」/「你好」→ out_of_scope=true。\n"
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
    aggregations: list[str] = field(default_factory=list)  # 聚合方式（FR-NLU-15）
    confidence: float = 0.9  # LLM 自评理解确信度（FR-NLU-17 澄清阈值）
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
        confidence=_safe_confidence(data.get("confidence")),
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
    result.time_granularity = normalize_granularity(ent.get("time_granularity"))
    result.aggregations = extract_aggregations(question)
    return result


def extract_aggregations(question: str) -> list[str]:
    """聚合方式抽取（FR-NLU-15）：问题关键词确定性归一化，供 SQL 生成对齐口径。"""
    return [agg for keywords, agg in _AGG_RULES if any(k in question for k in keywords)]


def normalize_granularity(raw: str | None) -> str | None:
    """时间粒度归一化（FR-NLU-16）：中文/英文表述 → day/week/month/quarter/year。"""
    if not raw:
        return None
    low = raw.strip().lower()
    for word, std in _GRANULARITY_MAP.items():
        if word in low:
            return std
    return low if low in ("day", "week", "month", "quarter", "year") else None


def _safe_confidence(v) -> float:
    """置信度容错解析：非法值回落 0.9（LLM 输出不可信，零信任校验）。"""
    try:
        c = float(v)
    except (TypeError, ValueError):
        return 0.9
    return min(max(c, 0.0), 1.0)


async def _normalize_metrics(db: AsyncSession, names: list[str]) -> list[str]:
    """指标归一化（FR-NLU-11）：精确匹配指标名/编码 → 同义词表 → 保留原词（后续澄清）。"""
    codes: list[str] = []
    for name in names:
        m = (
            await db.execute(
                db_bind(Metric).where((Metric.name == name) | (Metric.code == name.lower()))
            )
        ).scalars().first()
        if m:
            codes.append(m.code)
            continue
        s = (
            await db.execute(db_bind(Synonym).where(Synonym.term == name))
        ).scalars().first()  # 防重复数据取首条（零信任：数据质量不假设完美）
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
