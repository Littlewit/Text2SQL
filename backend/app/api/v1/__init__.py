"""API v1 路由集合。

路由层只做参数校验与编排，业务逻辑在 services 层（§2.3 分层约束）。
"""

from fastapi import APIRouter

from app.api.v1 import health

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
