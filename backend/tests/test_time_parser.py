"""时间解析器单元测试（FR-NLU-10、R-11）：以固定「今天」保证可复现。"""

from datetime import date

from app.services.nlu.time_parser import parse_time_expression

TODAY = date(2026, 10, 5)  # 周一，Q4


def test_last_month():
    """SC-01「上个月」：2026-09 自然月。"""
    assert parse_time_expression("上个月", TODAY) == (date(2026, 9, 1), date(2026, 9, 30))


def test_this_month():
    assert parse_time_expression("本月", TODAY) == (date(2026, 10, 1), date(2026, 10, 31))


def test_this_quarter():
    """SC-02「这个季度」：Q4 → 10-01 至 12-31。"""
    assert parse_time_expression("这个季度", TODAY) == (date(2026, 10, 1), date(2026, 12, 31))


def test_last_quarter_year_boundary():
    """上季度跨年：1 月的上季度是去年 Q4。"""
    jan = date(2026, 1, 5)
    assert parse_time_expression("上季度", jan) == (date(2025, 10, 1), date(2025, 12, 31))


def test_year_expressions():
    assert parse_time_expression("今年", TODAY) == (date(2026, 1, 1), date(2026, 12, 31))
    assert parse_time_expression("去年", TODAY) == (date(2025, 1, 1), date(2025, 12, 31))


def test_recent_days():
    """近 30 天含今天。"""
    assert parse_time_expression("近30天", TODAY) == (date(2026, 9, 6), date(2026, 10, 5))
    assert parse_time_expression("最近7天", TODAY) == (date(2026, 9, 29), date(2026, 10, 5))


def test_week_expressions():
    """周一为本周起点：今天周一 → 本周即今天。"""
    assert parse_time_expression("本周", TODAY) == (date(2026, 10, 5), date(2026, 10, 5))
    assert parse_time_expression("上周", TODAY) == (date(2026, 9, 28), date(2026, 10, 4))


def test_explicit_month():
    assert parse_time_expression("2026年8月", TODAY) == (date(2026, 8, 1), date(2026, 8, 31))
    assert parse_time_expression("2026-02", TODAY) == (date(2026, 2, 1), date(2026, 2, 28))


def test_month_only_defaults_to_current_year():
    assert parse_time_expression("3月", TODAY) == (date(2026, 3, 1), date(2026, 3, 31))


def test_recent_months():
    assert parse_time_expression("近3个月", TODAY) == (date(2026, 7, 5), date(2026, 10, 5))


def test_unknown_returns_none():
    """无法识别 → None（由 NLU 决定澄清而非硬猜）。"""
    assert parse_time_expression("大促期间", TODAY) is None
