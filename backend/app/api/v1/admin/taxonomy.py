"""指标 / 同义词 / 枚举字典 / JOIN 路径维护路由（R-DA/R-AD，FR-SCH-11~14）。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles
from app.core.errors import ok
from app.domain.schemas_meta import (
    EnumDictUpsert,
    JoinPathCreate,
    MetricCreate,
    MetricPatch,
    SynonymCreate,
)
from app.infra.db import get_session
from app.infra.models import User
from app.llm.embedding import get_embedder
from app.services import taxonomy_service

router = APIRouter(prefix="/admin", tags=["admin:taxonomy"])

da_or_ad = require_roles("R-DA", "R-AD")


def _metric_payload(m) -> dict:
    return {
        "id": m.id, "datasource_id": m.datasource_id, "name": m.name, "code": m.code,
        "description": m.description, "formula": m.formula, "agg_type": m.agg_type,
        "default_time_column": m.default_time_column, "unit": m.unit, "status": m.status,
    }


# --- 指标 ---
@router.get("/metrics")
async def list_metrics(_: User = Depends(da_or_ad), db: AsyncSession = Depends(get_session)):
    return ok([_metric_payload(m) for m in await taxonomy_service.list_metrics(db)])


@router.post("/metrics", status_code=201)
async def create_metric(
    body: MetricCreate,
    operator: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    m = await taxonomy_service.create_metric(db, get_embedder(), body, operator.id)
    return ok(_metric_payload(m))


@router.patch("/metrics/{metric_id}")
async def update_metric(
    metric_id: int,
    body: MetricPatch,
    operator: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    m = await taxonomy_service.update_metric(
        db, get_embedder(), metric_id, body.model_dump(), operator.id
    )
    return ok(_metric_payload(m))


# --- 同义词 ---
@router.get("/synonyms")
async def list_synonyms(
    datasource_id: int | None = Query(default=None),
    _: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    items = await taxonomy_service.list_synonyms(db, datasource_id)
    return ok(
        [
            {"id": s.id, "term": s.term, "target_type": s.target_type,
             "target_id": s.target_id, "datasource_id": s.datasource_id}
            for s in items
        ]
    )


@router.post("/synonyms", status_code=201)
async def create_synonym(
    body: SynonymCreate,
    operator: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    s = await taxonomy_service.create_synonym(db, get_embedder(), body, operator.id)
    return ok({"id": s.id, "term": s.term, "target_type": s.target_type, "target_id": s.target_id})


@router.delete("/synonyms/{synonym_id}")
async def delete_synonym(
    synonym_id: int,
    operator: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    await taxonomy_service.delete_synonym(db, synonym_id, operator.id)
    return ok({"deleted": True})


# --- 枚举字典 ---
@router.get("/enum-dicts")
async def list_enum_dicts(
    column_meta_id: int | None = Query(default=None),
    _: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    items = await taxonomy_service.list_enum_dicts(db, column_meta_id)
    return ok(
        [
            {"id": e.id, "column_meta_id": e.column_meta_id,
             "raw_value": e.raw_value, "display_name": e.display_name}
            for e in items
        ]
    )


@router.put("/enum-dicts")
async def upsert_enum_dict(
    body: EnumDictUpsert,
    operator: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    e = await taxonomy_service.upsert_enum_dict(db, body, operator.id)
    return ok({"id": e.id, "raw_value": e.raw_value, "display_name": e.display_name})


# --- JOIN 路径 ---
@router.get("/join-paths")
async def list_join_paths(
    datasource_id: int | None = Query(default=None),
    _: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    items = await taxonomy_service.list_join_paths(db, datasource_id)
    return ok(
        [
            {"id": j.id, "datasource_id": j.datasource_id,
             "left_table_id": j.left_table_id, "right_table_id": j.right_table_id,
             "left_column": j.left_column, "right_column": j.right_column,
             "join_type": j.join_type, "description": j.description}
            for j in items
        ]
    )


@router.post("/join-paths", status_code=201)
async def create_join_path(
    body: JoinPathCreate,
    operator: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    j = await taxonomy_service.create_join_path(db, body, operator.id)
    return ok({"id": j.id})
