"""API v1 路由集合。

路由层只做参数校验与编排，业务逻辑在 services 层（§2.3 分层约束）。
"""

from fastapi import APIRouter

from app.api.v1 import auth, health
from app.api.v1.admin import admin_router

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router)
api_router.include_router(admin_router)
