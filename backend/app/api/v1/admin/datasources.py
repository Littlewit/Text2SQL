"""数据源管理路由（R-DA/R-AD，§2.2）。"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles
from app.core.errors import ok
from app.domain.schemas import DataSourceCreate
from app.infra.db import get_session
from app.infra.models import Datasource, User
from app.services import datasource_service

router = APIRouter(prefix="/admin/datasources", tags=["admin:datasources"])

da_or_ad = require_roles("R-DA", "R-AD")


def _ds_payload(ds: Datasource) -> dict:
    """数据源 → 响应字典；绝不返回 credential 字段（KEY-02：界面不回显明文）。"""
    return {
        "id": ds.id,
        "name": ds.name,
        "db_type": ds.db_type,
        "host": ds.host,
        "port": ds.port,
        "db_name": ds.db_name,
        "readonly_user": ds.readonly_user,
        "status": ds.status,
    }


@router.get("")
async def list_datasources(
    _: User = Depends(da_or_ad), db: AsyncSession = Depends(get_session)
):
    items = await datasource_service.list_datasources(db)
    return ok([_ds_payload(d) for d in items])


@router.post("", status_code=201)
async def create_datasource(
    body: DataSourceCreate,
    operator: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    ds = await datasource_service.create_datasource(db, body, operator)
    return ok(_ds_payload(ds))


@router.post("/{ds_id}/test")
async def test_connection(
    ds_id: int,
    _: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    """连通性测试：真实建立只读连接。"""
    return ok(await datasource_service.test_connection(db, ds_id))
