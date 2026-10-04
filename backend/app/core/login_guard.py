"""登录失败锁定（FR-SEC-40、P-32）。

进程内存实现，适合 T1 单实例开发与验证；
生产多实例部署时须迁移到 Redis（与限流共用存储），TODO 在 T5 完成。
"""

import time

from app.core.errors import AppError

# {username: [连续失败次数, 锁定截止时间戳]}
_failed: dict[str, list] = {}
_LOCK_SECONDS = 15 * 60


def check_locked(username: str, threshold: int) -> None:
    """登录前检查：若已锁定且未到期则拒绝（不提示剩余错误次数，避免账号枚举）。"""
    entry = _failed.get(username)
    if not entry:
        return
    count, locked_until = entry
    if locked_until and time.monotonic() < locked_until:
        raise AppError(40103, "失败次数过多，账号已临时锁定，请稍后再试", 401)
    if locked_until and time.monotonic() >= locked_until:
        # 锁定期满自动解除，重新计数
        _failed.pop(username, None)
    if not locked_until and count >= threshold:
        _lock(username)


def record_failure(username: str, threshold: int) -> None:
    """记录一次登录失败；达到阈值即触发锁定。"""
    entry = _failed.setdefault(username, [0, 0.0])
    entry[0] += 1
    if entry[0] >= threshold:
        _lock(username)


def record_success(username: str) -> None:
    """登录成功清除失败计数。"""
    _failed.pop(username, None)


def _lock(username: str) -> None:
    entry = _failed.setdefault(username, [0, 0.0])
    entry[1] = time.monotonic() + _LOCK_SECONDS
