"""行级权限改写器（FR-SEC-11）：把策略强制注入执行 SQL 的 WHERE。

设计（§3.6）：
1. 取用户角色在目标数据源上生效的 row_policy；
2. 用 sqlglot 把策略片段以 AND 追加到引用了对应表的 SELECT 上；
3. 注入后必须重新过 sql_guard 全量校验，防止改写引入非法结构；
4. 用户无任何可见策略的表被查询 → 直接判无权限（FR-SEC-14：统一提示不泄露存在性）。
"""

import sqlglot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlglot import exp

from app.core.errors import AppError
from app.infra.models import RowPolicy, TableMeta, User


async def load_user_policies(
    db: AsyncSession, user: User, datasource_id: int
) -> dict[int, list[str]]:
    """返回 {table_meta_id: [过滤片段,...]}：用户角色匹配且启用的策略。"""
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
    result: dict[int, list[str]] = {}
    for p in policies:
        applicable = set(p.apply_to_role_ids or []) & role_codes
        if applicable:
            result.setdefault(p.table_meta_id, []).append(p.filter_template)
    return result


async def rewrite_row_permissions(
    db: AsyncSession,
    user: User,
    datasource_id: int,
    sql: str,
    dialect: str = "postgres",
) -> str:
    """注入行级权限条件并返回改写后的 SQL。

    无匹配策略 → 原样返回（表级可见性由白名单与管理员全量视图语义决定，FR-SEC-12）。
    """
    policies = await load_user_policies(db, user, datasource_id)
    if not policies:
        return sql

    # table_meta_id → 物理表名映射（AST 中使用表名）
    table_ids = list(policies.keys())
    id_to_name = {
        t.id: t.table_name.lower()
        for t in (
            await db.execute(select(TableMeta).where(TableMeta.id.in_(table_ids)))
        ).scalars()
    }
    name_filters: dict[str, list[str]] = {}
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
            for fragment in fragments:
                cond = sqlglot.parse_one(f"SELECT 1 WHERE {fragment}", dialect=dialect).args.get("where")
                if cond is None:
                    continue
                predicate = cond.this
                existing = select_expr.args.get("where")
                select_expr.where(
                    predicate if existing is None else existing.this.and_(predicate),
                    append=False,
                )
    return ast.sql(dialect=dialect)
