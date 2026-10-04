"""表结构自动扫描服务（FR-SCH-02/03/05）。

通过只读连接对业务库做 PostgreSQL 目录内省，采集表/字段/主外键/注释/行数估计/低基数采样。
扫描过程只读，不修改源库；结果与已有元数据合并（物理属性更新，业务标注保留）。
"""

import time
from datetime import datetime, timezone

import psycopg
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.credential import decrypt_credential
from app.core.errors import AppError
from app.infra.models import ColumnMeta, Datasource, TableMeta
from app.services import audit_service
from app.services.datasource_service import _build_conninfo

# 行数估计低于该值的表才做低基数枚举采样，避免大表全列扫描（FR-SCH-05）
SAMPLE_ROW_LIMIT = 100_000
SAMPLE_VALUES_LIMIT = 20


async def scan_datasource(db: AsyncSession, ds_id: int, operator_id: int) -> dict:
    """扫描指定数据源：新增/更新表与字段元数据，返回统计。"""
    ds = await db.get(Datasource, ds_id)
    if ds is None:
        raise AppError(40400, "数据源不存在", 404)

    password = decrypt_credential(ds.credential_enc)
    conninfo = _build_conninfo(ds.host, ds.port, ds.db_name, ds.readonly_user, password)

    start = time.monotonic()
    try:
        # connect_timeout 为 libpq 参数，须置于连接串内（psycopg 无 timeout 关键字参数）
        async with await psycopg.AsyncConnection.connect(f"{conninfo} connect_timeout=10") as conn:
            physical = await _introspect(conn)
            stats = await _merge_scan_results(db, ds_id, physical)
            await _sample_enum_values(conn, db, ds_id)  # 低基数采样，用扫描连接（FR-SCH-05）
    except psycopg.OperationalError as e:
        raise AppError(50010, "无法连接数据源，扫描中止", 502) from e

    stats["duration_ms"] = int((time.monotonic() - start) * 1000)
    await audit_service.record(
        db, user_id=operator_id, action="admin.datasource.scan",
        object_type="datasource", object_id=str(ds_id), detail=stats,
    )
    await db.commit()
    return stats


async def _introspect(conn) -> dict:
    """一次性采集源库全部表/字段/主外键信息（只读目录查询）。

    注意 psycopg 异步游标：execute 与 fetchall 均需 await。
    """
    cur = await conn.execute(
        """
        SELECT n.nspname AS schema_name, c.relname AS table_name,
               GREATEST(c.reltuples::bigint, 0) AS row_estimate,
               obj_description(c.oid, 'pg_class') AS comment
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind = 'r'
          AND n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND n.nspname NOT LIKE 'pg_toast%'
        """
    )
    tables = [tuple(r) for r in await cur.fetchall()]

    cur = await conn.execute(
        """
        SELECT table_schema, table_name, column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
        ORDER BY table_schema, table_name, ordinal_position
        """
    )
    columns = [tuple(r) for r in await cur.fetchall()]

    cur = await conn.execute(
        """
        SELECT tc.table_schema, tc.table_name, kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY'
        """
    )
    pks = {(r[0], r[1], r[2]) for r in await cur.fetchall()}

    cur = await conn.execute(
        """
        SELECT kcu.table_schema, kcu.table_name, kcu.column_name,
               ccu.table_name AS ref_table, ccu.column_name AS ref_column
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
        """
    )
    fks = {(r[0], r[1], r[2]): f"{r[3]}.{r[4]}" for r in await cur.fetchall()}

    return {"tables": tables, "columns": columns, "pks": pks, "fks": fks}

    return {
        "tables": [tuple(r) for r in tables],
        "columns": [tuple(r) for r in columns],
        "pks": {(r[0], r[1], r[2]) for r in pks},
        "fks": {(r[0], r[1], r[2]): f"{r[3]}.{r[4]}" for r in fks},
    }


async def _merge_scan_results(db: AsyncSession, ds_id: int, physical: dict) -> dict:
    """扫描结果与库内已有元数据合并：物理属性更新，业务标注保留。"""
    now = datetime.now(timezone.utc)
    stats = {"tables": 0, "columns": 0, "new_tables": 0, "new_columns": 0}
    pk_set, fk_map = physical["pks"], physical["fks"]

    existing = {
        (t.schema_name, t.table_name): t
        for t in (
            await db.execute(select(TableMeta).where(TableMeta.datasource_id == ds_id))
        ).scalars()
    }

    for schema_name, table_name, row_estimate, comment in physical["tables"]:
        tm = existing.get((schema_name, table_name))
        if tm is None:
            tm = TableMeta(datasource_id=ds_id, schema_name=schema_name, table_name=table_name)
            db.add(tm)
            stats["new_tables"] += 1
            await db.flush()  # 取得 id 供字段外键使用

        tm.row_estimate = row_estimate
        tm.scan_at = now
        # 原生注释仅作标注兜底（缺失时填充），已有业务标注不被覆盖
        if comment and not tm.description:
            tm.description = comment

        cols = {
            c.column_name: c
            for c in (
                await db.execute(select(ColumnMeta).where(ColumnMeta.table_meta_id == tm.id))
            ).scalars()
        }
        col_count = 0
        for schema_c, table_c, col_name, data_type, is_nullable in physical["columns"]:
            if (schema_c, table_c) != (schema_name, table_name):
                continue
            col_count += 1
            col = cols.get(col_name)
            if col is None:
                col = ColumnMeta(table_meta_id=tm.id, column_name=col_name)
                db.add(col)
                stats["new_columns"] += 1
            col.data_type = data_type
            col.nullable = is_nullable == "YES"
            col.is_pk = (schema_name, table_name, col_name) in pk_set
            fk_ref = fk_map.get((schema_name, table_name, col_name))
            col.is_fk = fk_ref is not None
            col.fk_ref = fk_ref
        await db.flush()  # 物理属性赋值完成后再落库

        stats["tables"] += 1
        stats["columns"] += col_count

    await db.commit()
    return stats


async def _sample_enum_values(conn, db: AsyncSession, ds_id: int) -> None:
    """低基数枚举采样（FR-SCH-05）：仅对已纳入且行数小的表的 varchar/text 字段做。"""
    tables = (
        (
            await db.execute(
                select(TableMeta).where(
                    TableMeta.datasource_id == ds_id,
                    TableMeta.included.is_(True),
                    TableMeta.row_estimate > 0,
                    TableMeta.row_estimate < SAMPLE_ROW_LIMIT,
                )
            )
        )
        .scalars()
        .all()
    )

    for tm in tables:
        for col in tm.columns:
            if "char" not in col.data_type and col.data_type != "text":
                continue
            qualified = f'"{tm.schema_name}"."{tm.table_name}"'
            cur = await conn.execute(
                f'SELECT DISTINCT "{col.column_name}" FROM {qualified} '
                f'WHERE "{col.column_name}" IS NOT NULL LIMIT {SAMPLE_VALUES_LIMIT + 1}'
            )
            values = [str(r[0]) for r in await cur.fetchall()]
            # 基数超过阈值则只记录"超限"标记，不存全量（FR-SCH-05）
            if len(values) <= SAMPLE_VALUES_LIMIT:
                col.sample_values = {"values": values}
            else:
                col.sample_values = {"values": values[:SAMPLE_VALUES_LIMIT], "truncated": True}
    await db.commit()
