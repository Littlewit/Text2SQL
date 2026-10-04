"""指标 / 同义词 / 枚举字典 / JOIN 路径维护服务（FR-SCH-11~14）。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.infra.models import EnumDict, JoinPath, MetaRevision, Metric, Synonym
from app.services import audit_service, vectorizer


# --- 指标（FR-SCH-12）---
async def list_metrics(db: AsyncSession) -> list[Metric]:
    return list((await db.execute(select(Metric).order_by(Metric.id))).scalars())


async def create_metric(db: AsyncSession, embedder, data, operator_id: int) -> Metric:
    exists = (await db.execute(select(Metric).where(Metric.code == data.code))).scalar_one_or_none()
    if exists:
        raise AppError(40004, "指标编码已存在", 409)
    m = Metric(
        datasource_id=data.datasource_id,
        name=data.name,
        code=data.code,
        description=data.description,
        formula=data.formula,
        agg_type=data.agg_type,
        default_time_column=data.default_time_column,
        unit=data.unit,
    )
    db.add(m)
    await db.flush()
    await audit_service.record(
        db, user_id=operator_id, action="admin.metric.create",
        object_type="metric", object_id=str(m.id), detail={"code": m.code, "name": m.name},
    )
    await db.commit()
    await vectorizer.vectorize_object(db, embedder, "metric", m.id)
    return m


async def update_metric(db: AsyncSession, embedder, metric_id: int, fields: dict, operator_id: int) -> Metric:
    m = await db.get(Metric, metric_id)
    if m is None:
        raise AppError(40400, "指标不存在", 404)
    # 变更前快照（DR-03）
    db.add(
        MetaRevision(
            object_type="metric", object_id=m.id,
            snapshot=m.to_dict(), op="update", operator_id=operator_id,
        )
    )
    for k in ("name", "description", "formula", "agg_type", "default_time_column", "unit", "status", "datasource_id"):
        if k in fields and fields[k] is not None:
            setattr(m, k, fields[k])
    await audit_service.record(
        db, user_id=operator_id, action="admin.metric.update",
        object_type="metric", object_id=str(m.id),
        detail={"fields": {k: v for k, v in fields.items() if v is not None}},
    )
    await db.commit()
    await vectorizer.vectorize_object(db, embedder, "metric", m.id)
    return m


# --- 同义词（FR-SCH-13）---
async def list_synonyms(db: AsyncSession, datasource_id: int | None = None) -> list[Synonym]:
    stmt = select(Synonym)
    if datasource_id is not None:
        stmt = stmt.where((Synonym.datasource_id == datasource_id) | (Synonym.datasource_id.is_(None)))
    return list((await db.execute(stmt).order_by(Synonym.id)).scalars())


async def create_synonym(db: AsyncSession, embedder, data, operator_id: int) -> Synonym:
    s = Synonym(
        term=data.term,
        target_type=data.target_type,
        target_id=data.target_id,
        datasource_id=data.datasource_id,
    )
    db.add(s)
    await db.flush()
    await audit_service.record(
        db, user_id=operator_id, action="admin.synonym.create",
        object_type="synonym", object_id=str(s.id), detail={"term": s.term, "target": f"{s.target_type}:{s.target_id}"},
    )
    await db.commit()
    await vectorizer.vectorize_object(db, embedder, "synonym", s.id)
    return s


async def delete_synonym(db: AsyncSession, synonym_id: int, operator_id: int) -> None:
    s = await db.get(Synonym, synonym_id)
    if s is None:
        raise AppError(40400, "同义词不存在", 404)
    await db.delete(s)
    await audit_service.record(
        db, user_id=operator_id, action="admin.synonym.delete",
        object_type="synonym", object_id=str(synonym_id), detail={"term": s.term},
    )
    await db.commit()


# --- 枚举字典（FR-SCH-11）---
async def list_enum_dicts(db: AsyncSession, column_meta_id: int | None = None) -> list[EnumDict]:
    stmt = select(EnumDict)
    if column_meta_id is not None:
        stmt = stmt.where(EnumDict.column_meta_id == column_meta_id)
    return list((await db.execute(stmt).order_by(EnumDict.id)).scalars())


async def upsert_enum_dict(db: AsyncSession, data, operator_id: int) -> EnumDict:
    """同 (column, raw_value) 唯一：存在则更新展示名。"""
    e = (
        await db.execute(
            select(EnumDict).where(
                EnumDict.column_meta_id == data.column_meta_id,
                EnumDict.raw_value == data.raw_value,
            )
        )
    ).scalar_one_or_none()
    if e is None:
        e = EnumDict(column_meta_id=data.column_meta_id, raw_value=data.raw_value)
        db.add(e)
    e.display_name = data.display_name
    await audit_service.record(
        db, user_id=operator_id, action="admin.enum.upsert",
        object_type="enum_dict", object_id=str(data.column_meta_id),
        detail={"raw": data.raw_value, "display": data.display_name},
    )
    await db.commit()
    return e


# --- JOIN 路径（FR-SCH-14）---
async def list_join_paths(db: AsyncSession, datasource_id: int | None = None) -> list[JoinPath]:
    stmt = select(JoinPath)
    if datasource_id is not None:
        stmt = stmt.where(JoinPath.datasource_id == datasource_id)
    return list((await db.execute(stmt)).scalars())


async def create_join_path(db: AsyncSession, data, operator_id: int) -> JoinPath:
    jp = JoinPath(
        datasource_id=data.datasource_id,
        left_table_id=data.left_table_id,
        right_table_id=data.right_table_id,
        left_column=data.left_column,
        right_column=data.right_column,
        join_type=data.join_type or "inner",
        description=data.description,
    )
    db.add(jp)
    await audit_service.record(
        db, user_id=operator_id, action="admin.join_path.create",
        object_type="join_path", object_id=str(jp.id),
        detail={"left": f"{jp.left_table_id}.{jp.left_column}", "right": f"{jp.right_table_id}.{jp.right_column}"},
    )
    await db.commit()
    return jp
