"""审计服务（FR-SEC-42）。

所有敏感操作必须调用 record 落审计；detail 中的敏感值由调用方脱敏（FR-SEC-44）。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import AuditLog


async def record(
    session: AsyncSession,
    *,
    user_id: int | None,
    action: str,
    object_type: str | None = None,
    object_id: str | None = None,
    detail: dict | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """写入一条审计记录；随业务事务一起提交，保证原子性。"""
    session.add(
        AuditLog(
            user_id=user_id,
            action=action,
            object_type=object_type,
            object_id=object_id,
            detail=detail,
            ip=ip,
            user_agent=user_agent,
        )
    )
