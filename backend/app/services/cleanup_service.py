"""保留期清理任务（FR-SEC-43、P-34/P-35）：审计日志与查询历史定时归档清理。

保留期读 sys_config（天）：
- audit.retention_days（默认 180）
- history.retention_days（默认 90）
支持 dry_run 预检：只统计不删除。生产由 Celery beat 定时触发（T6），
当前提供管理端点手动触发（每次执行留审计）。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_config_value
from app.infra.models import AuditLog, Feedback, QueryHistory
from app.services import audit_service


async def cleanup_retention(db: AsyncSession, operator_id: int, dry_run: bool = True) -> dict:
    """按保留期清理审计日志与查询历史；返回统计，dry_run=true 时只统计。"""
    now = datetime.now(timezone.utc)
    audit_cutoff = now - timedelta(
        days=int(await get_config_value(db, "audit.retention_days", 180))
    )
    history_cutoff = now - timedelta(
        days=int(await get_config_value(db, "history.retention_days", 90))
    )

    audit_cnt = (
        await db.execute(
            select(func.count()).select_from(AuditLog).where(AuditLog.created_at < audit_cutoff)
        )
    ).scalar_one()
    history_cnt = (
        await db.execute(
            select(func.count()).select_from(QueryHistory).where(
                QueryHistory.created_at < history_cutoff
            )
        )
    ).scalar_one()

    result = {
        "dry_run": dry_run,
        "audit_cutoff": audit_cutoff.isoformat(),
        "history_cutoff": history_cutoff.isoformat(),
        "audit_to_delete": int(audit_cnt),
        "history_to_delete": int(history_cnt),
    }
    if not dry_run:
        await db.execute(delete(AuditLog).where(AuditLog.created_at < audit_cutoff))
        # 先删关联反馈再删历史（feedback.query_history_id 外键引用）
        old_ids = select(QueryHistory.id).where(QueryHistory.created_at < history_cutoff)
        await db.execute(delete(Feedback).where(Feedback.query_history_id.in_(old_ids)))
        await db.execute(delete(QueryHistory).where(QueryHistory.created_at < history_cutoff))
        await audit_service.record(
            db, user_id=operator_id, action="admin.maintenance.cleanup",
            detail={**result, "executed": True},
        )
        await db.commit()
    return result
