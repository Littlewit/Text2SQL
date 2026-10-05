"""图表推荐规则引擎（FR-VIS-01/02、§3.8）。

规则（基线可配，NFR-M-03）：
- 含时间维度 + 1~2 度量 → 折线图（SC-03 趋势）
- 1 分类维度（基数 ≤ 柱状阈值）+ 1 度量 → 柱状图（SC-01 TopN）
- 1 分类维度（基数 ≤ 8）+ 占比语义 → 饼图
- 其余 / 0 行 → 表格 / 空态卡片
输出附推荐理由，前端可一键切换（FR-VIS-03）。
"""

PIE_MAX = 8  # 饼图分类基数上限（P-41）
BAR_MAX = 30  # 柱状图分类基数阈值（P-40 待定，取 30 基线）

_TIME_HINTS = ("date", "month", "week", "quarter", "year", "时间", "日期")


def _looks_time(col_name: str) -> bool:
    low = col_name.lower()
    return any(h in low for h in _TIME_HINTS)


def recommend_chart(columns: list[str], rows: list[list], question: str = "") -> dict:
    """根据结果集结构推荐图表类型并生成简化 ECharts 配置。"""
    if not rows:
        return {"chart_type": "empty", "reason": "查询成功但无匹配数据", "option": None}

    # 启发式识别时间列与数值列
    numeric_idx = [
        i for i, v in enumerate(rows[0]) if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    time_idx = next((i for i, c in enumerate(columns) if _looks_time(c)), None)
    dim_idx = next((i for i, c in enumerate(columns) if i not in numeric_idx and i != time_idx), None)
    metric_idx = numeric_idx[0] if numeric_idx else None

    # 折线：时间轴 + 度量（趋势/对比类问题，SC-03）
    if time_idx is not None and metric_idx is not None:
        categories = [str(r[time_idx]) for r in rows]
        return {
            "chart_type": "line",
            "reason": "结果含时间维度与度量，推荐折线图展示趋势",
            "option": {
                "xAxis": {"type": "category", "data": categories},
                "yAxis": {"type": "value"},
                "series": [{"type": "line", "data": [r[metric_idx] for r in rows]}],
            },
        }

    # 柱状/饼：单分类维度 + 单度量（SC-01 TopN）
    if dim_idx is not None and metric_idx is not None:
        categories = [str(r[dim_idx]) for r in rows]
        cardinality = len(set(categories))
        ratio_words = ("占比", "比例", "分布", "份额")
        if cardinality <= PIE_MAX and any(w in question for w in ratio_words):
            return {
                "chart_type": "pie",
                "reason": f"分类基数 {cardinality} ≤ {PIE_MAX} 且问题含占比语义，推荐饼图",
                "option": {
                    "series": [{"type": "pie", "data": [
                        {"name": str(r[dim_idx]), "value": r[metric_idx]} for r in rows
                    ]}],
                },
            }
        if cardinality <= BAR_MAX:
            return {
                "chart_type": "bar",
                "reason": f"单分类维度（基数 {cardinality}）+ 单度量，推荐柱状图",
                "option": {
                    "xAxis": {"type": "category", "data": categories},
                    "yAxis": {"type": "value"},
                    "series": [{"type": "bar", "data": [r[metric_idx] for r in rows]}],
                },
            }
        return {"chart_type": "table", "reason": f"分类基数 {cardinality} 过大，推荐表格展示", "option": None}

    # 度量列表（无明确维度）：单行数值 → 柱状；多列长表 → 表格
    if len(rows) == 1 and numeric_idx:
        return {
            "chart_type": "bar",
            "reason": "单行多度量结果，推荐柱状图",
            "option": {
                "xAxis": {"type": "category", "data": [columns[i] for i in numeric_idx]},
                "yAxis": {"type": "value"},
                "series": [{"type": "bar", "data": [rows[0][i] for i in numeric_idx]}],
            },
        }
    return {"chart_type": "table", "reason": "结果为明细列表，推荐表格展示", "option": None}
