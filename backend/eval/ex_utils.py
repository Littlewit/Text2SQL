"""评测执行辅助：连接信息与 LLM 链路调用（与评测 runner 解耦，便于 mock）。"""

import os

from sqlalchemy import select


def eval_connection_info() -> str:
    """demo 库连接串：评测数据源固定为 dev 容器的 demo_business。"""
    host = os.environ.get("ITEST_DB_HOST", "localhost")
    port = os.environ.get("ITEST_DB_PORT", "5433")
    user = os.environ.get("ITEST_DB_USER", "t2s")
    password = os.environ.get("ITEST_DB_PASSWORD", "t2s")
    return f"host={host} port={port} dbname=demo_business user={user} password={password}"


def eval_nlu_only(question: str):
    """仅执行 NLU 阶段（refused/clarify/intent 评测用，不进入 SQL 生成）。"""
    from app.core.config import get_settings
    from app.infra.db import get_session_factory, reset_engine

    get_settings.cache_clear()
    reset_engine()

    from app.llm.client import get_llm
    from app.services.nlu.intent import understand

    async def _run():
        async with get_session_factory()() as db:
            return await understand(db, get_llm(), question)

    return asyncio_run(_run())


def run_text2sql(question: str, datasource_name: str) -> str | None:
    """完整链路：NLU → 检索 → Prompt → 生成 → sql_guard（含白名单），返回最终 SQL。

    权限改写按管理员全量视图（无策略注入）——评测关注生成质量而非权限。
    """
    from app.core.config import get_settings
    from app.infra.db import get_session_factory, reset_engine
    from app.infra.models import Datasource

    get_settings.cache_clear()
    reset_engine()

    from app.llm.client import get_llm
    from app.services.nlu.intent import understand
    from app.services.prompt.builder import build_sql_prompt, recall_few_shots
    from app.services.schema_retrieval.retriever import search
    from app.services.sql_gen.generator import generate_sql
    from app.services.sql_guard import validate

    async def _run() -> str | None:
        async with get_session_factory()() as db:
            ds = (
                await db.execute(select(Datasource).where(Datasource.name == datasource_name))
            ).scalars().first()
            ds_id = ds.id if ds else None
            llm = get_llm()

            nlu = await understand(db, llm, question)
            if nlu.out_of_scope or nlu.clarify_question:
                return None

            recalled = await search(db, _embedder(), question, ds_id, top_k=10)
            schema_fragment, metrics_fragment = await _render(db, recalled, nlu)
            few_shots = await recall_few_shots(db, _embedder(), question, ds_id)
            messages, _ = build_sql_prompt(question, schema_fragment, metrics_fragment,
                                           few_shots, nlu, row_limit=1000)
            generated, _ = await generate_sql(llm, messages)

            guard_ctx = await _guard_ctx(db, ds_id)
            guard, errs = validate(generated.sql, guard_ctx)
            return (guard.rewritten_sql or generated.sql) if guard.ok else f"__REJECTED__ {errs[0].message}"

    return asyncio_run(_run())


async def _render(db, recalled, nlu):
    from app.infra.models import ColumnMeta, EnumDict, Metric, TableMeta
    from app.services.prompt.builder import render_metrics, render_schema_fragment

    table_ids = {r.object_id for r in recalled if r.object_type == "table"}
    tables = (await db.execute(select(TableMeta).where(TableMeta.id.in_(table_ids or {0})))).scalars().all()
    columns: dict[int, list] = {}
    enums: dict[int, list] = {}
    for tm in tables:
        cm_rows = (await db.execute(select(ColumnMeta).where(ColumnMeta.table_meta_id == tm.id))).scalars().all()
        columns[tm.id] = list(cm_rows)
        for cm in cm_rows:
            e_rows = (await db.execute(select(EnumDict).where(EnumDict.column_meta_id == cm.id))).scalars().all()
            if e_rows:
                enums[cm.id] = list(e_rows)
    metric_ids = {r.object_id for r in recalled if r.object_type == "metric"}
    metrics = (await db.execute(select(Metric).where(Metric.id.in_(metric_ids or {0})))).scalars().all()
    return render_schema_fragment(tables, columns, enums), render_metrics(list(metrics))


async def _guard_ctx(db, ds_id):
    from app.infra.models import ColumnMeta, TableMeta
    from app.services.sql_guard import GuardContext

    tables = (await db.execute(select(TableMeta).where(TableMeta.datasource_id == ds_id,
                                                       TableMeta.included.is_(True)))).scalars().all()
    allowed: dict[str, set[str]] = {}
    for tm in tables:
        cols = (await db.execute(select(ColumnMeta.column_name).where(ColumnMeta.table_meta_id == tm.id))).scalars()
        allowed[tm.table_name.lower()] = {c.lower() for c in cols}
    return GuardContext(allowed_tables=allowed, row_limit=1000)


def _embedder():
    from app.llm.embedding import get_embedder

    return get_embedder()


def asyncio_run(coro):
    import asyncio
    import sys

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(coro)
