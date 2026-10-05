"""导出服务（FR-VIS-20/23/24、M2-T4）：Excel / PDF 审计，复用已脱敏结果。

数据来源优先级：进程内结果缓存（完整脱敏结果，查询后 10 分钟内）→
query_history.result_sample（前 N 行样例）。
导出行数上限（FR-VIS-24）读 sys_config：超限需用户显式确认（confirmed=true），
且导出行为必须留审计（FR-VIS-23）。
"""

import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_config_value
from app.core.errors import AppError
from app.infra.models import QueryHistory
from app.services import audit_service


async def _export_rows(db: AsyncSession, history: QueryHistory) -> list[list]:
    """取导出数据行：优先结果缓存（完整脱敏结果），回退历史样例（DR-02）。"""
    from app.core.result_cache import get as cache_get

    cached = cache_get(history.id)
    if cached is not None:
        return cached["rows"]
    return (history.result_sample or {}).get("rows", [])


async def export_query_excel(
    db: AsyncSession, history: QueryHistory, operator_id: int, confirmed: bool = False
) -> bytes:
    """把查询结果导出为 Excel：数据表 + 元信息（问题/SQL/口径声明）。

    FR-VIS-24：行数超过 export.max_rows（sys_config，默认 1000）时
    需 confirmed=true 显式确认，否则 409 提示行数——防止误操作拉全量。
    """
    if history is None or history.exec_status != "success":
        raise AppError(40400, "仅成功的查询可导出", 404)

    max_rows = await get_config_value(db, "export.max_rows", 1000)
    rows = await _export_rows(db, history)
    if len(rows) > max_rows and not confirmed:
        raise AppError(
            40902,
            f"本次导出共 {len(rows)} 行，超过上限 {max_rows}，请确认后重试",
            409,
        )

    columns: list[str] = (history.result_sample or {}).get("columns", [])
    truncated: bool = (history.result_sample or {}).get("truncated", False)

    wb = Workbook()
    ws = wb.active
    ws.title = "查询结果"

    # 元信息区
    meta_font = Font(bold=True)
    ws.append(["查询问题", history.question])
    ws.append(["生成时间", datetime.now().isoformat(timespec="seconds")])
    ws.append(["口径假设", "；".join((history.assumptions or {}).get("list", [])) or "无"])
    if history.explain_text:
        ws.append(["SQL 解释", history.explain_text])
    ws.append([])

    # 数据表区（列头取自结果样例，行数据来自缓存/样例）
    ws.append(columns)
    for cell in ws[ws.max_row]:
        cell.font = meta_font
    for row in rows:
        ws.append(row)
    if truncated:
        ws.append([])  # type: ignore[arg-type] —— 空行分隔
        ws.append([f"（结果已按行数上限截断，仅含前 {len(rows)} 行）"])

    buf = io.BytesIO()
    wb.save(buf)
    content = buf.getvalue()

    await audit_service.record(
        db, user_id=operator_id, action="export.excel",
        object_type="query_history", object_id=str(history.id),
        detail={"rows": len(rows), "truncated": truncated, "confirmed": confirmed},
    )
    await db.commit()
    return content


def suggest_followups(question: str, chart_type: str | None) -> list[str]:
    """建议追问（FR-UI-04）：基于问题与图表类型的规则推荐。"""
    suggestions: list[str] = ["按月拆分看趋势", "换成表格展示", "导出 Excel"]
    if any(k in question for k in ("哪个", "最高", "最低", "排名", "Top")):
        suggestions.insert(0, "看前 10 名的完整排名")
    if chart_type == "bar":
        suggestions.insert(0, "换成分组柱状图对比")
    if "退货" in question:
        suggestions.insert(0, "只看退货率超过 5% 的")
    return suggestions[:4]
