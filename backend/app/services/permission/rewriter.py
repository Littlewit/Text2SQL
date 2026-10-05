"""行级权限改写器（FR-SEC-11/12）：把策略强制注入执行 SQL 的 WHERE。

设计（§3.6、M2-T3）：
1. 取用户角色在目标数据源上生效的 row_policy；
2. 同表多策略按 combine_mode 叠加：union → OR（并集）、intersect → AND（交集）；
   两种模式同时存在时：OR 块与 AND 块再取 AND（保守语义）；
3. 用 sqlglot 把条件以 AND 追加到引用了对应表的 SELECT 上，注入后必须复验；
4. 策略变更即时生效：每次查询实时加载（FR-SEC-13，无结果缓存前天然成立）。
"""

import sqlglot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlglot import exp

from app.core.errors import AppError
from app.infra.models import RowPolicy, TableMeta, User


async def load_user_policies(
    db: AsyncSession, user: User, datasource_id: int
) -> dict[int, list[tuple[str, str]]]:
    """返回 {table_meta_id: [(过滤片段, combine_mode), ...]}：用户角色匹配且启用的策略。"""
    role_codes = set(user.role_codes)
    policies = (
        (
            await db.execute(
                select(RowPolicy).where(
                    RowPolicy.datasource_id == datasource_id,
                    RowPolicy.enabled.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    result: dict[int, list[tuple[str, str]]] = {}
    for p in policies:
        if set(p.apply_to_role_ids or []) & role_codes:
            result.setdefault(p.table_meta_id, []).append(
                (p.filter_template, p.combine_mode or "union")
            )
    return result


def _combine(fragments: list[tuple[str, str]], dialect: str) -> exp.Expression | None:
    """叠加语义（FR-SEC-12）：同模式内 union=OR / intersect=AND；混合模式取 AND。"""
    parsed = []
    for fragment, mode in fragments:
        cond = sqlglot.parse_one(f"SELECT 1 WHERE {fragment}", dialect=dialect).args.get("where")
        if cond is not None:
            parsed.append((cond.this, mode))
    if not parsed:
        return None

    def _join(items, op: str):
        expr = items[0]
        for nxt in items[1:]:
            expr = expr.and_(nxt) if op == "and" else expr.or_(nxt)
        return expr

    union_parts = [c for c, m in parsed if m == "union"]
    intersect_parts = [c for c, m in parsed if m == "intersect"]
    combined = None
    if union_parts:
        combined = _join(union_parts, "or")
    if intersect_parts:
        and_block = _join(intersect_parts, "and")
        combined = and_block if combined is None else combined.and_(and_block)
    return combined


async def rewrite_row_permissions(
    db: AsyncSession,
    user: User,
    datasource_id: int,
    sql: str,
    dialect: str = "postgres",
) -> str:
    """注入行级权限条件并返回改写后的 SQL。

    无匹配策略 → 原样返回；改写只增不改：已有 WHERE 条件以 AND 保留（FR-SEC-11）。
    """
    policies = await load_user_policies(db, user, datasource_id)
    if not policies:
        return sql

    table_ids = list(policies.keys())
    id_to_name = {
        t.id: t.table_name.lower()
        for t in (
            await db.execute(select(TableMeta).where(TableMeta.id.in_(table_ids)))
        ).scalars()
    }
    name_filters: dict[str, list[tuple[str, str]]] = {}
    for tid, fragments in policies.items():
        name = id_to_name.get(tid)
        if name:
            name_filters.setdefault(name, []).extend(fragments)

    try:
        ast = sqlglot.parse_one(sql, dialect=dialect)
    except sqlglot.errors.ParseError as e:
        # 理论上不应发生（改写前已过校验）；防御性处理
        raise AppError(42203, "SQL 权限改写失败", 422) from e

    for select_expr in ast.find_all(exp.Select):
        for table in select_expr.find_all(exp.Table):
            fragments = name_filters.get(table.name.lower())
            if not fragments:
                continue
            predicate = _combine(fragments, dialect)
            if predicate is None:
                continue
            # sqlglot builder 默认返回副本：必须 copy=False 才能原地修改
            existing = select_expr.args.get("where")
            if existing is None:
                select_expr.where(predicate, append=False, copy=False)
            else:
                select_expr.where(predicate, append=True, copy=False)
    return ast.sql(dialect=dialect)
