"""运营与维护端点（FR-ADM-06、FR-SEC-43、FR-ADM-07、M2-T5/T6）。"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles
from app.core.errors import AppError, ok
from app.infra.db import get_session
from app.infra.models import EvalReportRun, User
from app.services import cleanup_service, dashboard_service, eval_service

router = APIRouter()

# 看板面向数据分析/管理员；清理属高危运维，仅管理员（§2.2 权限矩阵）
ops_or_ad = require_roles("R-DA", "R-AD")
ad_only = require_roles("R-AD")


@router.get("/admin/ops/dashboard")
async def ops_dashboard(
    days: int = Query(default=7, ge=1, le=90),
    _: User = Depends(ops_or_ad),
    db: AsyncSession = Depends(get_session),
):
    """运营看板（FR-ADM-06）：查询量/成功率/耗时分布/重试率/token/Top 问题与失败原因。"""
    return ok(await dashboard_service.get_dashboard(db, days))


class CleanupRequest(BaseModel):
    dry_run: bool = True


@router.post("/admin/ops/cleanup")
async def ops_cleanup(
    body: CleanupRequest,
    user: User = Depends(ad_only),
    db: AsyncSession = Depends(get_session),
):
    """保留期清理（FR-SEC-43）：dry_run 预检，实删留审计；保留期读 sys_config（P-34/35）。"""
    return ok(await cleanup_service.cleanup_retention(db, user.id, body.dry_run))


# ==================== 评测管理（FR-ADM-07，M2-T6） ====================
class EvalRunRequest(BaseModel):
    mode: str = Query(default="offline", pattern="^(offline|full)$")


@router.post("/admin/ops/eval/run", status_code=202)
async def eval_run(
    body: EvalRunRequest,
    user: User = Depends(ad_only),
    db: AsyncSession = Depends(get_session),
):
    """触发评测（FR-ADM-07）：offline 确定性快；full 调真实 LLM（后台线程，轮询报告列表）。"""
    import os

    if body.mode == "full" and not (
        os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY")
    ):
        raise AppError(40001, "未配置 LLM 密钥，无法执行全量评测", 400)
    if not eval_service.acquire_lock():
        raise AppError(42901, "已有评测任务在执行，请稍后再试", 429)

    run = EvalReportRun(mode=body.mode, status="running", operator_id=user.id)
    db.add(run)
    await db.commit()
    eval_service.start_eval(body.mode, user.id, run.id)
    return ok({"run_id": run.id, "status": "running"})


@router.get("/admin/ops/eval/reports")
async def eval_reports(
    limit: int = Query(default=20, ge=1, le=100),
    _: User = Depends(ops_or_ad),
    db: AsyncSession = Depends(get_session),
):
    """评测报告列表（新→旧），前端轮询获取后台评测进度。"""
    runs = await eval_service.list_runs(db, limit)
    return ok([
        {"id": r.id, "mode": r.mode, "status": r.status, "total": r.total,
         "passed": r.passed, "failed": r.failed, "skipped": r.skipped,
         "pass_rate": r.pass_rate, "duration_ms": r.duration_ms,
         "model_version": r.model_version, "created_at": str(r.created_at)}
        for r in runs
    ])


@router.get("/admin/ops/eval/reports/{run_id}")
async def eval_report_detail(
    run_id: int,
    _: User = Depends(ops_or_ad),
    db: AsyncSession = Depends(get_session),
):
    """评测报告详情：分维度统计与失败用例明细。"""
    run = await eval_service.get_run(db, run_id)
    return ok({
        "id": run.id, "mode": run.mode, "status": run.status,
        "total": run.total, "passed": run.passed, "failed": run.failed,
        "skipped": run.skipped, "pass_rate": run.pass_rate,
        "by_tag": run.by_tag, "failures": run.failures,
        "duration_ms": run.duration_ms, "model_version": run.model_version,
        "created_at": str(run.created_at),
    })


@router.get("/admin/ops/eval/compare")
async def eval_compare(
    a: int = Query(..., description="基准报告 id"),
    b: int = Query(..., description="对比报告 id"),
    _: User = Depends(ops_or_ad),
    db: AsyncSession = Depends(get_session),
):
    """分维度对比两份评测报告（EV-05 回归对比）。"""
    run_a = await eval_service.get_run(db, a)
    run_b = await eval_service.get_run(db, b)
    return ok(eval_service.compare_runs(run_a, run_b))
