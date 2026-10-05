"""确定性相对时间解析器（FR-NLU-10、R-11）。

时间解析不走 LLM：以服务器时区与「当前日期」为基准做规则解析，
保证 SC-01「上个月」、SC-02「这个季度」等表述结果可复现、可测试。
LLM 只输出时间表述原文，本模块负责落成具体日期区间 [start, end]（含端点）。
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def today_cn() -> date:
    """当前日期（服务器时区，DEP-09）。"""
    tz = ZoneInfo(get_settings().timezone)
    return datetime.now(tz).date()


def month_range(year: int, month: int) -> tuple[date, date]:
    """自然月区间。"""
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return start, end


def quarter_range(year: int, quarter: int) -> tuple[date, date]:
    """自然季区间。"""
    start_month = quarter * 3 - 2
    start = date(year, start_month, 1)
    end_year, end_month = (year, start_month + 3) if start_month + 3 <= 12 else (year + 1, 1)
    end = date(end_year, end_month, 1) - timedelta(days=1)
    return start, end


def parse_time_expression(text: str, today: date | None = None) -> tuple[date, date] | None:
    """解析时间表述 → [start, end]；无法识别返回 None（由调用方决定澄清）。

    覆盖：上/本/下月、上/本/下季度、今年/去年、本周/上周、近/最近 N 天、
    YYYY年M月、YYYY-MM、YYYY、M月D日~M月D日 等常见业务表述。
    """
    today = today or today_cn()
    t = text.strip()

    def prev_month(d: date) -> tuple[date, date]:
        y, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
        return month_range(y, m)

    if "上个月" in t or "上月" in t:
        return prev_month(today)
    if "这个月" in t or "本月" in t or "当月" in t:
        return month_range(today.year, today.month)
    if "上季度" in t or "上个季度" in t:
        q = (today.month - 1) // 3  # 0-based
        py, pq = (today.year, q) if q > 0 else (today.year - 1, 3)
        return quarter_range(py, pq + 1)  # 1-based
    if "这个季度" in t or "本季度" in t or "当季" in t:
        return quarter_range(today.year, (today.month - 1) // 3 + 1)
    if "去年" in t:
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    if "今年" in t:
        return date(today.year, 1, 1), date(today.year, 12, 31)
    if "上周" in t:
        this_monday = today - timedelta(days=today.weekday())
        last_monday = this_monday - timedelta(days=7)
        return last_monday, this_monday - timedelta(days=1)
    if "本周" in t or "这周" in t:
        monday = today - timedelta(days=today.weekday())
        return monday, today

    # 近/最近 N 天（含今天）
    for kw in ("近", "最近", "过去"):
        if kw in t and "天" in t:
            n = _extract_number(t, after=kw)
            if n:
                return today - timedelta(days=n - 1), today
    if "近" in t and "个月" in t:
        n = _extract_number(t, after="近") or 3
        # 同日回推 N 个月（日超界则取当月最后一天），滚动窗口语义
        y, m = today.year, today.month - n
        while m <= 0:
            m += 12
            y -= 1
        day = min(today.day, month_range(y, m)[1].day)
        return date(y, m, day), today

    # YYYY年M月 / YYYY-MM / M月（默认今年）
    if match := _year_month(t):
        return month_range(*match)
    if match := _iso_month(t):
        return month_range(*match)

    # 单独年份
    if t.isdigit() and 1900 < int(t) < 2200:
        y = int(t)
        return date(y, 1, 1), date(y, 12, 31)

    # M月（默认今年）
    if m := _extract_number(t, suffix="月"):
        if 1 <= m <= 12:
            return month_range(today.year, m)

    return None


def _extract_number(t: str, after: str = "", suffix: str = "") -> int | None:
    """从文本中提取 after 之后、suffix 之前的整数。"""
    idx = t.find(after) if after else 0
    if idx < 0:
        return None
    seg = t[idx + len(after):]
    if suffix:
        sfx = seg.find(suffix)
        if sfx < 0:
            return None
        seg = seg[:sfx]
    digits = "".join(ch for ch in seg if ch.isdigit())
    return int(digits) if digits else None


def _year_month(t: str) -> tuple[int, int] | None:
    """匹配 YYYY年M月 形态。"""
    import re

    m = re.search(r"(\d{4})年(\d{1,2})月", t)
    if m and 1 <= int(m.group(2)) <= 12:
        return int(m.group(1)), int(m.group(2))
    return None


def _iso_month(t: str) -> tuple[int, int] | None:
    """匹配 YYYY-MM 形态。"""
    import re

    m = re.fullmatch(r"(\d{4})-(\d{1,2})", t)
    if m and 1 <= int(m.group(2)) <= 12:
        return int(m.group(1)), int(m.group(2))
    return None
