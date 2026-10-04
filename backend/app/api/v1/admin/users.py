"""用户与角色管理路由（R-AD 专属，§2.2 权限矩阵）。"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles
from app.core.errors import ok
from app.domain.schemas import UserCreate, UserPatch
from app.infra.db import get_session
from app.infra.models import User
from app.services import user_service

router = APIRouter(prefix="/admin/users", tags=["admin:users"])

# 仅系统管理员可管理用户与角色
ad_only = require_roles("R-AD")


def _user_payload(user: User) -> dict:
    """用户对象 → 响应字典（含角色与数据范围，绝不含密码字段）。"""
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "status": user.status,
        "must_change_password": user.must_change_password,
        "roles": user.role_codes,
        "scopes": [
            {"scope_type": s.scope_type, "scope_value": s.scope_value} for s in user.scopes
        ],
    }


@router.get("")
async def list_users(
    _: User = Depends(ad_only), db: AsyncSession = Depends(get_session)
):
    users = await user_service.list_users(db)
    return ok([_user_payload(u) for u in users])


@router.post("", status_code=201)
async def create_user(
    body: UserCreate,
    operator: User = Depends(ad_only),
    db: AsyncSession = Depends(get_session),
):
    user = await user_service.create_user(db, body, operator)
    return ok(_user_payload(user))


@router.patch("/{user_id}")
async def update_user(
    user_id: int,
    body: UserPatch,
    operator: User = Depends(ad_only),
    db: AsyncSession = Depends(get_session),
):
    user = await user_service.update_user(db, user_id, body, operator)
    return ok(_user_payload(user))
