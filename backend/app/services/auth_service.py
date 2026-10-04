"""认证服务：登录 / 登出 / 当前用户（FR-SEC-40）。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import login_guard
from app.core.config import get_settings
from app.core.deps import get_config_value
from app.core.errors import AppError
from app.core.security import create_access_token, verify_password
from app.infra.models import User
from app.services import audit_service


def _client_meta(request) -> tuple[str | None, str | None]:
    """提取客户端 IP 与 UA，供审计记录。"""
    ip = request.client.host if request.client else None
    return ip, request.headers.get("user-agent")


async def login(db: AsyncSession, username: str, password: str, request) -> dict:
    """账号密码登录；失败计数与锁定见 login_guard，全部行为留审计。"""
    ip, ua = _client_meta(request)
    settings = get_settings()
    # 锁定阈值优先取 sys_config（管理员可热调），无配置时回落到环境默认
    threshold = await get_config_value(
        db, "security.login_lockout_threshold", settings.login_lockout_threshold
    )

    login_guard.check_locked(username, threshold)

    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()

    # 用户不存在与密码错误返回同一提示，避免账号枚举（§9.1 最小暴露）
    if user is None or not verify_password(user.password_hash, password):
        login_guard.record_failure(username, threshold)
        await audit_service.record(
            db, user_id=user.id if user else None, action="auth.login",
            detail={"username": username, "result": "failed"}, ip=ip, user_agent=ua,
        )
        await db.commit()
        raise AppError(40102, "用户名或密码错误", 401)

    if user.status != 1:
        raise AppError(40103, "账号已停用，请联系管理员", 403)

    login_guard.record_success(username)
    token = create_access_token(user.id, settings.secret_key, settings.token_expire_minutes)
    await audit_service.record(
        db, user_id=user.id, action="auth.login",
        detail={"username": username, "result": "success"}, ip=ip, user_agent=ua,
    )
    await db.commit()
    return {"token": token, "user": user}


async def logout(db: AsyncSession, user: User, request) -> None:
    """登出：JWT 无状态，服务端仅留审计；令牌吊销列表在 T5 结合 Redis 实现。"""
    ip, ua = _client_meta(request)
    await audit_service.record(db, user_id=user.id, action="auth.logout", ip=ip, user_agent=ua)
    await db.commit()
