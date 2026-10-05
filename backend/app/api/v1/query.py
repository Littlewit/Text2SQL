"""查询路由：SSE 流式（FR-UI-05）+ 同步接口 + 会话管理（FR-UI-06）。"""

import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.errors import AppError, ok
from app.core.rate_limit import check_query_allowed, mark_finished, mark_started
from app.infra.db import get_session
from app.infra.models import Conversation, QueryHistory, User
from app.llm.client import get_llm
from app.services import query_service

router = APIRouter(tags=["query"])


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    conversation_id: int
    datasource_id: int


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=256)


def _collect_emitter(events: list[tuple[str, dict]]):
    """同步接口的事件收集器。"""

    async def emit(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    return emit


@router.post("/query")
async def query(
    body: QueryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """同步查询：返回最终结果（SSE 版本见 /query/stream）。"""
    await check_query_allowed(user.id)
    await mark_started(user.id)
    events: list[tuple[str, dict]] = []

    async def emit(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    try:
        history = await query_service.run_query(
            db, user, get_llm(), body.question, body.conversation_id, body.datasource_id, emit
        )
    finally:
        await mark_finished(user.id)

    # 组装最终响应：取最后一个 result/chart 事件
    result = next((p for t, p in reversed(events) if t == "result"), None)
    chart = next((p for t, p in reversed(events) if t == "chart"), None)
    return ok({
        "query_id": history.id,
        "exec_status": history.exec_status,
        "result": result,
        "chart": chart,
    })


@router.post("/query/stream")
async def query_stream(
    body: QueryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """SSE 流式查询（FR-UI-05）：分阶段实时推送 stage/clarify/sql/result/chart/error/done。"""
    await check_query_allowed(user.id)

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        async def emit(event_type: str, payload: dict) -> None:
            await queue.put((event_type, payload))

        await mark_started(user.id)
        task = None
        try:
            task = asyncio.create_task(
                query_service.run_query(
                    db, user, get_llm(), body.question, body.conversation_id, body.datasource_id, emit
                )
            )
            while True:
                # 任务结束且队列取尽 → 退出（避免 done 后死循环）
                if task.done() and queue.empty():
                    break
                try:
                    event_type, payload = await asyncio.wait_for(queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                yield f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
            # 任务异常在此传播（error/done 事件已推送，客户端可感知失败原因）
            await task
            yield "event: __end__\ndata: {}\n\n"
        finally:
            await mark_finished(user.id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- 会话管理（FR-UI-06）----------

@router.post("/conversations", status_code=201)
async def create_conversation(
    body: ConversationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    conv = Conversation(user_id=user.id, title=body.title)
    db.add(conv)
    await db.commit()
    return ok({"id": conv.id, "title": conv.title})


@router.get("/conversations")
async def list_conversations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    items = (
        (await db.execute(
            select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.updated_at.desc())
        )).scalars().all()
    )
    return ok([{"id": c.id, "title": c.title, "updated_at": str(c.updated_at)} for c in items])


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise AppError(40400, "会话不存在", 404)
    from app.infra.models import Message

    items = (
        (await db.execute(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.seq)
        )).scalars().all()
    )
    return ok([{"role": m.role, "content": m.content, "seq": m.seq} for m in items])


@router.get("/history")
async def list_history(
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """本人查询历史（FR-HIS-01/02：仅本人可见，§2.2）。"""
    from sqlalchemy import func as sa_func

    base = select(QueryHistory).where(
        QueryHistory.user_id == user.id, QueryHistory.is_deleted.is_(False)
    )
    total = (await db.execute(
        select(sa_func.count()).select_from(base.subquery())
    )).scalar_one()
    items = (
        (await db.execute(
            base.order_by(QueryHistory.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )).scalars().all()
    )
    return ok({
        "total": total, "page": page, "page_size": page_size,
        "items": [
            {"id": h.id, "question": h.question, "intent": h.intent,
             "exec_status": h.exec_status, "row_count": h.row_count,
             "duration_ms": h.duration_ms, "created_at": str(h.created_at)}
            for h in items
        ],
    })
