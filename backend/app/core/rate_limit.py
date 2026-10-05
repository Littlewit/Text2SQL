"""查询限流（FR-SEC-31/32，P-25~28 待定值的进程内实现）。

T3 采用进程内滑动窗口（单实例开发足够）；
多实例部署时须迁移到 Redis 共享计数（TODO T5），接口保持不变。
"""

import time
from collections import defaultdict, deque

from app.core.errors import AppError

# {user_id: [(timestamp, ...)]} 滑动窗口
_windows: dict[int, deque] = defaultdict(deque)
# {user_id: 活跃查询数} 并发上限
_active: dict[int, int] = defaultdict(int)


def check_query_allowed(user_id: int, qps_limit: int = 5, concurrent_limit: int = 2) -> None:
    """提交查询前检查：QPS 与并发双窗口，超限返回 429 与建议等待（FR-SEC-31）。"""
    now = time.monotonic()
    window = _windows[user_id]
    while window and now - window[0] > 1.0:
        window.popleft()
    if len(window) >= qps_limit:
        raise AppError(42901, "查询过于频繁，请稍后再试", 429)
    if _active[user_id] >= concurrent_limit:
        raise AppError(42901, "您有查询正在执行，请等待完成后再提交", 429)


def mark_started(user_id: int) -> None:
    _windows[user_id].append(time.monotonic())
    _active[user_id] += 1


def mark_finished(user_id: int) -> None:
    _active[user_id] = max(_active[user_id] - 1, 0)


def reset_rate_limits() -> None:
    """测试/运维辅助：清空全部限流状态。"""
    _windows.clear()
    _active.clear()
