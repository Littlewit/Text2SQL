"""审计日志检索路由（R-AD/R-AU，FR-SEC-42）。

只读接口：审计记录无更新/删除入口，保证不可篡改（FR-SEC-43）。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles
from app.core.errors import ok
from app.infra.db import get_session
from app.infra.models import AuditLog, User

router = APIRouter(prefix="/admin/audit-logs", tags=["admin:audit"])

ad_or_au = require_roles("R-AD", "R-AU")


@router.get("")
async def list_audit_logs(
    user_id: int | None = Query(default=None),
    action: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: User = Depends(ad_or_au),
    db: AsyncSession = Depends(get_session),
):
    """审计日志分页检索：支持按操作人与动作类型过滤。"""
    stmt = select(AuditLog)
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await db.execute(
            stmt.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars()

    return ok(
        {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [
                {
                    "id": r.id,
                    "user_id": r.user_id,
                    "action": r.action,
                    "object_type": r.object_type,
                    "object_id": r.object_id,
                    "detail": r.detail,
                    "ip": r.ip,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
        }
    )
