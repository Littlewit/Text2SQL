"""FastAPI 依赖：当前用户解析与角色权限守卫（§2.2 权限矩阵）。"""

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import decode_access_token
from app.infra.db import get_session
from app.infra.models import User
from app.infra.models.config import SysConfig


async def get_current_user(request: Request, db: AsyncSession = Depends(get_session)) -> User:
    """解析 Bearer token 并加载当前用户（含角色）。

    权限在服务端强制（C-04）：即使前端遗漏校验，接口层也会拒绝。
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise AppError(40101, "未登录或凭证缺失", 401)
    token = auth.removeprefix("Bearer ").strip()

    from app.core.config import get_settings

    settings = get_settings()
    user_id = decode_access_token(token, settings.secret_key)

    user = await db.get(User, user_id)
    if user is None or user.status != 1:
        # 停用用户立即失效，不泄露账号是否存在，统一同一提示
        raise AppError(40101, "登录状态无效，请重新登录", 401)
    return user


def require_roles(*codes: str):
    """角色守卫工厂：require_roles("R-AD") 限制仅指定角色可访问（§2.2）。"""

    async def guard(user: User = Depends(get_current_user)) -> User:
        if not set(user.role_codes) & set(codes):
            raise AppError(40300, "您没有执行该操作的权限", 403)
        return user

    return guard


async def get_config_value(db: AsyncSession, key: str, default):
    """读取系统配置值；键不存在返回默认值（sys_config 为参数的唯一来源，FR-ADM-05）。"""
    cfg = await db.get(SysConfig, key)
    return cfg.value if cfg else default
