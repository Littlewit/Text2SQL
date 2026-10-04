"""认证路由（§6.1 认证组）。"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.errors import ok
from app.domain.schemas import LoginRequest, LoginResponse, UserInfo
from app.infra.db import get_session
from app.infra.models import User
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=None)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_session)):
    """登录：颁发访问令牌。响应包络 data = {token, token_type, user}。"""
    result = await auth_service.login(db, body.username, body.password, request)
    user: User = result["user"]
    return ok(
        LoginResponse(
            token=result["token"],
            user=UserInfo(
                id=user.id,
                username=user.username,
                display_name=user.display_name,
                roles=user.role_codes,
                must_change_password=user.must_change_password,
            ),
        ).model_dump()
    )


@router.post("/logout")
async def logout(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """登出：JWT 无状态，客户端丢弃令牌；服务端记录审计。"""
    await auth_service.logout(db, user, request)
    return ok({"logged_out": True})


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    """当前用户信息与角色（前端据此渲染功能入口）。"""
    return ok(
        UserInfo(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            roles=user.role_codes,
            must_change_password=user.must_change_password,
        ).model_dump()
    )
