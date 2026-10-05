"""收藏服务（FR-HIS-04/05）：收藏、重执行（动态参数天然支持）。"""


from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.infra.models import Favorite, QueryHistory
from app.services import audit_service


async def list_favorites(db: AsyncSession, user_id: int) -> list[Favorite]:
    return list(
        (await db.execute(select(Favorite).where(Favorite.user_id == user_id).order_by(Favorite.id.desc()))).scalars()
    )


async def create_favorite(
    db: AsyncSession, user_id: int, name: str, question: str,
    datasource_id: int, params: dict | None, note: str | None, group_name: str | None,
    query_history_id: int | None = None, operator_id: int | None = None,
) -> Favorite:
    """从历史查询或手输创建收藏。dynamic_time=true 时重执行按当前日期重算（FR-HIS-05）。"""
    fav = Favorite(
        user_id=user_id, name=name, question=question, datasource_id=datasource_id,
        params=params or {"dynamic_time": True}, note=note, group_name=group_name,
    )
    db.add(fav)
    await db.flush()
    await audit_service.record(
        db, user_id=operator_id or user_id, action="favorite.create",
        object_type="favorite", object_id=str(fav.id), detail={"name": name},
    )
    await db.commit()
    return fav


async def update_favorite(db: AsyncSession, user_id: int, fav_id: int, fields: dict) -> Favorite:
    fav = await _get_own(db, user_id, fav_id)
    for k in ("name", "note", "group_name", "params"):
        if k in fields and fields[k] is not None:
            setattr(fav, k, fields[k])
    await db.commit()
    return fav


async def delete_favorite(db: AsyncSession, user_id: int, fav_id: int) -> None:
    fav = await _get_own(db, user_id, fav_id)
    await db.delete(fav)
    await audit_service.record(
        db, user_id=user_id, action="favorite.delete", object_type="favorite", object_id=str(fav_id)
    )
    await db.commit()


async def _get_own(db: AsyncSession, user_id: int, fav_id: int) -> Favorite:
    fav = await db.get(Favorite, fav_id)
    if fav is None or fav.user_id != user_id:
        raise AppError(40400, "收藏不存在", 404)
    return fav


def favorite_from_history(history: QueryHistory) -> dict:
    """从历史记录提取收藏默认值（问题原文 + 数据源）。"""
    return {"name": (history.question or "未命名收藏")[:50], "question": history.question}
