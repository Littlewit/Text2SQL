"""健康检查探针（DEP-05）。

- /healthz：存活探针，进程活着即返回 200；
- /readyz：就绪探针，检查元数据库连通性，不可用返回 503（编排系统据此摘流量）。
"""

import logging

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.core.config import get_settings
from app.infra.db import get_engine

logger = logging.getLogger(__name__)

router = APIRouter()
settings = get_settings()


@router.get("/healthz")
async def healthz() -> dict:
    """存活探针：无外部依赖，永远快速返回。"""
    return {"status": "ok", "app": settings.app_name}


@router.get("/readyz")
async def readyz(response: Response) -> dict:
    """就绪探针：依赖元数据库可达。失败时返回 503 而非 500，便于编排区分"未就绪"与"故障"。"""
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "up"}
    except Exception:  # noqa: BLE001 —— 探针必须吞掉异常细节，避免泄露内部结构（§9.1 最小暴露）
        # 技术细节只写日志（NFR-O-02），不进响应体
        logger.exception("readyz database check failed")
        response.status_code = 503
        return {"status": "degraded", "database": "down"}
