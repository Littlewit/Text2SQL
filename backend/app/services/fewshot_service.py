"""Few-shot 样例库管理服务（FR-ADM-04）：录入/审核/启停/分类/命中统计。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.infra.models import FewShot
from app.services import audit_service, vectorizer

# status: 2=待审核 1=启用 0=停用
STATUS_PENDING, STATUS_ENABLED, STATUS_DISABLED = 2, 1, 0


async def list_few_shots(
    db: AsyncSession, datasource_id: int | None = None, status: int | None = None
) -> list[FewShot]:
    stmt = select(FewShot)
    if datasource_id is not None:
        stmt = stmt.where((FewShot.datasource_id == datasource_id) | (FewShot.datasource_id.is_(None)))
    if status is not None:
        stmt = stmt.where(FewShot.status == status)
    stmt = stmt.order_by(FewShot.id.desc())
    return list((await db.execute(stmt)).scalars())


async def create_few_shot(db: AsyncSession, embedder, data, operator_id: int) -> FewShot:
    """录入样例：新录入为待审核（status=2），审核通过后启用并可被召回。"""
    fs = await vectorizer.build_few_shot(
        db, embedder,
        datasource_id=data.datasource_id,
        question=data.question,
        sql_text=data.sql_text,
        intent=data.intent,
        explanation=data.explanation,
        status=STATUS_PENDING,
    )
    db.add(fs)
    await db.flush()
    await audit_service.record(
        db, user_id=operator_id, action="admin.fewshot.create",
        object_type="few_shot", object_id=str(fs.id),
        detail={"question": fs.question[:100]},
    )
    await db.commit()
    await vectorizer.vectorize_object(db, embedder, "few_shot", fs.id)
    return fs


async def review_few_shot(db: AsyncSession, embedder, fs_id: int, approve: bool, operator_id: int) -> FewShot:
    """审核样例：通过 → 启用；驳回 → 停用。"""
    fs = await db.get(FewShot, fs_id)
    if fs is None:
        raise AppError(40400, "样例不存在", 404)
    fs.status = STATUS_ENABLED if approve else STATUS_DISABLED
    await audit_service.record(
        db, user_id=operator_id, action="admin.fewshot.review",
        object_type="few_shot", object_id=str(fs_id), detail={"approve": approve},
    )
    await db.commit()
    return fs


async def update_few_shot(db: AsyncSession, embedder, fs_id: int, fields: dict, operator_id: int) -> FewShot:
    fs = await db.get(FewShot, fs_id)
    if fs is None:
        raise AppError(40400, "样例不存在", 404)
    for k in ("question", "sql_text", "intent", "explanation", "status"):
        if k in fields and fields[k] is not None:
            setattr(fs, k, fields[k])
    await audit_service.record(
        db, user_id=operator_id, action="admin.fewshot.update",
        object_type="few_shot", object_id=str(fs_id),
        detail={"fields": {k: v for k, v in fields.items() if v is not None}},
    )
    await db.commit()
    await vectorizer.vectorize_object(db, embedder, "few_shot", fs_id)
    return fs


async def delete_few_shot(db: AsyncSession, fs_id: int, operator_id: int) -> None:
    fs = await db.get(FewShot, fs_id)
    if fs is None:
        raise AppError(40400, "样例不存在", 404)
    await db.delete(fs)
    await audit_service.record(
        db, user_id=operator_id, action="admin.fewshot.delete",
        object_type="few_shot", object_id=str(fs_id),
    )
    await db.commit()


async def increment_hit_counts(db: AsyncSession, sample_ids: list[int]) -> None:
    """召回命中计数（FR-ADM-04 效果统计）：批量 +1，不单独提交（随主流程事务）。"""
    if not sample_ids:
        return
    rows = (await db.execute(select(FewShot).where(FewShot.id.in_(sample_ids)))).scalars()
    for fs in rows:
        fs.hit_count = (fs.hit_count or 0) + 1
