"""查询主链路编排服务（§3.1、D-01）。

管线：NLU → Schema 检索 → Prompt 组装 → SQL 生成 → sql_guard 校验 → 权限改写
     → 只读执行 → 脱敏 → 图表推荐 → 历史/消息落库。
失败自愈（FR-SQL-30）：校验/执行错误回灌 LLM 重试 ≤ N 次，过程经 emit 对用户可见。
"""

import time
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_config_value
from app.core.errors import AppError
from app.infra.models import (
    ColumnMeta,
    Conversation,
    Datasource,
    EnumDict,
    Message,
    Metric,
    QueryHistory,
    TableMeta,
    User,
)
from app.core.obs import LLM_TOKENS, QUERIES, RETRIES
from app.llm.client import LLMClient
from app.llm.embedding import get_embedder
from app.services import audit_service, masking
from app.services.executor.runner import execute_readonly
from app.services.nlu.intent import NluResult, understand
from app.services.permission.rewriter import rewrite_row_permissions
from app.services.prompt.builder import (
    build_sql_prompt,
    recall_few_shots,
    render_metrics,
    render_schema_fragment,
)
from app.services.schema_retrieval.retriever import search, to_explainable
from app.services.sql_gen.generator import generate_sql
from app.services.sql_guard import GuardContext, validate
from app.services.visualization.recommender import recommend_chart

# SSE 阶段事件回调：async def emit(event_type: str, payload: dict)
EmitFn = Callable[[str, dict], Awaitable[None]]

# 历史中保存的结果样例行数（DR-02，P-36 待定）
RESULT_SAMPLE_ROWS = 10


async def run_query(
    db: AsyncSession,
    user: User,
    llm: LLMClient,
    question: str,
    conversation_id: int,
    datasource_id: int,
    emit: EmitFn,
) -> QueryHistory:
    """执行一次完整查询，返回落库后的 query_history 记录。

    参数 emit 为 SSE 事件回调（同步接口可传收集器），各阶段实时推送（FR-UI-05）。
    """
    started = time.monotonic()
    ds = await db.get(Datasource, datasource_id)
    if ds is None or ds.status != 1:
        raise AppError(40400, "数据源不存在或已停用", 404)

    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise AppError(40400, "会话不存在", 404)

    retry_max = await get_config_value(db, "sql_gen.max_retry", 2)
    row_limit = await get_config_value(db, "query.row_limit", 1000)
    timeout_s = await get_config_value(db, "query.timeout_s", 30)

    history = QueryHistory(
        conversation_id=conversation_id, user_id=user.id, question=question, exec_status="failed"
    )

    async def fail(code: int, message: str, status: str = "failed"):
        """统一失败出口：历史/消息/审计落库后抛业务错误。"""
        history.exec_status = status
        history.error_code = code
        history.duration_ms = int((time.monotonic() - started) * 1000)
        db.add(history)
        await _add_message(db, conversation_id, "assistant",
                           {"type": "error", "code": code, "message": message})
        await audit_service.record(
            db, user_id=user.id, action="query.fail",
            object_type="query_history", detail={"question": question[:200], "code": code},
        )
        await db.commit()
        await emit("error", {"code": code, "user_message": message, "retryable": status == "failed"})
        await emit("done", {"query_id": history.id})
        QUERIES.labels(status).inc()
        raise AppError(code, message, 422 if code >= 42200 else 500)

    # ---------- 阶段 1：NLU ----------
    await emit("stage", {"stage": "understanding", "message": "理解问题中"})
    context_summary = _context_summary(conversation.context)
    try:
        nlu = await understand(db, llm, question, context_summary)
    except AppError:
        raise
    except Exception as e:  # LLM 故障转可读错误（NFR-R-02）
        raise AppError(50002, "AI 服务暂时不可用，请稍后重试", 503) from e

    history.entities = {"intent": nlu.intent, "raw": nlu.raw}
    history.intent = nlu.intent

    if nlu.out_of_scope:  # 越界拒答（FR-NLU-03）：不生成任何 SQL
        return await _refuse(db, history, conversation_id, question,
                             nlu.refuse_reason or "该问题超出数据分析平台的范围", emit, started)
    if nlu.clarify_question:  # 澄清短路（FR-NLU-02）
        return await _clarify(db, history, conversation_id, question,
                              nlu.clarify_question, nlu.clarify_options, emit, started)

    # ---------- 阶段 2：Schema 检索 ----------
    await emit("stage", {"stage": "retrieving_schema", "message": "检索相关表结构"})
    recalled = await search(db, get_embedder_safe(), question, datasource_id, top_k=10)
    history.recalled_schema = {"results": to_explainable(recalled)}

    # ---------- 阶段 3~5：Prompt → 生成 → 校验（含自愈重试）----------
    await emit("stage", {"stage": "generating_sql", "message": "生成 SQL 中"})
    schema_fragment, metrics_fragment = await _render_context(db, recalled, nlu)
    few_shots = await recall_few_shots_safe(db, question, datasource_id)

    context_summary_full = context_summary
    last_error_hint: str | None = None
    guard_ctx = await _guard_context(db, datasource_id, row_limit)
    generated = None
    total_tokens = 0

    for attempt in range(retry_max + 1):
        messages, tpl_version = build_sql_prompt(
            question, schema_fragment, metrics_fragment, few_shots, nlu,
            context_summary=context_summary_full, row_limit=row_limit,
        )
        if last_error_hint:  # 错误回灌（FR-SQL-30：可见的自愈重试）
            messages.append({"role": "user", "content": f"上一次生成的 SQL 存在以下问题，请修正：\n{last_error_hint}"})
        history.prompt_template_version = tpl_version

        try:
            generated, tokens = await generate_sql(llm, messages)
            total_tokens += tokens
        except Exception as e:
            raise AppError(50002, "AI 服务暂时不可用，请稍后重试", 503) from e
        await emit("sql", {"sql": generated.sql, "explanation": generated.explain,
                           "assumptions": generated.assumptions, "retry_index": attempt})

        # AST 安全校验（FR-SQL-10~14）
        await emit("stage", {"stage": "validating", "message": "校验 SQL 安全性"})
        guard, guard_errors = validate(generated.sql, guard_ctx)
        history.validate_result = {"ok": guard.ok,
                                   "errors": [vars(e) for e in guard_errors]}
        if not guard.ok:
            last_error_hint = "\n".join(f"- [{e.stage}] {e.message}（建议：{e.hint}）" for e in guard_errors)
            RETRIES.inc()  # 自愈重试计数（NFR-O-01）
            continue
        sql_text = guard.rewritten_sql or generated.sql

        # 行级权限改写（FR-SEC-11）+ 复验
        try:
            sql_text = await rewrite_row_permissions(db, user, datasource_id, sql_text)
            re_guard, re_errors = validate(sql_text, guard_ctx)
            if not re_guard.ok:
                raise AppError(40300, "该查询触及数据权限边界，已拦截", 403)
            sql_text = re_guard.rewritten_sql or sql_text
        except AppError:
            raise

        # ---------- 阶段 6：只读执行（FR-SEC-30）----------
        await emit("stage", {"stage": "executing", "message": "执行查询中"})
        try:
            result = await execute_readonly(ds, sql_text, row_limit, timeout_s)
        except AppError as e:
            if e.code == 42205 and attempt < retry_max:
                last_error_hint = f"数据库执行错误：{e.message}"
                continue  # 执行期失败回灌重试（FR-SQL-30）
            raise
        break
    else:
        # 重试耗尽（§3.2）：明确失败并给出可操作出口
        return await _exhausted(db, history, conversation_id, question, generated, last_error_hint, emit, started)

    # ---------- 阶段 7：脱敏（FR-SEC-22，服务端出口统一执行）----------
    col_meta = await _column_meta_map(db, datasource_id, result.columns)
    col_infos = [masking.ColumnMaskInfo(name=c, is_sensitive=col_meta.get(c.lower(), False)) for c in result.columns]
    _, masked_rows = masking.mask_rows(col_infos, result.rows)
    # NUMERIC/日期等 DB 类型转 JSON 兼容值（结果样例与消息均入 JSONB，DR-02）
    import datetime as _dt
    import decimal

    def _jsonable(v):
        if isinstance(v, decimal.Decimal):
            return float(v)
        if isinstance(v, _dt.datetime | _dt.date):
            return v.isoformat()
        return v

    masked_rows = [[_jsonable(v) for v in row] for row in masked_rows]

    # ---------- 阶段 8：图表推荐（FR-VIS-01/02）----------
    await emit("stage", {"stage": "rendering", "message": "渲染图表"})
    chart = recommend_chart(result.columns, masked_rows, question)

    # ---------- 阶段 9：落库（FR-HIS-01/08）----------
    history.exec_status = "success"
    history.generated_sql = sql_text
    history.explain_text = generated.explain
    history.assumptions = {"list": generated.assumptions}
    history.row_count = result.row_count
    history.result_sample = {"columns": result.columns, "rows": masked_rows[:RESULT_SAMPLE_ROWS],
                             "truncated": result.truncated}
    history.duration_ms = int((time.monotonic() - started) * 1000)
    history.llm_tokens = total_tokens
    history.chart_config = chart
    history.retry_count = attempt
    db.add(history)
    await _add_message(db, conversation_id, "assistant", {
        "type": "result", "query_id": None, "question": question,
        "sql": sql_text, "explain": generated.explain, "assumptions": generated.assumptions,
        "columns": result.columns, "rows": masked_rows, "row_count": result.row_count,
        "truncated": result.truncated, "chart": chart, "duration_ms": history.duration_ms,
    })
    # 更新会话上下文（多轮继承，§3.3）
    conversation.context = {
        "last_question": question, "last_sql": sql_text,
        "time_expression": nlu.time_expression,
    }
    await audit_service.record(
        db, user_id=user.id, action="query.success",
        object_type="query_history", detail={"question": question[:200], "rows": result.row_count},
    )
    await db.commit()
    QUERIES.labels("success").inc()
    LLM_TOKENS.inc(total_tokens)
    await _add_message_ref(db, conversation_id, history.id)
    await emit("result", {"columns": result.columns, "rows": masked_rows, "row_count": result.row_count,
                          "truncated": result.truncated, "duration_ms": result.duration_ms})
    await emit("chart", {"chart_type": chart["chart_type"], "chart_config": chart["option"],
                         "reason": chart["reason"]})
    await emit("done", {"query_id": history.id})
    return history


# ---------- 内部辅助 ----------

def _context_summary(ctx: dict | None) -> str | None:
    """会话上下文摘要（FR-NLU-24：注入必要历史，避免无限膨胀）。"""
    if not ctx:
        return None
    parts = []
    if ctx.get("last_question"):
        parts.append(f"上一问：{ctx['last_question']}")
    if ctx.get("time_expression"):
        parts.append(f"继承时间条件：{ctx['time_expression']}")
    return "；".join(parts) or None


async def _render_context(db: AsyncSession, recalled, nlu: NluResult):
    """按检索结果渲染 Schema 片段与指标口径片段（只注入命中对象，FR-NLU-22）。"""

    table_ids = {r.object_id for r in recalled if r.object_type == "table"}
    col_ids = {r.object_id for r in recalled if r.object_type == "column"}
    tables = (
        (await db.execute(select(TableMeta).where(TableMeta.id.in_(table_ids or {0})))).scalars().all()
    )
    columns: dict[int, list[ColumnMeta]] = {}
    enums: dict[int, list[EnumDict]] = {}
    for tm in tables:
        cm_rows = (
            await db.execute(select(ColumnMeta).where(ColumnMeta.table_meta_id == tm.id))
        ).scalars().all()
        columns[tm.id] = list(cm_rows)
        for cm in cm_rows:
            # 检索命中的字段或命中表的全部字段均可带枚举
            if cm.id in col_ids or True:
                e_rows = (
                    await db.execute(select(EnumDict).where(EnumDict.column_meta_id == cm.id))
                ).scalars().all()
                if e_rows:
                    enums[cm.id] = list(e_rows)

    # 指标：NLU 归一化 code + 检索命中
    metric_codes = set(nlu.metrics)
    metric_ids = {r.object_id for r in recalled if r.object_type == "metric"}
    metrics = list(
        (
            await db.execute(
                select(Metric).where(
                    (Metric.code.in_(metric_codes or {"__none__"}))
                    | (Metric.id.in_(metric_ids or {0}))
                )
            )
        ).scalars()
    )
    schema_fragment = render_schema_fragment(tables, columns, enums)
    metrics_fragment = render_metrics(metrics)
    return schema_fragment, metrics_fragment


async def _guard_context(db: AsyncSession, datasource_id: int, row_limit: int) -> GuardContext:
    """构建白名单上下文：仅 included 表进入（FR-SCH-03）。"""
    tables = (
        (
            await db.execute(
                select(TableMeta).where(
                    TableMeta.datasource_id == datasource_id, TableMeta.included.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    allowed: dict[str, set[str]] = {}
    for tm in tables:
        cols = (
            await db.execute(select(ColumnMeta.column_name).where(ColumnMeta.table_meta_id == tm.id))
        ).scalars()
        allowed[tm.table_name.lower()] = {c.lower() for c in cols}
    return GuardContext(allowed_tables=allowed, row_limit=row_limit)


async def _column_meta_map(db: AsyncSession, datasource_id: int, columns: list[str]) -> dict[str, bool]:
    """结果列名 → 是否敏感（FR-SEC-20；未匹配的列按列名正则兜底）。"""
    rows = (
        await db.execute(
            select(ColumnMeta.column_name, ColumnMeta.is_sensitive)
            .join(TableMeta, TableMeta.id == ColumnMeta.table_meta_id)
            .where(TableMeta.datasource_id == datasource_id)
        )
    ).all()
    return {name.lower(): sens for name, sens in rows}


def get_embedder_safe():
    """获取 Embedding 客户端（未配置模型时为 HashEmbedder，见 app.llm.embedding）。"""
    return get_embedder()


async def recall_few_shots_safe(db: AsyncSession, question: str, datasource_id: int):
    """Few-shot 动态召回（FR-NLU-21）。"""
    return await recall_few_shots(db, get_embedder_safe(), question, datasource_id)


async def _add_message(db: AsyncSession, conversation_id: int, role: str, content: dict) -> None:
    seq = (
        await db.execute(
            select(Message.seq).where(Message.conversation_id == conversation_id).order_by(Message.seq.desc()).limit(1)
        )
    ).scalar_one_or_none() or 0
    db.add(Message(conversation_id=conversation_id, role=role, content=content, seq=seq + 1))


async def _add_message_ref(db: AsyncSession, conversation_id: int, query_id: int) -> None:
    """消息中的 query_id 在历史落库后回填（需要 history.id）。"""
    msg = (
        await db.execute(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if msg and msg.content.get("type") == "result":
        msg.content = {**msg.content, "query_id": query_id}
        await db.commit()


async def _refuse(db, history, conversation_id, question, reason, emit, started) -> QueryHistory:
    """越界拒答出口（FR-NLU-03）：不生成 SQL，记录 refused 并给引导。"""
    history.exec_status = "refused"
    history.duration_ms = int((time.monotonic() - started) * 1000)
    db.add(history)
    await _add_message(db, conversation_id, "assistant",
                       {"type": "refused", "message": reason})
    await audit_service.record(db, user_id=history.user_id, action="query.refused",
                               detail={"question": question[:200], "reason": reason})
    await db.commit()
    await emit("error", {"code": 42201, "user_message": reason, "retryable": False})
    await emit("done", {"query_id": history.id})
    raise AppError(42201, reason, 422)


async def _clarify(db, history, conversation_id, question, q, options, emit, started) -> QueryHistory:
    """澄清出口（FR-NLU-02）：反问候选项，不硬编 SQL（AC-08）。"""
    history.exec_status = "clarify"
    history.duration_ms = int((time.monotonic() - started) * 1000)
    db.add(history)
    await _add_message(db, conversation_id, "assistant",
                       {"type": "clarify", "question": q, "options": options})
    await db.commit()
    await emit("clarify", {"question": q, "options": options})
    await emit("done", {"query_id": history.id})
    return history


async def _exhausted(db, history, conversation_id, question, generated, hint, emit, started) -> QueryHistory:
    """重试耗尽出口（§3.2）：展示最后 SQL 与原因，提供人工编辑/转人工出口。"""
    history.exec_status = "failed"
    history.generated_sql = generated.sql if generated else None
    history.duration_ms = int((time.monotonic() - started) * 1000)
    db.add(history)
    await _add_message(db, conversation_id, "assistant", {
        "type": "error", "code": 42203,
        "message": "多次尝试后仍无法生成正确的 SQL",
        "last_sql": generated.sql if generated else None,
        "hint": hint, "actions": ["edit_sql", "retry", "contact_admin"],
    })
    await audit_service.record(db, user_id=history.user_id, action="query.exhausted",
                               detail={"question": question[:200]})
    await db.commit()
    await emit("error", {"code": 42203, "user_message": "多次尝试后仍无法生成正确的查询，可编辑 SQL 或换个问法",
                         "retryable": True})
    await emit("done", {"query_id": history.id})
    raise AppError(42203, "多次尝试后仍无法生成正确的查询", 422)
