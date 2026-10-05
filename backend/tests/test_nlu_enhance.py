"""NLU 增强（M2-T5）单测：聚合方式抽取（FR-NLU-15）、时间粒度归一化（FR-NLU-16）、置信度。"""

import pytest

from app.services.nlu.intent import _safe_confidence, extract_aggregations, normalize_granularity


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("上个月各店铺平均GMV是多少", ["avg"]),
        ("统计每个月的合计GMV和订单数量", ["sum", "count"]),
        ("哪个店铺GMV最高", ["max"]),
        ("最低退货率的商品", ["min"]),
        ("各渠道销售占比", ["ratio"]),
        ("有多少去重客户", ["count", "distinct"]),
        ("查出昨天的订单明细", []),  # 无聚合语义
    ],
)
def test_extract_aggregations(question, expected):
    """聚合关键词 → 归一化标识；多语义可叠加。"""
    assert extract_aggregations(question) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("按月", "month"),
        ("每月", "month"),
        ("月度", "month"),
        ("按天", "day"),
        ("每天", "day"),
        ("按周", "week"),
        ("每季度", "quarter"),
        ("按年", "year"),
        ("monthly", "month"),
        (None, None),
        ("", None),
        ("不知道", None),  # 非法粒度不猜测
        ("month", "month"),
    ],
)
def test_normalize_granularity(raw, expected):
    """时间粒度归一化：中文/英文表述 → 标准枚举。"""
    assert normalize_granularity(raw) == expected


def test_safe_confidence_bounds():
    """置信度容错：非法/越界值收敛到 [0,1]（零信任 LLM 输出）。"""
    assert _safe_confidence("0.7") == 0.7
    assert _safe_confidence(None) == 0.9  # 缺省
    assert _safe_confidence("abc") == 0.9  # 非法回落
    assert _safe_confidence(5) == 1.0  # 上界
    assert _safe_confidence(-1) == 0.0  # 下界
