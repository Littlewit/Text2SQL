"""T4 路由：收藏 / 分享 / 导出 / 建议追问（FR-HIS-04~07、FR-VIS-20、FR-UI-04）。"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.errors import AppError, ok
from app.infra.db import get_session
from app.infra.models import Conversation, QueryHistory, User
from app.services import export_service, favorite_service, share_service

router = APIRouter(tags=["extras"])


# ---------- 收藏（FR-HIS-04/05）----------
class FavoriteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=1000)
    datasource_id: int
    params: dict | None = None
    note: str | None = Field(default=None, max_length=256)
    group_name: str | None = Field(default=None, max_length=64)
    query_history_id: int | None = None


class FavoritePatch(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    note: str | None = Field(default=None, max_length=256)
    group_name: str | None = Field(default=None, max_length=64)
    params: dict | None = None


def _fav_payload(f) -> dict:
    return {
        "id": f.id, "name": f.name, "question": f.question,
        "datasource_id": f.datasource_id, "params": f.params,
        "note": f.note, "group_name": f.group_name,
        "created_at": str(f.created_at),
    }


@router.get("/favorites")
async def list_favorites(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    items = await favorite_service.list_favorites(db, user.id)
    return ok([_fav_payload(f) for f in items])


@router.post("/favorites", status_code=201)
async def create_favorite(
    body: FavoriteCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    fav = await favorite_service.create_favorite(
        db, user.id, body.name, body.question, body.datasource_id,
        body.params, body.note, body.group_name, body.query_history_id,
    )
    return ok(_fav_payload(fav))


@router.patch("/favorites/{fav_id}")
async def update_favorite(
    fav_id: int, body: FavoritePatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    fav = await favorite_service.update_favorite(db, user.id, fav_id, body.model_dump())
    return ok(_fav_payload(fav))


@router.delete("/favorites/{fav_id}")
async def delete_favorite(
    fav_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)
):
    await favorite_service.delete_favorite(db, user.id, fav_id)
    return ok({"deleted": True})


@router.post("/favorites/{fav_id}/run")
async def run_favorite(
    fav_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """执行收藏（FR-HIS-05）：相对时间按当前日期重算——直接复用问题原文走主链路。"""
    fav = await favorite_service._get_own(db, user.id, fav_id)  # noqa: SLF001 —— 同包服务层复用
    events: list[tuple[str, dict]] = []

    async def emit(t, p):
        events.append((t, p))

    from app.llm.client import get_llm
    from app.services.query_service import run_query

    conv_id = fav.conversation_id
    if conv_id is None:
        conv = Conversation(user_id=user.id, title=f"收藏：{fav.name}")
        db.add(conv)
        await db.commit()
        conv_id = conv.id

    history = await run_query(db, user, get_llm(), fav.question, conv_id, fav.datasource_id, emit)
    result = next((p for t, p in reversed(events) if t == "result"), None)
    chart = next((p for t, p in reversed(events) if t == "chart"), None)
    return ok({"query_id": history.id, "exec_status": history.exec_status,
               "result": result, "chart": chart})


# ---------- 分享（FR-HIS-06/07）----------
class ShareCreate(BaseModel):
    datasource_id: int
    question: str | None = Field(default=None, max_length=1000)
    query_history_id: int | None = None


def _share_payload(s) -> dict:
    return {
        "id": s.id, "token": s.token, "question": s.question,
        "share_type": s.share_type, "expire_at": str(s.expire_at), "revoked": s.revoked,
        "url": f"/shares/{s.token}",
    }


@router.post("/shares", status_code=201)
async def create_share(
    body: ShareCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if body.question is None and body.query_history_id is None:
        raise AppError(40001, "question 与 query_history_id 至少提供一个", 400)
    share = await share_service.create_share(
        db, user.id, body.question or "", body.datasource_id,
        query_history_id=body.query_history_id,
    )
    return ok(_share_payload(share))


@router.get("/shares/{token}")
async def open_share(
    token: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """打开分享：返回分享内容；接收方以自身权限重新执行（前端据此发起查询）。"""
    share = await share_service.get_share_by_token(db, token, user.id)
    return ok({"question": share.question, "datasource_id": share.datasource_id,
               "owner_id": share.owner_id})


@router.get("/my-shares")
async def list_my_shares(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    items = await share_service.list_my_shares(db, user.id)
    return ok([_share_payload(s) for s in items])


@router.delete("/shares/{share_id}")
async def revoke_share(
    share_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    is_admin = "R-AD" in user.role_codes
    await share_service.revoke_share(db, share_id, user.id, is_admin)
    return ok({"revoked": True})


# ---------- 导出（FR-VIS-20/23）----------
@router.post("/query/{query_id}/export")
async def export_query(
    query_id: int,
    format: str = Query(default="xlsx", pattern="^(xlsx)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """导出 Excel：数据已在查询链路服务端脱敏（FR-SEC-22），导出记录审计（FR-VIS-23）。"""
    history = await db.get(QueryHistory, query_id)
    if history is None or history.user_id != user.id:
        raise AppError(40400, "查询记录不存在", 404)
    content = await export_service.export_query_excel(db, history, user.id)
    filename = f"query_{query_id}_{datetime.now():%Y%m%d%H%M%S}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------- 建议追问（FR-UI-04）----------
@router.get("/suggest/followups")
async def suggest_followups(
    query_id: int | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """基于问题与图表类型的规则推荐（规则引擎，NFR-M-03）。"""
    question, chart_type = "", None
    if query_id is not None:
        h = await db.get(QueryHistory, query_id)
        if h is not None and h.user_id == user.id:
            question = h.question or ""
            chart_type = (h.chart_config or {}).get("chart_type")
    return ok({"suggestions": export_service.suggest_followups(question, chart_type)})
