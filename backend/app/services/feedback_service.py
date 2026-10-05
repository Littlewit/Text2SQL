"""反馈服务（FR-UI-08、R-10）：反馈提交 → 审核 → 转入 Few-shot 样例库。"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.infra.models import Feedback, QueryHistory
from app.services import audit_service, vectorizer

if TYPE_CHECKING:
    pass


async def create_feedback(
    db: AsyncSession, user_id: int, query_history_id: int,
    rating: str, correction_sql: str | None, comment: str | None,
) -> Feedback:
    """提交反馈：同一用户对同一查询仅一次；纠正 SQL 需为 down 评分场景。"""
    hist = await db.get(QueryHistory, query_history_id)
    if hist is None or hist.user_id != user_id:
        raise AppError(40400, "查询记录不存在", 404)
    if rating not in ("up", "down"):
        raise AppError(40001, "rating 必须为 up 或 down", 400)

    dup = (
        await db.execute(
            select(Feedback).where(
                Feedback.query_history_id == query_history_id, Feedback.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if dup:
        raise AppError(40005, "您已对该结果提交过反馈", 409)

    fb = Feedback(
        query_history_id=query_history_id,
        user_id=user_id,
        rating=rating,
        correction_sql=correction_sql,
        comment=comment,
    )
    db.add(fb)
    await audit_service.record(
        db, user_id=user_id, action="feedback.create",
        object_type="feedback", object_id=str(fb.id),
        detail={"rating": rating, "question": (hist.question or "")[:100]},
    )
    await db.commit()
    return fb


async def review_feedback(
    db: AsyncSession, feedback_id: int, reviewer, approve: bool,
) -> Feedback:
    """数据管理员审核反馈（R-DA/R-AD，FR-ADM-04）。

    采纳 down+纠错反馈 → 自动创建启用的 Few-shot 样例并向量izes（问题来自原查询）。
    """
    fb = await db.get(Feedback, feedback_id)
    if fb is None:
        raise AppError(40400, "反馈不存在", 404)
    if fb.review_status != "pending":
        raise AppError(40006, "该反馈已审核", 409)

    fb.review_status = "approved" if approve else "rejected"
    fb.reviewer_id = reviewer.id
    fb.reviewed_at = datetime.now(timezone.utc)

    if approve and fb.rating == "down" and fb.correction_sql:
        hist = await db.get(QueryHistory, fb.query_history_id)
        sample = await vectorizer.build_few_shot(
            db, get_embedder_safe(),
            datasource_id=hist.datasource_id if hist else None,
            question=hist.question if hist else "",
            sql_text=fb.correction_sql,
            status=1,  # 采纳即启用（FR-ADM-04）
        )
        db.add(sample)
        await db.flush()
        fb.sample_id = sample.id
        await vectorizer.vectorize_object(db, get_embedder_safe(), "few_shot", sample.id)

    await audit_service.record(
        db, user_id=reviewer.id, action="feedback.review",
        object_type="feedback", object_id=str(fb.id),
        detail={"approve": approve, "sample_id": fb.sample_id},
    )
    await db.commit()
    return fb


async def list_pending_feedbacks(db: AsyncSession, limit: int = 50) -> list[Feedback]:
    """待审核反馈列表（最新优先）。"""
    return list(
        (
            await db.execute(
                select(Feedback)
                .where(Feedback.review_status == "pending")
                .order_by(Feedback.id.desc())
                .limit(limit)
            )
        ).scalars()
    )


def get_embedder_safe():
    from app.llm.embedding import get_embedder

    return get_embedder()
