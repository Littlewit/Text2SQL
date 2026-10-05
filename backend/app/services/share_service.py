"""分享服务（FR-HIS-06/07、§3.5）：分享的是「问题 + 配置」，重执行以接收方权限。"""

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.infra.models import QueryHistory, Share, ShareAccess
from app.services import audit_service

# 分享默认有效期（P-37 待定，暂取 7 天）
DEFAULT_EXPIRE_DAYS = 7


async def create_share(
    db: AsyncSession, owner_id: int, question: str, datasource_id: int,
    conversation_id: int | None = None, query_history_id: int | None = None,
) -> Share:
    """创建链接分享：token 用安全随机值不可枚举（SEC-09）；不含结果数据。"""
    if query_history_id is not None:
        hist = await db.get(QueryHistory, query_history_id)
        if hist is None or hist.user_id != owner_id:
            raise AppError(40400, "查询记录不存在", 404)
        question = hist.question
        conversation_id = hist.conversation_id

    share = Share(
        owner_id=owner_id,
        question=question,
        datasource_id=datasource_id,
        conversation_id=conversation_id,
        token=secrets.token_urlsafe(32),
        expire_at=datetime.now(timezone.utc) + timedelta(days=DEFAULT_EXPIRE_DAYS),
    )
    db.add(share)
    await db.flush()
    await audit_service.record(
        db, user_id=owner_id, action="share.create",
        object_type="share", object_id=str(share.id), detail={"question": question[:100]},
    )
    await db.commit()
    return share


async def get_share_by_token(db: AsyncSession, token: str, visitor_id: int) -> Share:
    """打开分享：校验 token/有效期/撤销，记录访问（FR-HIS-07）。

    接收方以自身权限重新执行（§3.5），因此这里只返回分享的问题与数据源。
    """
    share = (
        await db.execute(select(Share).where(Share.token == token))
    ).scalar_one_or_none()
    if share is None:
        raise AppError(40400, "分享不存在或已失效", 404)
    if share.revoked:
        raise AppError(40300, "该分享已被撤销", 403)
    if share.expire_at and share.expire_at < datetime.now(timezone.utc):
        raise AppError(40300, "该分享已过期", 403)

    db.add(ShareAccess(share_id=share.id, user_id=visitor_id))
    await audit_service.record(
        db, user_id=visitor_id, action="share.open",
        object_type="share", object_id=str(share.id),
    )
    await db.commit()
    return share


async def revoke_share(db: AsyncSession, share_id: int, user_id: int, is_admin: bool) -> None:
    """撤销分享：仅创建者或管理员（§6.1 权限）。"""
    share = await db.get(Share, share_id)
    if share is None:
        raise AppError(40400, "分享不存在", 404)
    if share.owner_id != user_id and not is_admin:
        raise AppError(40300, "只能撤销自己创建的分享", 403)
    share.revoked = True
    await audit_service.record(
        db, user_id=user_id, action="share.revoke", object_type="share", object_id=str(share_id)
    )
    await db.commit()


async def list_my_shares(db: AsyncSession, user_id: int) -> list[Share]:
    return list(
        (await db.execute(select(Share).where(Share.owner_id == user_id).order_by(Share.id.desc()))).scalars()
    )
