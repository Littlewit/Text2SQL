"""元数据标注服务：表/字段业务标注 + 变更历史 + 回滚（FR-SCH-10、DR-03、FR-ADM-03）。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.infra.models import ColumnMeta, MetaRevision, TableMeta
from app.services import audit_service, vectorizer
from app.services.schema_retrieval.retriever import search


async def _snapshot_and_track(
    db: AsyncSession, obj, object_type: str, operator_id: int
) -> None:
    """变更前快照入 meta_revision（DR-03：变更历史可回滚）。"""
    db.add(
        MetaRevision(
            object_type=object_type,
            object_id=obj.id,
            snapshot=obj.to_dict(),
            op="update",
            operator_id=operator_id,
        )
    )


async def annotate_table(
    db: AsyncSession, embedder, table_id: int, fields: dict, operator_id: int
) -> TableMeta:
    """更新表标注（cn_name/description/included），快照留痕并重向量。"""
    tm = await db.get(TableMeta, table_id)
    if tm is None:
        raise AppError(40400, "表不存在", 404)
    await _snapshot_and_track(db, tm, "table", operator_id)

    for k in ("cn_name", "description", "included"):
        if k in fields and fields[k] is not None:
            setattr(tm, k, fields[k])

    await audit_service.record(
        db, user_id=operator_id, action="admin.schema.annotate_table",
        object_type="table", object_id=str(table_id),
        detail={"fields": {k: v for k, v in fields.items() if v is not None}},
    )
    await db.commit()
    await vectorizer.vectorize_object(db, embedder, "table", table_id)
    return tm


async def annotate_column(
    db: AsyncSession, embedder, column_id: int, fields: dict, operator_id: int
) -> ColumnMeta:
    """更新字段标注（cn_name/description/unit/usage_type/is_sensitive）。"""
    cm = await db.get(ColumnMeta, column_id)
    if cm is None:
        raise AppError(40400, "字段不存在", 404)
    await _snapshot_and_track(db, cm, "column", operator_id)

    for k in ("cn_name", "description", "unit", "usage_type", "is_sensitive", "hidden_roles"):
        if k in fields and fields[k] is not None:
            setattr(cm, k, fields[k])

    await audit_service.record(
        db, user_id=operator_id, action="admin.schema.annotate_column",
        object_type="column", object_id=str(column_id),
        detail={"fields": {k: v for k, v in fields.items() if v is not None}},
    )
    await db.commit()
    await vectorizer.vectorize_object(db, embedder, "column", column_id)
    return cm


async def rollback_table(db: AsyncSession, embedder, table_id: int, operator_id: int) -> TableMeta:
    """回滚表标注到上一版本（FR-ADM-03）：取最近一次快照恢复标注字段。"""
    tm = await db.get(TableMeta, table_id)
    if tm is None:
        raise AppError(40400, "表不存在", 404)

    rev = (
        await db.execute(
            select(MetaRevision)
            .where(MetaRevision.object_type == "table", MetaRevision.object_id == table_id)
            .order_by(MetaRevision.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if rev is None:
        raise AppError(40401, "没有可回滚的历史版本", 404)

    snap = rev.snapshot
    for k in ("cn_name", "description", "included"):
        if k in snap and snap[k] is not None:
            setattr(tm, k, snap[k])

    await _snapshot_and_track(db, tm, "table", operator_id)  # 回滚本身也留痕
    await audit_service.record(
        db, user_id=operator_id, action="admin.schema.rollback_table",
        object_type="table", object_id=str(table_id), detail={"restored_from": rev.id},
    )
    await db.commit()
    await vectorizer.vectorize_object(db, embedder, "table", table_id)
    return tm


async def compute_annotation_score(db: AsyncSession, table_id: int) -> float:
    """标注完整度评分（FR-SCH-15）：已标注中文名/描述的字段占比。"""
    cols = (
        await db.execute(select(ColumnMeta).where(ColumnMeta.table_meta_id == table_id))
    ).scalars()
    total, annotated = 0, 0
    for c in cols:
        total += 1
        if c.cn_name or c.description:
            annotated += 1
    if total == 0:
        return 0.0
    score = round(annotated / total * 100, 2)
    tm = await db.get(TableMeta, table_id)
    if tm:
        tm.annotation_score = score
        await db.commit()
    return score


async def search_schema(db: AsyncSession, embedder, query: str, datasource_id: int | None, top_k: int):
    """面向管理台的检索入口（标注验收用），返回可解释结果（FR-SCH-24）。"""
    from app.services.schema_retrieval.retriever import to_explainable

    results = await search(db, embedder, query, datasource_id, top_k)
    return to_explainable(results)
