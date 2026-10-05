"""运营与维护端点（FR-ADM-06、FR-SEC-43、M2-T5）。"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles
from app.core.errors import ok
from app.infra.db import get_session
from app.infra.models import User
from app.services import cleanup_service, dashboard_service

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
