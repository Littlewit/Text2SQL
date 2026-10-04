"""Schema 标注工作台路由（R-DA/R-AD）：扫描触发、表/字段标注、回滚、检索验收。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles
from app.core.errors import ok
from app.domain.schemas_meta import ColumnPatch, SchemaSearchRequest, TablePatch
from app.infra.db import get_session
from app.infra.models import ColumnMeta, TableMeta, User
from app.llm.embedding import get_embedder
from app.services import scan_service, schema_meta_service

router = APIRouter(prefix="/admin/schema", tags=["admin:schema"])

da_or_ad = require_roles("R-DA", "R-AD")


@router.post("/datasources/{ds_id}/scan")
async def scan_datasource(
    ds_id: int,
    operator: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    """触发表结构扫描（FR-SCH-02）：只读内省，返回增量统计。"""
    stats = await scan_service.scan_datasource(db, ds_id, operator.id)
    return ok(stats)


@router.get("/tables")
async def list_tables(
    datasource_id: int | None = Query(default=None),
    _: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    """表元数据列表（含标注与完整度）。"""
    stmt = select(TableMeta)
    if datasource_id is not None:
        stmt = stmt.where(TableMeta.datasource_id == datasource_id)
    items = (await db.execute(stmt.order_by(TableMeta.id))).scalars()
    return ok(
        [
            {
                "id": t.id,
                "datasource_id": t.datasource_id,
                "schema_name": t.schema_name,
                "table_name": t.table_name,
                "cn_name": t.cn_name,
                "description": t.description,
                "row_estimate": t.row_estimate,
                "included": t.included,
                "annotation_score": float(t.annotation_score) if t.annotation_score else 0,
                "columns_count": len(t.columns),
            }
            for t in items
        ]
    )


@router.get("/tables/{table_id}/columns")
async def list_columns(
    table_id: int,
    _: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    """字段元数据列表（含标注与枚举采样）。"""
    items = (
        await db.execute(
            select(ColumnMeta)
            .where(ColumnMeta.table_meta_id == table_id)
            .order_by(ColumnMeta.id)
        )
    ).scalars()
    return ok(
        [
            {
                "id": c.id,
                "column_name": c.column_name,
                "cn_name": c.cn_name,
                "data_type": c.data_type,
                "is_pk": c.is_pk,
                "is_fk": c.is_fk,
                "fk_ref": c.fk_ref,
                "description": c.description,
                "unit": c.unit,
                "usage_type": c.usage_type,
                "is_sensitive": c.is_sensitive,
                "sample_values": c.sample_values,
            }
            for c in items
        ]
    )


@router.patch("/tables/{table_id}")
async def annotate_table(
    table_id: int,
    body: TablePatch,
    operator: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    """表业务标注（快照留痕 + 重新向量化）。"""
    embedder = get_embedder()
    tm = await schema_meta_service.annotate_table(
        db, embedder, table_id, body.model_dump(), operator.id
    )
    score = await schema_meta_service.compute_annotation_score(db, table_id)
    return ok({"id": tm.id, "cn_name": tm.cn_name, "included": tm.included, "annotation_score": score})


@router.post("/tables/{table_id}/rollback")
async def rollback_table(
    table_id: int,
    operator: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    """回滚表标注到上一版本（DR-03、FR-ADM-03）。"""
    embedder = get_embedder()
    tm = await schema_meta_service.rollback_table(db, embedder, table_id, operator.id)
    return ok({"id": tm.id, "cn_name": tm.cn_name, "description": tm.description})


@router.patch("/columns/{column_id}")
async def annotate_column(
    column_id: int,
    body: ColumnPatch,
    operator: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    """字段业务标注（快照留痕 + 重新向量化）。"""
    embedder = get_embedder()
    cm = await schema_meta_service.annotate_column(
        db, embedder, column_id, body.model_dump(), operator.id
    )
    return ok({"id": cm.id, "cn_name": cm.cn_name, "usage_type": cm.usage_type})


@router.post("/search")
async def search_schema(
    body: SchemaSearchRequest,
    _: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    """Schema 混合检索（标注验收入口 + T3 主链路复用，FR-SCH-21/22/24）。"""
    embedder = get_embedder()
    results = await schema_meta_service.search_schema(
        db, embedder, body.query, body.datasource_id, body.top_k
    )
    return ok(results)
