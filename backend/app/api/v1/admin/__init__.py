"""管理后台路由集合（/admin/*，导航与业务前台分离，UX-07）。"""

from fastapi import APIRouter

from app.api.v1.admin import audit, configs, datasources, users

admin_router = APIRouter()
admin_router.include_router(users.router)
admin_router.include_router(datasources.router)
admin_router.include_router(configs.router)
admin_router.include_router(audit.router)
