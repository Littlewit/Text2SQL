"""查询限流（FR-SEC-31/32）。

双后端设计（调用点为 async，Redis 操作经 asyncio.to_thread 执行）：
- Redis 后端（多实例部署/生产）：INCR+EXPIRE 计数 + 并发键；
- 内存后端（单实例开发/测试）：Redis 不可用时自动降级，保证可用性（NFR-R-02）。

使用同步 redis 客户端而非 asyncio 客户端：异步连接绑定创建时的事件循环，
而测试/多 worker 场景下请求可能运行在不同循环上（跨循环 Future 报错）；
同步客户端无循环亲和性，配合 to_thread 安全且开销可接受（限流操作均为微秒级命令）。

配额默认值对应 P-25~28 待定参数；键前缀 t2s:rl:* 便于统一清理。
"""

import asyncio
import time
from collections import defaultdict, deque

from app.core.errors import AppError

# 内存后端状态
_windows: dict[int, deque] = defaultdict(deque)
_active_mem: dict[int, int] = defaultdict(int)

_redis = None
_redis_checked = False


def _get_redis_sync():
    """惰性获取同步 Redis 客户端；不可用返回 None（降级内存后端）。"""
    global _redis, _redis_checked
    if not _redis_checked:
        _redis_checked = True
        try:
            import redis

            from app.core.config import get_settings

            client = redis.from_url(
                get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1
            )
            client.ping()  # 真正探活
            _redis = client
        except Exception:  # noqa: BLE001 —— Redis 故障不应阻断限流降级
            _redis = None
    return _redis


async def reset_rate_limits() -> None:
    """测试/运维辅助：清空全部限流状态（含 Redis）。"""
    _windows.clear()
    _active_mem.clear()
    r = _get_redis_sync()
    if r:
        keys = list(r.scan_iter("t2s:rl:*"))
        if keys:
            r.delete(*keys)


async def check_query_allowed(user_id: int, qps_limit: int = 5, concurrent_limit: int = 2) -> None:
    """提交查询前检查：QPS 与并发双窗口（FR-SEC-31），超限抛 429 并给出可读提示。"""
    r = _get_redis_sync()
    if r:
        def _check() -> None:
            now = int(time.time())
            qps_key = f"t2s:rl:qps:{user_id}:{now}"
            act_key = f"t2s:rl:act:{user_id}"
            pipe = r.pipeline()
            pipe.incr(qps_key)
            pipe.expire(qps_key, 2)
            pipe.get(act_key)
            count, _, active = pipe.execute()
            if int(count) > qps_limit:
                raise AppError(42901, "查询过于频繁，请稍后再试", 429)
            if int(active or 0) >= concurrent_limit:
                raise AppError(42901, "您有查询正在执行，请等待完成后再提交", 429)

        await asyncio.to_thread(_check)
        return
    _mem_check(user_id, qps_limit, concurrent_limit)


async def mark_started(user_id: int) -> None:
    r = _get_redis_sync()
    _windows[user_id].append(time.monotonic())
    _active_mem[user_id] += 1
    if r:
        await asyncio.to_thread(r.incr, f"t2s:rl:act:{user_id}")


async def mark_finished(user_id: int) -> None:
    r = _get_redis_sync()
    _active_mem[user_id] = max(_active_mem[user_id] - 1, 0)
    if r:
        await asyncio.to_thread(r.decr, f"t2s:rl:act:{user_id}")


def _mem_check(user_id: int, qps_limit: int, concurrent_limit: int) -> None:
    now = time.monotonic()
    window = _windows[user_id]
    while window and now - window[0] > 1.0:
        window.popleft()
    if len(window) >= qps_limit:
        raise AppError(42901, "查询过于频繁，请稍后再试", 429)
    if _active_mem[user_id] >= concurrent_limit:
        raise AppError(42901, "您有查询正在执行，请等待完成后再提交", 429)
