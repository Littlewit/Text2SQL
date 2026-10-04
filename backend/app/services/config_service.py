"""系统配置服务（FR-ADM-05）。

配置项是限流、超时、行数上限等参数的唯一来源（NFR-M-03）；
所有变更留痕（审计），管理员调整后对新查询立即生效（内存缓存 TTL=0，直接查库）。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import SysConfig
from app.services import audit_service

# 内置默认配置（建议基线，P-xx 待定项确认后由管理 API 调整）
DEFAULT_CONFIGS: list[dict] = [
    {"key": "query.row_limit", "value": 1000, "description": "查询结果集强制行数上限（P-20 待定）"},
    {"key": "query.timeout_s", "value": 30, "description": "单条 SQL 执行超时（P-24，建议 30s）"},
    {"key": "sql_gen.max_retry", "value": 2, "description": "SQL 生成失败最大自动重试次数（P-19）"},
    {"key": "schema.top_k", "value": 10, "description": "Schema 检索 Top-K（P-15 待定）"},
    {"key": "security.login_lockout_threshold", "value": 5,
     "description": "登录失败锁定阈值（P-32 待定）"},
]


async def list_configs(db: AsyncSession) -> list[SysConfig]:
    """全部配置项列表。"""
    from sqlalchemy import select

    return list((await db.execute(select(SysConfig).order_by(SysConfig.key))).scalars())


async def upsert_config(
    db: AsyncSession, key: str, value, description: str | None, operator_id: int
) -> SysConfig:
    """新增或更新配置；更新前旧值留审计，支持追溯（变更留痕要求）。"""
    cfg = await db.get(SysConfig, key)
    old_value = cfg.value if cfg else None
    if cfg is None:
        cfg = SysConfig(key=key, value=value, description=description)
        db.add(cfg)
    else:
        cfg.value = value
        if description is not None:
            cfg.description = description

    await audit_service.record(
        db, user_id=operator_id, action="admin.config.update",
        object_type="sys_config", object_id=key,
        detail={"old": old_value, "new": value},
    )
    await db.commit()
    return cfg
