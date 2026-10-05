"""sql_guard 全阶段单元测试（FR-SQL-10~14、FR-SEC-01~05）。

安全用例要求 100% 拦截（§11.1），覆盖注入变形/多语句/系统表/越权/笛卡尔积/*。
"""

from app.services.sql_guard import GuardContext, validate

CTX = GuardContext(
    allowed_tables={
        "orders": {"id", "shop_id", "order_date", "status", "amount"},
        "shop": {"id", "name", "region", "city"},
    },
    row_limit=1000,
)


def _ok(sql):
    result, errs = validate(sql, CTX)
    return result.ok, errs


def test_valid_select_passes():
    ok, _ = _ok("SELECT shop_id, SUM(amount) FROM orders GROUP BY shop_id")
    assert ok


def test_syntax_error_rejected():
    ok, errs = _ok("SELEC * FROM orders")
    assert not ok and errs[0].stage == "parse"


def test_multi_statement_rejected():
    """多语句注入（FR-SEC-04）。"""
    ok, errs = _ok("SELECT 1; DROP TABLE orders")
    assert not ok and errs[0].code == 40302


def test_write_statements_rejected():
    """写操作全拦截（FR-SQL-11）。"""
    for sql in (
        "DROP TABLE orders",
        "DELETE FROM orders",
        "INSERT INTO orders VALUES (1)",
        "UPDATE orders SET amount = 0",
        "TRUNCATE orders",
        "ALTER TABLE orders ADD COLUMN x INT",
        "CREATE TABLE x (id INT)",
    ):
        result, errs = validate(sql, CTX)
        assert not result.ok, sql
        assert errs[0].code == 40302, sql


def test_commented_injection_rejected():
    """注释绕过变形（AC-06）：注释碎片导致解析失败或多语句 → 拒绝。"""
    result, _ = validate("SELECT * FROM orders; --", CTX)
    assert not result.ok
    result, _ = validate("SELECT id FROM orders WHERE id = 1; DROP TABLE orders; --", CTX)
    assert not result.ok


def test_dangerous_functions_blocked():
    """pg_sleep 类函数拦截（FR-SQL-13）。"""
    for sql in (
        "SELECT pg_sleep(10)",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT dblink('host=x dbname=y', 'SELECT 1')",
    ):
        result, errs = validate(sql, CTX)
        assert not result.ok, sql
        assert errs[0].stage == "sensitive", sql


def test_system_schema_blocked():
    result, errs = validate("SELECT * FROM information_schema.tables", CTX)
    assert not result.ok and errs[0].stage == "sensitive"
    result, errs = validate("SELECT * FROM pg_catalog.pg_tables", CTX)
    assert not result.ok and errs[0].stage == "sensitive"


def test_table_whitelist():
    """越权访问未纳入表（FR-SQL-12）。"""
    ok, errs = _ok("SELECT id FROM secret_table")
    assert not ok and errs[0].stage == "whitelist"


def test_column_whitelist():
    ok, errs = _ok("SELECT internal_flag FROM orders")
    assert not ok and errs[0].stage == "whitelist"


def test_star_expanded():
    """SELECT * 自动展开为白名单列（FR-SQL-14）。"""
    result, errs = validate("SELECT * FROM shop", CTX)
    assert result.ok
    assert "city" in result.rewritten_sql and "name" in result.rewritten_sql
    assert "*" not in result.rewritten_sql


def test_limit_injected():
    """无 LIMIT 自动补行数上限（FR-SQL-20）。"""
    result, errs = validate("SELECT id FROM orders", CTX)
    assert result.ok and "LIMIT 1000" in result.rewritten_sql


def test_limit_capped():
    """超上限的 LIMIT 被压到上限。"""
    result, errs = validate("SELECT id FROM orders LIMIT 999999", CTX)
    assert result.ok and "LIMIT 1000" in result.rewritten_sql


def test_cartesian_join_rejected():
    """无关联条件的 JOIN（笛卡尔积）被拒绝（FR-SQL-14）。"""
    ok, errs = _ok("SELECT o.id FROM orders o JOIN shop s")
    assert not ok and errs[0].stage == "perf"


def test_proper_join_passes():
    ok, _ = _ok("SELECT o.id FROM orders o JOIN shop s ON s.id = o.shop_id")
    assert ok


def test_cte_select_passes():
    """WITH 只读查询允许（FR-SQL-11）。"""
    ok, _ = _ok("WITH t AS (SELECT id FROM orders) SELECT id FROM t")
    assert ok
