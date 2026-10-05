"""Celery 任务注册（DEP-01 worker 服务）。

T6 阶段任务以同步内联为主（向量化在标注 API 内联执行）；
本模块提供异步化入口：耗时的扫描/向量化/导出/评测在 T5+ 按需迁移至队列。
"""

from app.workers.celery_app import celery_app


@celery_app.task(name="schema.vectorize_datasource")
def vectorize_datasource(datasource_id: int) -> int:
    """全量重建数据源向量（DR-04：Embedding 模型变更时触发）。"""
    import asyncio
    import sys

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    from app.core.config import get_settings
    from app.infra.db import get_session_factory, reset_engine
    from app.llm.embedding import get_embedder
    from app.services.vectorizer import revectorize_datasource

    get_settings.cache_clear()
    reset_engine()

    async def _run() -> int:
        async with get_session_factory()() as db:
            return await revectorize_datasource(db, get_embedder(), datasource_id)

    return asyncio.run(_run())
