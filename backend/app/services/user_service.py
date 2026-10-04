"""用户与角色管理服务（FR-ADM-01）。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import hash_password
from app.infra.models import DataScope, Role, User
from app.services import audit_service

BUILTIN_ROLE_CODES = ["R-BIZ", "R-DA", "R-AD", "R-AU", "R-DEV"]


async def list_users(db: AsyncSession) -> list[User]:
    """用户列表（含角色与数据范围）。"""
    return list((await db.execute(select(User))).scalars())


async def create_user(db: AsyncSession, data, operator: User) -> User:
    """创建用户并绑定角色与数据范围；用户名唯一。"""
    exists = (
        await db.execute(select(User).where(User.username == data.username))
    ).scalar_one_or_none()
    if exists:
        raise AppError(40002, "用户名已存在", 409)

    roles = await _resolve_roles(db, data.roles)
    user = User(
        username=data.username,
        display_name=data.display_name,
        password_hash=hash_password(data.password),
        roles=roles,
        scopes=[DataScope(scope_type=s.scope_type, scope_value=s.scope_value) for s in data.scopes],
    )
    db.add(user)
    await db.flush()
    await audit_service.record(
        db, user_id=operator.id, action="admin.user.create",
        object_type="user", object_id=str(user.id),
        detail={"username": user.username, "roles": data.roles},  # 不记录密码
    )
    await db.commit()
    return user


async def update_user(db: AsyncSession, user_id: int, data, operator: User) -> User:
    """更新用户基础信息/状态/密码/角色/数据范围；停用即时生效（登录与 token 校验均检查）。"""
    user = await db.get(User, user_id)
    if user is None:
        raise AppError(40400, "用户不存在", 404)

    if data.display_name is not None:
        user.display_name = data.display_name
    if data.status is not None:
        user.status = data.status
    if data.password is not None:
        user.password_hash = hash_password(data.password)
        user.must_change_password = False  # 管理员重置密码后仍建议强制改密，T1 简化处理
    if data.roles is not None:
        user.roles = await _resolve_roles(db, data.roles)
    if data.scopes is not None:
        user.scopes = [
            DataScope(scope_type=s.scope_type, scope_value=s.scope_value) for s in data.scopes
        ]

    await audit_service.record(
        db, user_id=operator.id, action="admin.user.update",
        object_type="user", object_id=str(user_id),
        detail={"fields": data.model_dump(exclude_none=True, exclude={"password"})},
    )
    await db.commit()
    return user


async def _resolve_roles(db: AsyncSession, codes: list[str]) -> list[Role]:
    """把角色编码解析为 Role 实体；未知编码直接拒绝，避免静默降权。"""
    if not codes:
        return []
    roles = list((await db.execute(select(Role).where(Role.code.in_(codes)))).scalars())
    found = {r.code for r in roles}
    missing = set(codes) - found
    if missing:
        raise AppError(40003, f"未知角色: {', '.join(sorted(missing))}", 400)
    return roles
