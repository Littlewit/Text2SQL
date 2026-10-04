"""数据源管理服务（FR-ADM-02、FR-SCH-06）。

凭据加密存储；连通性测试使用真实只读连接（带超时），
为 T2 的表结构扫描建立可复用的连接构建逻辑。
"""

import asyncio
import time
from typing import TYPE_CHECKING

import psycopg
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.credential import decrypt_credential, encrypt_credential
from app.core.errors import AppError
from app.infra.models import Datasource
from app.services import audit_service

if TYPE_CHECKING:
    from app.infra.models import User


def _build_conninfo(host: str, port: int, db_name: str, user: str, password: str) -> str:
    """构建 psycopg 连接串；连接参数值中的空白与反斜杠需转义。"""
    def esc(v: str) -> str:
        return v.replace("\\", "\\\\").replace(" ", "\\ ")

    return (
        f"host={esc(host)} port={port} dbname={esc(db_name)} "
        f"user={esc(user)} password={esc(password)}"
    )


async def create_datasource(db: AsyncSession, data, operator: "User") -> Datasource:
    """接入数据源：密码即刻加密，接口与日志均不出现明文（KEY-02）。"""
    ds = Datasource(
        name=data.name,
        host=data.host,
        port=data.port,
        db_name=data.db_name,
        readonly_user=data.readonly_user,
        credential_enc=encrypt_credential(data.password),
        created_by=operator.id,
    )
    db.add(ds)
    await db.flush()
    await audit_service.record(
        db, user_id=operator.id, action="admin.datasource.create",
        object_type="datasource", object_id=str(ds.id),
        detail={"name": ds.name, "host": ds.host, "port": ds.port, "db": ds.db_name},
    )
    await db.commit()
    return ds


async def list_datasources(db: AsyncSession) -> list[Datasource]:
    """数据源列表（不含任何凭据信息）。"""
    return list((await db.execute(select(Datasource))).scalars())


async def get_datasource(db: AsyncSession, ds_id: int) -> Datasource:
    ds = await db.get(Datasource, ds_id)
    if ds is None:
        raise AppError(40400, "数据源不存在", 404)
    return ds


async def test_connection(db: AsyncSession, ds_id: int) -> dict:
    """连通性测试：真实建立只读连接并执行 SELECT 1（FR-ADM-02）。

    错误信息仅区分「无法连接 / 认证失败」，不透出数据库原始堆栈（§9.1 最小暴露）。
    """
    ds = await get_datasource(db, ds_id)
    password = decrypt_credential(ds.credential_enc)
    conninfo = _build_conninfo(ds.host, ds.port, ds.db_name, ds.readonly_user, password)

    start = time.monotonic()
    try:
        conn = await asyncio.wait_for(
            psycopg.AsyncConnection.connect(conninfo), timeout=5.0
        )
    except psycopg.OperationalError as e:
        msg = str(e)
        if "password authentication failed" in msg:
            raise AppError(50010, "数据源认证失败，请检查只读账号配置", 502) from e
        raise AppError(50010, "无法连接数据源，请检查地址、端口与网络", 502) from e
    latency_ms = int((time.monotonic() - start) * 1000)

    try:
        await conn.execute("SELECT 1")
    finally:
        await conn.close()
    return {"ok": True, "latency_ms": latency_ms}
