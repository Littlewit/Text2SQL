"""SQL 输出解析 / 脱敏引擎 / 图表推荐单元测试。"""

import pytest

from app.services.masking.engine import ColumnMaskInfo, mask_rows, mask_value
from app.services.sql_gen.generator import OutputParseError, parse_llm_output
from app.services.visualization.recommender import recommend_chart


# --- 输出健壮解析（FR-SQL-04）---
def test_parse_json_direct():
    out = parse_llm_output('{"sql": "SELECT 1", "assumptions": [], "confidence": 0.9, "explain": "x"}')
    assert out.sql == "SELECT 1" and out.confidence == 0.9


def test_parse_json_in_markdown():
    raw = (
        '好的，以下是查询：\n```json\n'
        '{"sql": "SELECT id FROM orders", "assumptions": ["假设a"], '
        '"confidence": 0.8, "explain": "查订单ID"}\n```\n以上。'
    )
    out = parse_llm_output(raw)
    assert out.sql == "SELECT id FROM orders"
    assert out.assumptions == ["假设a"]


def test_parse_sql_code_block():
    raw = "```sql\nSELECT id FROM orders\n```"
    assert parse_llm_output(raw).sql == "SELECT id FROM orders"


def test_parse_garbage_raises():
    """完全无法提取 → 抛错，由调用方回灌重试（FR-SQL-04/30）。"""
    with pytest.raises(OutputParseError):
        parse_llm_output("抱歉我不明白你的意思")


def test_parse_multi_statement_fallback_rejected():
    """裸多条语句不能整段当作 SQL。"""
    with pytest.raises(OutputParseError):
        parse_llm_output("SELECT 1; SELECT 2")


# --- 脱敏引擎（FR-SEC-20~22）---
def test_mask_phone():
    assert mask_value("13812345678", "phone") == "138****5678"


def test_mask_email():
    assert mask_value("zhangsan@example.com", "email") == "z***@example.com"


def test_mask_name():
    assert mask_value("张三丰", "name") == "张**"


def test_mask_none_passthrough():
    assert mask_value(None, "phone") is None


def test_mask_rows_by_column_flag():
    """只有敏感列被掩码；掩码类型由列名模式识别（FR-SEC-21）。"""
    cols = [ColumnMaskInfo("shop_name"), ColumnMaskInfo("customer_phone", True)]
    rows = [["旗舰店A", "13812345678"], ["门店B", "13987654321"]]
    _, masked = mask_rows(cols, rows)
    assert masked[0] == ["旗舰店A", "138****5678"]
    assert masked[1] == ["门店B", "139****4321"]


def test_non_sensitive_column_untouched():
    cols = [ColumnMaskInfo("amount")]
    _, masked = mask_rows(cols, [[123.45]])
    assert masked[0][0] == 123.45


# --- 图表推荐（FR-VIS-01/02）---
def test_chart_line_for_time_series():
    """时间 + 度量 → 折线（SC-03 趋势）。"""
    rec = recommend_chart(["month", "gmv"], [["2026-08", 100], ["2026-09", 200]], "趋势")
    assert rec["chart_type"] == "line"


def test_chart_bar_for_category():
    """分类 + 度量 → 柱状（SC-01 TopN）。"""
    rec = recommend_chart(["shop", "gmv"], [["A店", 500], ["B店", 300]], "哪个最高")
    assert rec["chart_type"] == "bar"


def test_chart_table_for_high_cardinality():
    rows = [[str(i), i] for i in range(50)]
    rec = recommend_chart(["shop", "gmv"], rows, "全部店铺")
    assert rec["chart_type"] == "table"


def test_chart_empty_state():
    """0 行 → 提示卡片，不出空图（FR-VIS-02）。"""
    rec = recommend_chart(["shop", "gmv"], [], "任意")
    assert rec["chart_type"] == "empty" and rec["option"] is None
