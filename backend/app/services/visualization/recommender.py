"""图表推荐规则引擎（FR-VIS-01/02/03/04、§3.8）。

规则（基线可配，NFR-M-03）：
- 含时间维度 + 1~2 度量 → 折线图（SC-03 趋势）
- 1 分类维度（基数 ≤ 柱状阈值）+ 1 度量 → 柱状图（SC-01 TopN）
- 1 分类维度（基数 ≤ 8）+ 占比语义 → 饼图
- 其余 / 0 行 → 表格 / 空态卡片
输出附推荐理由；前端可基于缓存结果一键切换类型（FR-VIS-03，零请求重查）。

FR-VIS-13：绘图数据点超过 CHART_MAX_POINTS 时均匀采样并注明。
"""

import math

PIE_MAX = 8  # 饼图分类基数上限（P-41）
BAR_MAX = 30  # 柱状图分类基数阈值（P-40 待定，取 30 基线）
CHART_MAX_POINTS = 1000  # 绘图数据点上限（FR-VIS-13 大结果采样）

CHART_TYPES = ("line", "bar", "pie", "table")  # 支持一键切换的类型（FR-VIS-03）

_TIME_HINTS = ("date", "month", "week", "quarter", "year", "时间", "日期", "月份")


def _looks_time(col_name: str) -> bool:
    low = col_name.lower()
    return any(h in low for h in _TIME_HINTS)


def _sample(rows: list[list], cap: int = CHART_MAX_POINTS) -> tuple[list[list], bool]:
    """均匀采样到 cap 个数据点（FR-VIS-13）：返回 (采样后行, 是否触发采样)。"""
    if len(rows) <= cap:
        return rows, False
    step = math.ceil(len(rows) / cap)
    return rows[::step], True


def _categorize(columns: list[str], rows: list[list]):
    """识别时间列/数值列/分类列下标（启发式）。"""
    numeric_idx = [
        i for i, v in enumerate(rows[0]) if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    time_idx = next((i for i, c in enumerate(columns) if _looks_time(c)), None)
    dim_idx = next((i for i, c in enumerate(columns) if i not in numeric_idx and i != time_idx), None)
    metric_idx = numeric_idx[0] if numeric_idx else None
    return numeric_idx, time_idx, dim_idx, metric_idx


def build_chart_option(chart_type: str, columns: list[str], rows: list[list]) -> dict:
    """按指定类型构建 ECharts option（FR-VIS-03 一键切换：复用缓存结果，零请求）。

    FR-VIS-13：数据点超限时均匀采样并在标题注明；table 类型不采样直接由前端渲染。
    """
    sampled, sampled_flag = _sample(rows) if chart_type != "table" else (rows, False)
    base: dict = {"title": {"text": "（数据点已采样展示，完整数据请导出）"}} if sampled_flag else {}
    numeric_idx, time_idx, dim_idx, metric_idx = _categorize(columns, sampled)

    if chart_type == "table" or not sampled or metric_idx is None:
        return {**base, "type": "table"}

    # 无任何维度列（全数值结果）：单行用数值列名作分类，多行无法成图 → 表格
    if dim_idx is None and time_idx is None:
        if len(sampled) == 1:
            cats = [columns[i] for i in numeric_idx]
            data = [sampled[0][i] for i in numeric_idx]
            if chart_type == "pie":
                return {**base, "series": [{"type": "pie", "data": [
                    {"name": n, "value": v} for n, v in zip(cats, data, strict=False)]}]}
            return {**base,
                    "xAxis": {"type": "category", "data": cats},
                    "yAxis": {"type": "value"},
                    "series": [{"type": chart_type, "data": data}]}
        return {**base, "type": "table"}

    if chart_type == "line":
        x = [str(r[time_idx if time_idx is not None else dim_idx]) for r in sampled]
        return {**base,
                "xAxis": {"type": "category", "data": x},
                "yAxis": {"type": "value"},
                "series": [{"type": "line", "data": [r[metric_idx] for r in sampled]}]}

    if chart_type == "bar":
        cats = [str(r[dim_idx if dim_idx is not None else time_idx]) for r in sampled]
        return {**base,
                "xAxis": {"type": "category", "data": cats},
                "yAxis": {"type": "value"},
                "series": [{"type": "bar", "data": [r[metric_idx] for r in sampled]}]}

    if chart_type == "pie":
        cats = [str(r[dim_idx if dim_idx is not None else time_idx]) for r in sampled]
        return {**base, "series": [{"type": "pie", "data": [
            {"name": n, "value": r[metric_idx]} for n, r in zip(cats, sampled, strict=False)
        ]}]}

    return {**base, "type": "table"}


def recommend_chart(columns: list[str], rows: list[list], question: str = "") -> dict:
    """根据结果集结构推荐图表类型并生成 ECharts 配置（含采样处理，FR-VIS-13）。"""
    if not rows:
        return {"chart_type": "empty", "reason": "查询成功但无匹配数据", "option": None}

    sampled, sampled_flag = _sample(rows)
    numeric_idx, time_idx, dim_idx, metric_idx = _categorize(columns, sampled)
    reason_suffix = f"（{len(rows)} 点已采样为 {len(sampled)} 点展示）" if sampled_flag else ""

    # 折线：时间轴 + 度量（趋势/对比类问题，SC-03）
    if time_idx is not None and metric_idx is not None:
        reason = "结果含时间维度与度量，推荐折线图展示趋势"
        return {"chart_type": "line", "reason": reason + reason_suffix,
                "option": build_chart_option("line", columns, sampled)}

    # 柱状/饼：单分类维度 + 单度量（SC-01 TopN）
    if dim_idx is not None and metric_idx is not None:
        categories = [str(r[dim_idx]) for r in sampled]
        cardinality = len(set(categories))
        ratio_words = ("占比", "比例", "分布", "份额")
        if cardinality <= PIE_MAX and any(w in question for w in ratio_words):
            return {"chart_type": "pie",
                    "reason": f"分类基数 {cardinality} ≤ {PIE_MAX} 且问题含占比语义，推荐饼图{reason_suffix}",
                    "option": build_chart_option("pie", columns, sampled)}
        if cardinality <= BAR_MAX:
            return {"chart_type": "bar",
                    "reason": f"单分类维度（基数 {cardinality}）+ 单度量，推荐柱状图{reason_suffix}",
                    "option": build_chart_option("bar", columns, sampled)}
        return {"chart_type": "table", "reason": f"分类基数 {cardinality} 过大，推荐表格展示", "option": None}

    # 度量列表（无明确维度）：单行数值 → 柱状；多列长表 → 表格
    if len(rows) == 1 and numeric_idx:
        return {"chart_type": "bar", "reason": "单行多度量结果，推荐柱状图",
                "option": build_chart_option("bar", columns, sampled)}
    return {"chart_type": "table", "reason": "结果为明细列表，推荐表格展示", "option": None}
