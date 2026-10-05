"""每日查询配额（FR-SEC-33、P-25~28）：单用户/全局「次数」与 token 配额拦截。

双后端与限流一致（core.rate_limit）：
- Redis：INCR + 当日过期（键含日期，自然滚动重置）；
- 内存：单实例开发/测试降级。
配额值读 sys_config（0 = 不限制）：
- quota.user_daily_queries / quota.global_daily_queries（次数，前置硬拦截）
- quota.user_daily_tokens / quota.global_daily_tokens（token，事后累计软拦截：
  下一次查询前若已超限则拒绝）
"""

import asyncio
from collections import defaultdict
from datetime import datetime

from app.core.errors import AppError

# 内存后端：{(kind, key, date): count}
_mem_quota: dict[tuple[str, str, str], int] = defaultdict(int)

_redis = None
_redis_checked = False

_TTL = 60 * 60 * 36  # 键 TTL：覆盖跨日边界；键本身含日期保证按日重置


def _get_redis_sync():
    """惰性获取同步 Redis；不可用降级内存后端（NFR-R-02）。"""
    global _redis, _redis_checked
    if not _redis_checked:
        _redis_checked = True
        try:
            import redis

            from app.core.config import get_settings

            client = redis.from_url(
                get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1
            )
            client.ping()
            _redis = client
        except Exception:  # noqa: BLE001 —— Redis 故障不应阻断降级
            _redis = None
    return _redis


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def reset_quotas() -> None:
    """测试/运维辅助：清空配额计数（含 Redis）。"""
    _mem_quota.clear()
    r = _get_redis_sync()
    if r:
        keys = list(r.scan_iter("t2s:rl:quota:*"))
        if keys:
            r.delete(*keys)


def _quota_keys(user_id: int, today: str) -> dict[str, str]:
    return {
        "uq": f"t2s:rl:quota:uq:{user_id}:{today}",
        "gq": f"t2s:rl:quota:gq:{today}",
        "ut": f"t2s:rl:quota:ut:{user_id}:{today}",
        "gt": f"t2s:rl:quota:gt:{today}",
    }


def _raise_exceeded(kind: str) -> None:
    msg = {
        "uq": "今日查询次数已达配额上限，请明天再试或联系管理员",
        "gq": "平台今日查询总量已达配额上限，请稍后再试",
        "ut": "今日 AI 用量（token）已达配额上限",
        "gt": "平台今日 AI 用量（token）已达配额上限",
    }[kind]
    raise AppError(42902, msg, 429)


async def check_quota(user_id: int, user_daily: int, global_daily: int,
                      user_tokens: int, global_tokens: int) -> None:
    """查询前置配额校验：任一维度超限即 429（FR-SEC-33）。0 表示不限。"""
    if not (user_daily or global_daily or user_tokens or global_tokens):
        return  # 全部未配置，零开销跳过
    today = _today()
    r = _get_redis_sync()

    if r:
        def _check() -> None:
            vals = r.mget(_quota_keys(user_id, today).values())
            counts = dict(zip(("uq", "gq", "ut", "gt"),
                              (int(v or 0) for v in vals), strict=False))
            for kind, limit in (("uq", user_daily), ("gq", global_daily),
                                ("ut", user_tokens), ("gt", global_tokens)):
                if limit and counts[kind] >= limit:
                    _raise_exceeded(kind)

        await asyncio.to_thread(_check)
        return

    for kind, limit in (("uq", user_daily), ("gq", global_daily),
                        ("ut", user_tokens), ("gt", global_tokens)):
        key = str(user_id) if kind in ("uq", "ut") else "-"
        if limit and _mem_quota[(kind, key, today)] >= limit:
            _raise_exceeded(kind)


async def record_usage(user_id: int, tokens: int) -> None:
    """查询成功后累计用量（次数 +1，token +tokens）。"""
    today = _today()
    r = _get_redis_sync()
    if r:
        def _rec() -> None:
            for key in _quota_keys(user_id, today).values():
                pipe = r.pipeline()
                pipe.incr(key)
                pipe.expire(key, _TTL)
                pipe.execute()

        await asyncio.to_thread(_rec)
        return

    _mem_quota[("uq", str(user_id), today)] += 1
    _mem_quota[("gq", "-", today)] += 1
    if tokens:
        _mem_quota[("ut", str(user_id), today)] += tokens
        _mem_quota[("gt", "-", today)] += tokens