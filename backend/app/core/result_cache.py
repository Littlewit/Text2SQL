"""查询结果缓存（FR-SQL-22，M2-T2 MVP 实现）。

进程内存缓存：结果在查询生命周期后短暂保留，供表格分页取数
（翻页不重新执行查询，§3.9/FR-SQL-22）。
- 仅缓存已脱敏数据（FR-SEC-22 出口一致性）；
- TTL 与容量上限防止内存膨胀；权限变更即时生效语义不受影响
  （FR-SEC-13：缓存的是脱敏后数据，不参与权限判定）。
多实例部署时迁移 Redis（TODO M2 后续）。
"""

import time

_MAX_ENTRIES = 200
_TTL_S = 600  # 10 分钟
_cache: dict[int, tuple[float, dict]] = {}


def put(query_id: int, payload: dict) -> None:
    """缓存结果（columns/rows/masked 已脱敏）。"""
    if len(_cache) >= _MAX_ENTRIES:
        # 淘汰最旧的一半
        for k in sorted(_cache, key=lambda k: _cache[k][0])[: _MAX_ENTRIES // 2]:
            _cache.pop(k, None)
    _cache[query_id] = (time.monotonic(), payload)


def get(query_id: int) -> dict | None:
    """取缓存结果；过期/不存在返回 None。"""
    entry = _cache.get(query_id)
    if entry is None:
        return None
    ts, payload = entry
    if time.monotonic() - ts > _TTL_S:
        _cache.pop(query_id, None)
        return None
    return payload


def evict(query_id: int) -> None:
    _cache.pop(query_id, None)
