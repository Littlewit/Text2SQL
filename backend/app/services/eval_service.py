"""评测管理服务（FR-ADM-07、M2-T6）：触发评测、报告入库、历史与分维度对比。

执行模型：
- offline 模式确定性（秒级），可同步等待结果；
- full 模式调真实 LLM（分钟级），提交后台线程执行，行状态 running->done/failed。
线程内通过独立事件循环写库（与 eval.ex_utils 同模式），不与请求循环共享连接。
"""

import asyncio
import sys
import threading

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.infra.models import EvalReportRun

# 进程内防并发：同一时刻只允许一个评测任务
_eval_lock = threading.Lock()


def _asyncio_run(coro):
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(coro)


async def list_runs(db: AsyncSession, limit: int = 20) -> list[EvalReportRun]:
    """评测报告列表（新到旧）。"""
    return list(
        (
            await db.execute(
                select(EvalReportRun).order_by(EvalReportRun.id.desc()).limit(limit)
            )
        ).scalars()
    )

async def get_run(db: AsyncSession, run_id: int) -> EvalReportRun:
    run = await db.get(EvalReportRun, run_id)
    if run is None:
        raise AppError(40400, "评测报告不存在", 404)
    return run


def compare_runs(a: EvalReportRun, b: EvalReportRun) -> dict:
    """分维度对比：b 相对 a 的通过率变化（EV-05 回归对比）。"""
    tags = set((a.by_tag or {}).keys()) | set((b.by_tag or {}).keys())
    delta = {}
    for t in sorted(tags):
        sa_ = (a.by_tag or {}).get(t, {})
        sb = (b.by_tag or {}).get(t, {})
        ra = sa_.get("passed", 0) / max(sa_.get("total", 0), 1)
        rb = sb.get("passed", 0) / max(sb.get("total", 0), 1)
        delta[t] = {"a": round(ra, 4), "b": round(rb, 4),
                    "diff": round(rb - ra, 4), "total_b": sb.get("total", 0)}
    return {
        "a": {"id": a.id, "pass_rate": a.pass_rate, "created_at": str(a.created_at)},
        "b": {"id": b.id, "pass_rate": b.pass_rate, "created_at": str(b.created_at)},
        "overall_diff": round((b.pass_rate or 0) - (a.pass_rate or 0), 4),
        "by_tag": delta,
    }


def acquire_lock() -> bool:
    """尝试获取评测执行锁（非阻塞），防止并发评测。"""
    return _eval_lock.acquire(blocking=False)


def start_eval(mode: str, operator_id: int, run_id: int) -> None:
    """启动评测线程（须先建 running 行并持有锁）。full 模式为真实 LLM 调用。"""
    thread = threading.Thread(target=_run_eval_thread, args=(mode, operator_id, run_id), daemon=True)
    thread.start()


def _run_eval_thread(mode: str, operator_id: int, run_id: int) -> None:
    """评测线程体：跑评测，结果写回报告行。"""

    async def _finish() -> None:
        from app.core.config import get_settings
        from app.infra.db import get_session_factory, reset_engine
        from eval.runner import load_cases, run_eval

        reset_engine()
        async with get_session_factory()() as db:
            run = await db.get(EvalReportRun, run_id)
            if run is None:
                return
            try:
                cases = load_cases()
                report = run_eval(cases, offline_only=(mode == "offline"))
                d = report.to_dict()
                run.status = "done"
                run.total, run.passed = d["total"], d["passed"]
                run.failed, run.skipped = d["failed"], d["skipped"]
                run.pass_rate = d["pass_rate"]
                run.by_tag = d["by_tag"]
                run.failures = d["failures"]
                run.duration_ms = d["duration_ms"]
                run.model_version = get_settings().llm_model
            except Exception as e:  # noqa: BLE001 -- 评测失败落状态，不炸线程
                run.status = "failed"
                run.failures = [{"error": str(e)[:300]}]
            await db.commit()

    try:
        _asyncio_run(_finish())
    finally:
        _eval_lock.release()
