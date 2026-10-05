"""SQL 安全校验管道（FR-SQL-10~16、FR-SEC-01~05、§3.5）。

纯函数式管道：输入 SQL AST + 上下文，输出结构化结果；校验失败信息可回灌 LLM 重试。
按序执行五阶段：AST 解析 → 语句类型 → 敏感操作 → 对象白名单 → 性能守卫。
"""

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

# 敏感/危险函数黑名单（FR-SQL-13）——可经 sys_config 扩展
BLOCKED_FUNCTIONS = {
    "pg_sleep", "pg_sleep_for", "pg_sleep_until", "pg_read_file", "pg_read_binary_file",
    "pg_ls_dir", "pg_terminate_backend", "pg_cancel_backend", "pg_reload_conf",
    "pg_rotate_logfile", "lo_import", "lo_export", "dblink", "dblink_exec",
    "copy", "pg_logical_slot_get_changes", "pg_create_logical_replication_slot",
}
# 禁止访问的系统 schema（FR-SQL-13）
BLOCKED_SCHEMAS = {"pg_catalog", "information_schema"}


@dataclass
class GuardError:
    """结构化校验错误：错误类型 + 说明 + 修正建议，可原样回灌 LLM（FR-SQL-15）。"""

    stage: str  # parse / statement / sensitive / whitelist / perf
    code: int
    message: str
    hint: str


@dataclass
class GuardResult:
    ok: bool
    ast: exp.Expression | None = None
    errors: list[GuardError] = field(default_factory=list)
    # perf 阶段可能改写 AST（展开 * / 注入 LIMIT），改写后的 SQL 由此返回
    rewritten_sql: str | None = None


@dataclass
class GuardContext:
    """校验上下文：表白名单 → 字段集合（均小写），及行数上限。"""

    allowed_tables: dict[str, set[str]]  # {"orders": {"id", "shop_id", ...}}
    row_limit: int
    dialect: str = "postgres"


def validate(sql: str, ctx: GuardContext) -> tuple[GuardResult, list[GuardError]]:
    """执行完整校验管道，返回 (结果, 可回灌错误列表)。任一阶段失败即终止。"""
    result = GuardResult(ok=False)

    # 阶段 1：AST 解析（FR-SQL-10）——语法错误 100% 拒绝
    try:
        statements = sqlglot.parse(sql, dialect=ctx.dialect)
    except sqlglot.errors.ParseError as e:
        err = GuardError("parse", 42203, f"SQL 语法错误: {e}", "请检查语法后重新生成")
        result.errors.append(err)
        return result, [err]
    if not statements or len(statements) != 1:
        err = GuardError("parse", 40302, "只允许单条查询语句", "只输出一条 SELECT")
        result.errors.append(err)
        return result, [err]
    result.ast = statements[0]

    # 阶段 2：语句类型白名单（FR-SQL-11、FR-SEC-04）
    err = _check_statement_type(result.ast)
    if err:
        result.errors.append(err)
        return result, [err]

    # 阶段 3：敏感操作识别（FR-SQL-13）
    err = _check_sensitive(result.ast)
    if err:
        result.errors.append(err)
        return result, [err]

    # 阶段 4：对象白名单（FR-SQL-12、FR-SEC-15）；CTE 别名视为合法来源
    err = _check_objects(result.ast, ctx)
    if err:
        result.errors.append(err)
        return result, [err]

    # 阶段 5：性能守卫（FR-SQL-14）——展开 * / 校验 JOIN / 注入 LIMIT（可能改写 AST）
    errs = _perf_guard(result.ast, ctx)
    if errs:
        result.errors.extend(errs)
        return result, errs
    result.rewritten_sql = result.ast.sql(dialect=ctx.dialect)
    result.ok = True
    return result, []


def _check_statement_type(ast: exp.Expression) -> GuardError | None:
    """仅允许单条只读 SELECT/WITH；其余一律拒绝。"""
    if isinstance(ast, (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create,
                        exp.Drop, exp.Alter, exp.TruncateTable, exp.Copy, exp.Command,
                        exp.Grant, exp.Set)):
        return GuardError("statement", 40302,
                          f"语句类型 {type(ast).__name__} 不允许，平台只读",
                          "只允许 SELECT/WITH 查询")
    if not isinstance(ast, (exp.Select, exp.Union, exp.Subquery)):
        return GuardError("statement", 40302,
                          f"不支持的语句类型: {type(ast).__name__}", "只允许 SELECT/WITH 查询")
    return None


def _check_sensitive(ast: exp.Expression) -> GuardError | None:
    """危险函数与系统 schema 访问拦截（FR-SQL-13）。"""
    for func in ast.find_all(exp.Anonymous, exp.Func):
        name = (getattr(func, "this", None) or "").lower() if isinstance(func, exp.Anonymous) else \
               func.sql_name().lower().replace("(", "")
        if name in BLOCKED_FUNCTIONS:
            return GuardError("sensitive", 40302, f"函数 {name} 被禁止", "移除该函数后重试")
    for table in ast.find_all(exp.Table):
        if (table.db or "").lower() in BLOCKED_SCHEMAS or (table.catalog or "").lower() in BLOCKED_SCHEMAS:
            return GuardError("sensitive", 40302,
                              f"禁止访问系统对象 {table.name}", "只允许访问白名单业务表")
        if table.name.lower() in BLOCKED_SCHEMAS:
            return GuardError("sensitive", 40302,
                              f"禁止访问系统 schema {table.name}", "只允许访问白名单业务表")
    return None


def _check_objects(ast: exp.Expression, ctx: GuardContext) -> GuardError | None:
    """表/字段白名单：引用的每个对象必须在已纳入范围（FR-SQL-12、FR-SEC-15）。

    CTE 别名（WITH t AS ...）是合法来源，不参与物理表白名单检查。
    """
    allowed_cols: set[str] = set()
    for cols in ctx.allowed_tables.values():
        allowed_cols |= cols
    cte_names = {c.alias_or_name.lower() for c in ast.find_all(exp.CTE)}

    for table in ast.find_all(exp.Table):
        name = table.name.lower()
        if name in cte_names:
            continue
        if name not in ctx.allowed_tables:
            return GuardError("whitelist", 40301,
                              f"表 {name} 不在可查询范围内", "只能使用可用表结构中列出的表")

    aliases = {o.alias_or_name.lower() for o in ast.find_all(exp.Alias)}
    for col in ast.find_all(exp.Column):
        col_name = col.name.lower()
        if col_name == "*":
            continue
        if col.table:
            src = col.table.lower()
            # CTE / 子查询别名的列不做物理白名单校验（列集由其定义决定）
            if src in cte_names or src not in ctx.allowed_tables:
                continue
            if col_name not in ctx.allowed_tables[src]:
                return GuardError("whitelist", 40301,
                                  f"字段 {src}.{col_name} 不存在或不可查询", "检查字段名")
        elif col_name not in allowed_cols and col_name not in aliases and col_name not in _builtin_names():
            return GuardError("whitelist", 40301,
                              f"字段 {col_name} 不在可查询字段中", "检查字段名或补全表前缀")
    return None


def _builtin_names() -> set[str]:
    """sqlglot 内部产生的列名（窗口/聚合别名等）与常见伪列。"""
    return {"*", "row_number", "rank", "dense_rank", "lag", "lead", "ntile"}


def _perf_guard(ast: exp.Expression, ctx: GuardContext) -> list[GuardError]:
    """性能守卫（FR-SQL-14）：原地改写 AST。

    1. SELECT * 自动展开为白名单列；
    2. 多表 JOIN 必须带 ON 条件（拒绝笛卡尔积）；
    3. 强制 LIMIT ≤ 行数上限（已有时取较小值）。
    """
    errors: list[GuardError] = []

    # 1. 展开 SELECT *（FR-SQL-14：禁止 *，自动展开为白名单列）
    for select_expr in ast.find_all(exp.Select):
        stars = [e for e in select_expr.expressions if isinstance(e, exp.Star)]
        if not stars:
            continue
        froms = list(select_expr.find_all(exp.Table))
        if len(froms) != 1:
            errors.append(GuardError("perf", 42203,
                                     "SELECT * 无法唯一确定来源表，请显式列出字段",
                                     "显式写出所需字段"))
            continue
        table_name = froms[0].name.lower()
        cols = sorted(ctx.allowed_tables.get(table_name, set()))
        if not cols:
            errors.append(GuardError("perf", 42203,
                                     f"表 {table_name} 无可展开字段", "显式写出所需字段"))
            continue
        # 用显式列替换整个投影列表（按白名单字典序，保证确定性行为）
        select_expr.set(
            "expressions",
            [exp.column(c, table=froms[0].alias_or_name) for c in cols],
        )

    # 2. JOIN 必须有关联条件（FR-SQL-14：拒绝笛卡尔积）
    for join in ast.find_all(exp.Join):
        if join.args.get("on") is None and join.args.get("using") is None:
            errors.append(GuardError("perf", 42203,
                                     "JOIN 缺少关联条件（笛卡尔积被拒绝）", "补充 ON 关联条件"))

    # 3. 强制 LIMIT（FR-SQL-14、FR-SQL-20）：超上限取上限；缺失则注入
    limit = ast.args.get("limit")
    if limit is None:
        ast.set("limit", exp.Limit(expression=exp.Literal.number(str(ctx.row_limit))))
    else:
        try:
            current = int(limit.expression.this)
        except (AttributeError, ValueError):
            current = ctx.row_limit
        if current > ctx.row_limit:
            ast.set("limit", exp.Limit(expression=exp.Literal.number(str(ctx.row_limit))))

    return errors
