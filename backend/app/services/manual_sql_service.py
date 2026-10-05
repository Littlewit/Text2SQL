"""手工编辑 SQL 执行服务（FR-SQL-32）。

与生成链路**同权同责**：完整 sql_guard 校验 → 行级权限改写 → 只读执行 → 脱敏。
用户输入的 SQL 是不可信输入，任何校验环节不可跳过（FR-SEC-05）。
"""

import datetime as _dt
import decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_config_value
from app.core.errors import AppError
from app.infra.models import Datasource, User
from app.services import audit_service, masking
from app.services.executor.runner import execute_readonly
from app.services.permission.rewriter import rewrite_row_permissions
from app.services.query_service import _column_meta_map, _guard_context
from app.services.sql_guard import validate
from app.services.visualization.recommender import recommend_chart


async def execute_manual_sql(
    db: AsyncSession, user: User, datasource_id: int, sql: str
) -> dict:
    """执行用户手工编辑的 SQL（须经完整校验与权限改写）。"""
    ds = await db.get(Datasource, datasource_id)
    if ds is None or ds.status != 1:
        raise AppError(40400, "数据源不存在或已停用", 404)

    row_limit = await get_config_value(db, "query.row_limit", 1000)
    timeout_s = await get_config_value(db, "query.timeout_s", 30)

    # 1) AST 安全校验（与生成链路同一管道，FR-SQL-32 同权同责）
    guard_ctx = await _guard_context(db, datasource_id, row_limit, user)
    guard, errs = validate(sql, guard_ctx)
    if not guard.ok:
        raise AppError(
            40302,
            "；".join(f"{e.message}（{e.hint}）" for e in errs) or "SQL 校验未通过",
            422,
        )
    sql_text = guard.rewritten_sql or sql

    # 2) 行级权限改写 + 复验（FR-SEC-11）
    sql_text = await rewrite_row_permissions(db, user, datasource_id, sql_text)
    re_guard, re_errs = validate(sql_text, guard_ctx)
    if not re_guard.ok:
        raise AppError(40300, "该查询触及数据权限边界，已拦截", 403)
    sql_text = re_guard.rewritten_sql or sql_text

    # 3) 只读执行（FR-SEC-30）
    result = await execute_readonly(ds, sql_text, row_limit, timeout_s)

    # 4) 脱敏（FR-SEC-22）+ 反推风险分析（FR-SEC-23）
    col_meta = await _column_meta_map(db, datasource_id, result.columns)
    col_infos = [masking.ColumnMaskInfo(name=c, is_sensitive=col_meta.get(c.lower(), False))
                 for c in result.columns]
    _, masked_rows = masking.mask_rows(col_infos, result.rows)
    sensitive_cols = {n.lower() for n, s in col_meta.items() if s}
    risk_warnings = masking.mask_risk_warnings(sql_text, sensitive_cols)

    def _jsonable(v):
        if isinstance(v, decimal.Decimal):
            return float(v)
        if isinstance(v, _dt.datetime | _dt.date):
            return v.isoformat()
        return v

    masked_rows = [[_jsonable(v) for v in row] for row in masked_rows]
    chart = recommend_chart(result.columns, masked_rows, "")

    await audit_service.record(
        db, user_id=user.id, action="query.manual_sql",
        detail={"sql": sql_text[:500], "rows": result.row_count},
    )
    await db.commit()
    return {
        "sql": sql_text,
        "warnings": guard.warnings + risk_warnings,
        "columns": result.columns,
        "rows": masked_rows,
        "row_count": result.row_count,
        "truncated": result.truncated,
        "duration_ms": result.duration_ms,
        "chart": chart,
    }
