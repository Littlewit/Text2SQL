"""Prompt 组装器（FR-NLU-20/22/23）。

内容红线（CMP-02）：Prompt 只允许出现 Schema 元数据、指标口径、Few-shot 样例 SQL
与用户问题文本，禁止拼接任何业务库真实数据行。
"""

import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import ColumnMeta, EnumDict, FewShot, Metric, TableMeta
from app.llm.embedding import EmbeddingClient
from app.services.nlu.intent import NluResult

# 模板版本：模板内容变更时递增，历史查询可追溯当时版本（FR-NLU-23）
PROMPT_TEMPLATE_VERSION = "v1.0"


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


async def recall_few_shots(
    db: AsyncSession, embedder: EmbeddingClient, question: str, datasource_id: int | None, top_m: int = 3
) -> list[FewShot]:
    """Few-shot 动态召回（FR-NLU-21）：样例库按问题相似度取 Top-M，非固定写死。"""
    rows = (
        (
            await db.execute(
                select(FewShot).where(
                    FewShot.status == 1,
                    FewShot.model_version == embedder.model_version,
                    (FewShot.datasource_id == datasource_id) | (FewShot.datasource_id.is_(None)),
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return []
    qvec = (await embedder.embed([question]))[0]
    scored = sorted(
        ((fs, _cosine(qvec, list(fs.embedding))) for fs in rows), key=lambda x: -x[1]
    )
    return [fs for fs, _ in scored[:top_m]]


def render_schema_fragment(tables: list[TableMeta], columns: dict[int, list[ColumnMeta]],
                           enums: dict[int, list[EnumDict]]) -> str:
    """把检索命中的表/字段/枚举渲染为 Prompt 片段（含业务标注，FR-SCH-10）。"""
    blocks = []
    for tm in tables:
        lines = [f"表: {tm.schema_name}.{tm.table_name}（{tm.cn_name or ''}） {tm.description or ''}".rstrip()]
        for cm in columns.get(tm.id, []):
            line = f"  - {cm.column_name} {cm.data_type}"
            if cm.cn_name:
                line += f" ({cm.cn_name})"
            if cm.description:
                line += f" -- {cm.description}"
            if cm.unit:
                line += f" [单位:{cm.unit}]"
            lines.append(line)
            for e in enums.get(cm.id, []):
                lines.append(f"    · 取值 {e.raw_value} = {e.display_name}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_metrics(metrics: list[Metric]) -> str:
    """指标口径片段：LLM 必须引用定义而非自造口径（FR-SCH-12、R-01）。"""
    if not metrics:
        return ""
    lines = [
        f"指标 {m.name}（code={m.code}）：{m.description or ''} "
        f"公式={m.formula.get('expr') if m.formula else None} "
        f"聚合={m.agg_type or ''} 时间字段={m.default_time_column or ''} 单位={m.unit or ''}"
        for m in metrics
    ]
    return "可用指标定义（必须按此口径生成，不得自行编造）：\n" + "\n".join(lines)


def build_sql_prompt(
    question: str,
    schema_fragment: str,
    metrics_fragment: str,
    few_shots: list[FewShot],
    nlu: NluResult,
    context_summary: str | None = None,
    dialect: str = "postgres",
    row_limit: int = 1000,
) -> tuple[list[dict], str]:
    """组装 SQL 生成 Prompt，返回 (messages, template_version)。"""
    few_shot_text = "\n\n".join(
        f"问题：{fs.question}\nSQL：\n{fs.sql_text}" for fs in few_shots
    )
    time_hint = (
        f"（时间范围：{nlu.time_range[0]} 至 {nlu.time_range[1]}，含端点）"
        if nlu.time_range
        else "（问题未明确时间，如需时间条件请在 assumptions 中声明假设）"
    )
    context_text = f"\n会话上文条件：{context_summary}" if context_summary else ""

    system = f"""你是 Text2SQL 引擎。根据给定的表结构与指标口径，把用户问题转换为一条只读 {dialect} SQL。
规则：
1. 只能生成单条 SELECT（含 WITH 只读 CTE），禁止任何写操作与多语句；
2. 只能使用「可用表结构」中列出的表与字段，不得引用其他对象；
3. 指标必须按「指标定义」的公式与时间字段计算，不得自行编造口径；
4. 枚举筛选使用原始值而非中文展示名；金额/数值不加千分位；
5. 输出必须是 JSON：{{"sql": "...", "assumptions": ["..."], \
"confidence": 0.0, "explain": "一句话说明这条SQL做了什么"}}；
6. 查询结果会被强制限制在 {row_limit} 行内；聚合粒度由问题决定，未指明时间粒度时在 assumptions 中声明；
7. explain 面向非技术用户，说明查了什么、怎么算的。"""

    user = f"""[SQL_GEN_TASK]
【可用表结构】
{schema_fragment}

{metrics_fragment}

【动态示例】
{few_shot_text or "（无）"}

【用户问题】
{question} {time_hint}{context_text}"""

    return (
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        PROMPT_TEMPLATE_VERSION,
    )
