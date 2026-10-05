"""只读查询执行器（FR-SEC-30/32/35、SEC-08）。

- 使用业务库只读账号独立连接（与元数据库连接池隔离）；
- 会话级 statement_timeout 数据库侧兜底，超时取消数据库端会话；
- 结果集获取至多 row_limit+1 行用于判断截断（FR-SQL-20）。
"""

import time

import psycopg
from pydantic import BaseModel

from app.core.credential import decrypt_credential
from app.core.errors import AppError
from app.infra.models import Datasource
from app.services.datasource_service import _build_conninfo


class ExecuteResult(BaseModel):
    columns: list[str]
    rows: list[list]
    row_count: int
    truncated: bool
    duration_ms: int


async def execute_readonly(
    ds: Datasource, sql: str, row_limit: int, timeout_s: int = 30
) -> ExecuteResult:
    """在只读连接上执行 SQL；错误转业务码（50003/50010），不透出堆栈（§9.1）。"""
    password = decrypt_credential(ds.credential_enc)
    conninfo = _build_conninfo(ds.host, ds.port, ds.db_name, ds.readonly_user, password)
    conninfo += f" connect_timeout=5 options='-c statement_timeout={timeout_s * 1000}'"

    start = time.monotonic()
    try:
        async with await psycopg.AsyncConnection.connect(conninfo) as conn:
            cur = await conn.execute(sql)
            cols = [d.name for d in cur.description] if cur.description else []
            rows = (await cur.fetchmany(row_limit + 1))[: row_limit + 1]
            truncated = len(rows) > row_limit
            rows = rows[:row_limit]
            return ExecuteResult(
                columns=cols,
                rows=[list(r) for r in rows],
                row_count=len(rows),
                truncated=truncated,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
    except psycopg.errors.QueryCanceled as e:
        raise AppError(50003, "查询超时已取消，请缩小时间范围或增加筛选条件", 504) from e
    except psycopg.errors.InsufficientPrivilege as e:
        raise AppError(40300, "当前账号无权执行该查询", 403) from e
    except psycopg.ProgrammingError as e:
        # 运行期错误（类型不匹配/字段不存在等）→ 结构化信息供自愈重试（FR-SQL-30）
        raise AppError(42205, f"SQL 执行错误: {e}", 422) from e
    except psycopg.OperationalError as e:
        raise AppError(50003, "数据库连接异常或超时，请稍后重试", 504) from e
