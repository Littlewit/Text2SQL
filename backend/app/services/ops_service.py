"""运营分析服务（FR-ADM-08）：未覆盖问题统计——澄清/拒答/失败问题的聚类清单。"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import QueryHistory

# 视为「未覆盖」的执行状态
UNCOVERED_STATUS = ("clarify", "refused", "failed")


async def uncaptured_questions(db: AsyncSession, limit: int = 50) -> dict:
    """按问题原文聚合未覆盖查询：出现次数 + 最近时间 + 状态分布。

    供数据管理员补充指标/标注/样例（R-02、R-09 闭环）。
    """
    rows = (
        await db.execute(
            select(
                QueryHistory.question,
                func.count().label("cnt"),
                func.max(QueryHistory.created_at).label("last_at"),
                func.array_agg(QueryHistory.exec_status).label("statuses"),
            )
            .where(
                QueryHistory.exec_status.in_(UNCOVERED_STATUS),
                QueryHistory.is_deleted.is_(False),
            )
            .group_by(QueryHistory.question)
            .order_by(func.count().desc())
            .limit(limit)
        )
    ).all()

    items = [
        {
            "question": r.question,
            "count": r.cnt,
            "last_seen": r.last_at.isoformat() if r.last_at else None,
            "statuses": sorted(set(r.statuses)),
        }
        for r in rows
    ]
    total_uncovered = (
        await db.execute(
            select(func.count())
            .select_from(QueryHistory)
            .where(QueryHistory.exec_status.in_(UNCOVERED_STATUS), QueryHistory.is_deleted.is_(False))
        )
    ).scalar_one()
    return {"total_uncovered": total_uncovered, "distinct": len(items), "items": items}
