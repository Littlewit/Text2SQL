"""脱敏引擎（FR-SEC-20~22）。

按字段敏感标记与内置规则（手机号/身份证/邮箱/姓名等）在服务端结果集出口统一执行；
前端与导出文件均只接触脱敏后数据（FR-SEC-22）。
"""

import re
from dataclasses import dataclass

# 内置敏感类型识别（FR-SEC-21）：列名模式 → 掩码函数
_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
_IDCARD_RE = re.compile(r"^\d{17}[\dXx]$")
_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.]+$")

_COLUMN_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"phone|mobile|手机", re.I), "phone"),
    (re.compile(r"id_?card|身份证|identity", re.I), "id_card"),
    (re.compile(r"email|邮箱|mail", re.I), "email"),
    (re.compile(r"bank_?card|银行卡", re.I), "bank_card"),
    (re.compile(r"name|姓名", re.I), "name"),
]


@dataclass
class ColumnMaskInfo:
    """结果列的脱敏上下文：列名 + 是否敏感标记。"""

    name: str
    is_sensitive: bool = False


def detect_mask_type(column: ColumnMaskInfo, sample_values: list) -> str | None:
    """识别列的掩码类型：优先列名模式，辅以样例值正则（仅敏感列参与）。"""
    if not column.is_sensitive:
        return None
    for pat, mask_type in _COLUMN_PATTERNS:
        if pat.search(column.name):
            return mask_type
    for v in sample_values:
        s = str(v)
        if _PHONE_RE.match(s):
            return "phone"
        if _IDCARD_RE.match(s):
            return "id_card"
        if _EMAIL_RE.match(s):
            return "email"
    # 敏感但类型不明 → 通用部分掩码
    return "generic"


def mask_value(value, mask_type: str):
    """按类型执行掩码；非字符串先转字符串，None 原样返回。"""
    if value is None:
        return None
    s = str(value)
    if mask_type == "phone" and _PHONE_RE.match(s):
        return s[:3] + "****" + s[-4:]  # 138****1234（FR-SEC-21 示例形态）
    if mask_type == "id_card":
        return s[:4] + "***********" + s[-2:] if len(s) >= 8 else "***"
    if mask_type == "email" and _EMAIL_RE.match(s):
        local, _, domain = s.partition("@")
        return local[0] + "***@" + domain
    if mask_type == "bank_card" and s.isdigit() and len(s) >= 8:
        return s[:4] + " **** " + s[-4:]
    if mask_type == "name":
        return s[0] + "*" * max(len(s) - 1, 1)
    return s[:1] + "***"  # generic


def mask_rows(
    columns: list[ColumnMaskInfo], rows: list[list]
) -> tuple[list[ColumnMaskInfo], list[list]]:
    """对结果集就地掩码：返回 (列信息, 掩码后行数据)。

    敏感列的掩码类型在列级识别一次，行级执行，避免逐格正则（性能）。
    """
    samples: dict[int, list] = {}
    for row in rows[:50]:  # 用前 50 行做类型探测
        for i, v in enumerate(row):
            samples.setdefault(i, []).append(v)

    mask_types: dict[int, str | None] = {}
    for i, col in enumerate(columns):
        mask_types[i] = detect_mask_type(col, samples.get(i, []))

    masked = [
        [mask_value(v, mask_types[i]) if mask_types.get(i) else v for i, v in enumerate(row)]
        for row in rows
    ]
    return columns, masked


def mask_risk_warnings(sql: str, sensitive_columns: set[str]) -> list[str]:
    """脱敏反推风险分析（FR-SEC-23，M2-T3）：脱敏列参与分组/等值筛选时告警。

    掩码值仍可能被用于反推（如按掩码手机号分组计数即等于按原值分组）。
    MVP 采用告警而非拦截；拦截模式随需求确认（Q-09）后启用。
    """
    if not sensitive_columns:
        return []
    import sqlglot
    from sqlglot import exp

    try:
        ast = sqlglot.parse_one(sql, dialect="postgres")
    except sqlglot.errors.SqlglotError:
        return []

    warnings: list[str] = []
    for col in ast.find_all(exp.Column):
        if col.name.lower() not in sensitive_columns:
            continue
        in_group = col.find_ancestor(exp.Group)
        in_eq = any(
            isinstance(p.this, exp.Column) and p.this.name.lower() == col.name.lower()
            for p in ast.find_all(exp.EQ)
            if isinstance(p.this, exp.Column)
        )
        if in_group:
            w = f"脱敏字段 {col.name} 参与了分组，分组计数等价于按原值分组，存在反推风险"
            if w not in warnings:
                warnings.append(w)
        elif in_eq:
            w = f"脱敏字段 {col.name} 参与了等值筛选，可能被用于反推原值"
            if w not in warnings:
                warnings.append(w)
    return warnings
