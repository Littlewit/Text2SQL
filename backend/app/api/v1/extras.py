"""T4 + M2-T1 路由：收藏 / 分享 / 导出 / 建议追问 / 反馈 / Few-shot 样例库 / 未覆盖问题。

（FR-HIS-04~07、FR-VIS-20、FR-UI-04/08、FR-ADM-04/08）
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.core.errors import AppError, ok
from app.infra.db import get_session
from app.infra.models import Conversation, QueryHistory, User
from app.llm.embedding import get_embedder
from app.services import export_service, favorite_service, feedback_service, fewshot_service, ops_service, share_service

router = APIRouter()

da_or_ad = require_roles("R-DA", "R-AD")


# ==================== 收藏（FR-HIS-04/05） ====================
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
    """执行收藏（FR-HIS-05）：相对时间按当前日期重算——复用问题原文走主链路。"""
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


# ==================== 分享（FR-HIS-06/07） ====================
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
    """打开分享：返回分享内容；接收方以自身权限重新执行（§3.5）。"""
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


# ==================== 导出（FR-VIS-20/23/24） ====================
@router.post("/query/{query_id}/export")
async def export_query(
    query_id: int,
    confirmed: bool = Query(default=False, description="FR-VIS-24：行数超限时需显式确认"),
    format: str = Query(default="xlsx", pattern="^(xlsx)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """导出 Excel：数据已在查询链路服务端脱敏（FR-SEC-22），导出记录审计（FR-VIS-23）。

    行数超过 export.max_rows 时需 confirmed=true（FR-VIS-24）。
    """
    history = await db.get(QueryHistory, query_id)
    if history is None or history.user_id != user.id:
        raise AppError(40400, "查询记录不存在", 404)
    content = await export_service.export_query_excel(db, history, user.id, confirmed)
    filename = f"query_{query_id}_{datetime.now():%Y%m%d%H%M%S}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/query/{query_id}/export/pdf")
async def export_query_pdf(
    query_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """PDF 导出（FR-VIS-21）：由前端浏览器打印生成，服务端记录审计。

    （设计：FR-VIS-21 的 PDF 走前端打印通道；服务端负责审计留痕，
    数据本身来自已脱敏的结果缓存/样例，无明文敏感值外泄。）
    """
    from app.services import audit_service

    h = await db.get(QueryHistory, query_id)
    if h is None or h.user_id != user.id:
        raise AppError(40400, "查询记录不存在", 404)
    await audit_service.record(
        db, user_id=user.id, action="export.pdf",
        object_type="query_history", object_id=str(query_id),
    )
    await db.commit()
    return ok({"audit": True})


@router.get("/history/{query_id}")
async def history_detail(
    query_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """历史详情（FR-HIS-01）：SQL/解释/假设/召回明细，仅本人可见。"""
    h = await db.get(QueryHistory, query_id)
    if h is None or h.user_id != user.id:
        raise AppError(40400, "查询记录不存在", 404)
    return ok({
        "id": h.id, "question": h.question, "intent": h.intent,
        "exec_status": h.exec_status, "row_count": h.row_count,
        "generated_sql": h.generated_sql, "explain_text": h.explain_text,
        "assumptions": h.assumptions, "validate_result": h.validate_result,
        "recalled_schema": h.recalled_schema,
        "prompt_template_version": h.prompt_template_version,
        "retry_count": h.retry_count, "duration_ms": h.duration_ms,
        "chart_config": h.chart_config, "result_sample": h.result_sample,
    })


# ==================== 图表一键切换（FR-VIS-03/04，M2-T4） ====================
class ChartSwitchRequest(BaseModel):
    chart_type: str = Field(pattern="^(line|bar|pie|table)$")


@router.post("/query/{query_id}/chart")
async def switch_chart(
    query_id: int,
    body: ChartSwitchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """图表一键切换（FR-VIS-03/04）：复用缓存/样例数据重建 option，零请求重查。"""
    from app.core.result_cache import get as cache_get
    from app.services.visualization.recommender import build_chart_option

    cached = cache_get(query_id)
    if cached is not None:
        columns, rows = cached["columns"], cached["rows"]
        source = "cache"
    else:
        h = await db.get(QueryHistory, query_id)
        if h is None or h.user_id != user.id or h.exec_status != "success":
            raise AppError(40400, "查询记录不存在或未成功", 404)
        sample = h.result_sample or {}
        columns, rows = sample.get("columns", []), sample.get("rows", [])
        source = "history_sample"

    if not rows:
        return ok({"chart_type": "empty", "reason": "无数据可绘制", "option": None, "source": source})
    option = build_chart_option(body.chart_type, columns, rows)
    reason = f"已切换为 {body.chart_type}（数据源：{source}，零请求重查）"
    return ok({"chart_type": body.chart_type, "reason": reason, "option": option, "source": source})


# ==================== 建议追问（FR-UI-04） ====================
@router.get("/suggest/followups")
async def suggest_followups(
    query_id: int | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """基于问题与图表类型的规则推荐（NFR-M-03）。"""
    question, chart_type = "", None
    if query_id is not None:
        h = await db.get(QueryHistory, query_id)
        if h is not None and h.user_id == user.id:
            question = h.question or ""
            chart_type = (h.chart_config or {}).get("chart_type")
    return ok({"suggestions": export_service.suggest_followups(question, chart_type)})


# ==================== 用户反馈（FR-UI-08，M2-T1） ====================
class FeedbackCreate(BaseModel):
    rating: str = Field(pattern="^(up|down)$")
    correction_sql: str | None = Field(default=None, max_length=4000)
    comment: str | None = Field(default=None, max_length=1000)


@router.post("/query/{query_id}/feedback", status_code=201)
async def create_feedback(
    query_id: int,
    body: FeedbackCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """对查询结果提交赞踩/纠错；同用户同查询仅一次。"""
    fb = await feedback_service.create_feedback(
        db, user.id, query_id, body.rating, body.correction_sql, body.comment
    )
    return ok({"id": fb.id, "review_status": fb.review_status})


@router.get("/admin/feedbacks")
async def list_pending_feedbacks(
    _: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    """待审核反馈列表（数据管理员处理纠错，R-10 闭环）。"""
    items = await feedback_service.list_pending_feedbacks(db)
    return ok(
        [
            {
                "id": f.id, "query_history_id": f.query_history_id,
                "rating": f.rating, "correction_sql": f.correction_sql,
                "comment": f.comment, "created_at": str(f.created_at),
            }
            for f in items
        ]
    )


@router.post("/admin/feedbacks/{feedback_id}/review")
async def review_feedback(
    feedback_id: int,
    approve: bool = Query(...),
    reviewer: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    """审核反馈：采纳 down+纠错 → 自动生成启用的 Few-shot 样例并向量化。"""
    fb = await feedback_service.review_feedback(db, feedback_id, reviewer, approve)
    return ok({"id": fb.id, "review_status": fb.review_status, "sample_id": fb.sample_id})


# ==================== Few-shot 样例库（FR-ADM-04，M2-T1） ====================
class FewShotCreate(BaseModel):
    datasource_id: int | None = None
    question: str = Field(min_length=1, max_length=1000)
    sql_text: str = Field(min_length=1, max_length=4000)
    intent: str | None = Field(default=None, max_length=32)
    explanation: str | None = None


class FewShotPatch(BaseModel):
    question: str | None = Field(default=None, max_length=1000)
    sql_text: str | None = Field(default=None, max_length=4000)
    intent: str | None = Field(default=None, max_length=32)
    explanation: str | None = None
    status: int | None = Field(default=None, ge=0, le=2)


def _fs_payload(fs) -> dict:
    return {
        "id": fs.id, "datasource_id": fs.datasource_id, "question": fs.question,
        "sql_text": fs.sql_text, "intent": fs.intent, "explanation": fs.explanation,
        "status": fs.status, "hit_count": fs.hit_count,
    }


@router.get("/admin/few-shots")
async def list_few_shots(
    datasource_id: int | None = Query(default=None),
    status: int | None = Query(default=None),
    _: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    items = await fewshot_service.list_few_shots(db, datasource_id, status)
    return ok([_fs_payload(f) for f in items])


@router.post("/admin/few-shots", status_code=201)
async def create_few_shot(
    body: FewShotCreate,
    operator: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    fs = await fewshot_service.create_few_shot(db, get_embedder(), body, operator.id)
    return ok(_fs_payload(fs))


@router.post("/admin/few-shots/{fs_id}/review")
async def review_few_shot(
    fs_id: int,
    approve: bool = Query(...),
    operator: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    fs = await fewshot_service.review_few_shot(db, get_embedder(), fs_id, approve, operator.id)
    return ok(_fs_payload(fs))


@router.patch("/admin/few-shots/{fs_id}")
async def update_few_shot(
    fs_id: int,
    body: FewShotPatch,
    operator: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    fs = await fewshot_service.update_few_shot(
        db, get_embedder(), fs_id, body.model_dump(), operator.id
    )
    return ok(_fs_payload(fs))


@router.delete("/admin/few-shots/{fs_id}")
async def delete_few_shot(
    fs_id: int,
    operator: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    await fewshot_service.delete_few_shot(db, fs_id, operator.id)
    return ok({"deleted": True})


# ==================== 未覆盖问题分析（FR-ADM-08，M2-T1） ====================
@router.get("/admin/uncaptured")
async def uncaptured_questions(
    limit: int = Query(default=50, ge=1, le=200),
    _: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    """澄清/拒答/失败问题聚合清单 → 待补充指标与标注待办。"""
    return ok(await ops_service.uncaptured_questions(db, limit))


# ==================== 行级权限策略（FR-SEC-10/12，M2-T3） ====================
class RowPolicyCreate(BaseModel):
    datasource_id: int
    table_meta_id: int
    filter_template: str = Field(min_length=1, max_length=500)
    apply_to_role_ids: list[str]
    combine_mode: str = Field(default="union", pattern="^(union|intersect)$")
    description: str | None = Field(default=None, max_length=256)


@router.get("/admin/row-policies")
async def list_row_policies(
    datasource_id: int | None = Query(default=None),
    _: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    """行级权限策略列表（FR-SEC-10）。"""
    from sqlalchemy import select

    from app.infra.models import RowPolicy as RP

    stmt = select(RP)
    if datasource_id is not None:
        stmt = stmt.where(RP.datasource_id == datasource_id)
    items = (await db.execute(stmt)).scalars().all()
    return ok([
        {"id": p.id, "datasource_id": p.datasource_id, "table_meta_id": p.table_meta_id,
         "filter_template": p.filter_template, "apply_to_role_ids": p.apply_to_role_ids,
         "combine_mode": p.combine_mode, "enabled": p.enabled}
        for p in items
    ])


@router.post("/admin/row-policies", status_code=201)
async def create_row_policy(
    body: RowPolicyCreate,
    operator: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    """创建行级权限策略（FR-SEC-10）；变更即时生效（FR-SEC-13，实时加载）。"""
    from app.infra.models import RowPolicy as RP

    p = RP(
        datasource_id=body.datasource_id,
        table_meta_id=body.table_meta_id,
        filter_template=body.filter_template,
        apply_to_role_ids=body.apply_to_role_ids,
        combine_mode=body.combine_mode,
    )
    db.add(p)
    from app.services import audit_service

    await audit_service.record(
        db, user_id=operator.id, action="admin.row_policy.create",
        object_type="row_policy", object_id=str(p.id),
        detail={"filter": body.filter_template, "roles": body.apply_to_role_ids,
                "combine_mode": body.combine_mode},
    )
    await db.commit()
    return ok({"id": p.id})


@router.delete("/admin/row-policies/{policy_id}")
async def delete_row_policy(
    policy_id: int,
    operator: User = Depends(da_or_ad),
    db: AsyncSession = Depends(get_session),
):
    from app.infra.models import RowPolicy as RP

    p = await db.get(RP, policy_id)
    if p is None:
        raise AppError(40400, "策略不存在", 404)
    await db.delete(p)
    from app.services import audit_service

    await audit_service.record(
        db, user_id=operator.id, action="admin.row_policy.delete",
        object_type="row_policy", object_id=str(policy_id),
    )
    await db.commit()
    return ok({"deleted": True})
