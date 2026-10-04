"""系统配置路由（R-AD，FR-ADM-05）。"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles
from app.core.errors import ok
from app.domain.schemas import ConfigUpsert
from app.infra.db import get_session
from app.infra.models import User
from app.services import config_service

router = APIRouter(prefix="/admin/configs", tags=["admin:configs"])

ad_only = require_roles("R-AD")


@router.get("")
async def list_configs(_: User = Depends(ad_only), db: AsyncSession = Depends(get_session)):
    items = await config_service.list_configs(db)
    return ok(
        [
            {
                "key": c.key,
                "value": c.value,
                "description": c.description,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in items
        ]
    )


@router.patch("/{key}")
async def upsert_config(
    key: str,
    body: ConfigUpsert,
    operator: User = Depends(ad_only),
    db: AsyncSession = Depends(get_session),
):
    cfg = await config_service.upsert_config(db, key, body.value, body.description, operator.id)
    return ok({"key": cfg.key, "value": cfg.value, "description": cfg.description})
