"""SQL 生成器（FR-SQL-01~04）。

调用 LLM 生成 SQL 并做健壮解析：容忍 markdown 代码块包裹、多余解释文字、
多条语句等异常输出；解析失败向上返回错误供自愈重试（FR-SQL-30）。
"""

import json
import re
from dataclasses import dataclass, field

SQL_GEN_MARKER = "[SQL_GEN_TASK]"


@dataclass
class GeneratedSQL:
    """解析后的 LLM 输出。"""

    sql: str
    assumptions: list[str] = field(default_factory=list)  # 口径假设（NFR-A-05 必须显式展示）
    confidence: float = 0.0
    explain: str = ""  # 自然语言解释（FR-SQL-34）


class OutputParseError(Exception):
    """LLM 输出无法解析（调用方据此回灌重试）。"""


def parse_llm_output(raw: str) -> GeneratedSQL:
    """解析 LLM 输出：优先 JSON（可能被 markdown 包裹），否则提取 SQL 代码块。"""
    text = raw.strip()

    # 1) 剥离 markdown 代码块后尝试 JSON
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = []
    if fenced:
        candidates.append(fenced.group(1))
    brace = re.search(r"\{.*\}", text, re.S)
    if brace:
        candidates.append(brace.group())

    for candidate in candidates:
        try:
            data = json.loads(candidate)
            sql = (data.get("sql") or "").strip()
            if sql:
                return GeneratedSQL(
                    sql=sql,
                    assumptions=list(data.get("assumptions") or []),
                    confidence=float(data.get("confidence") or 0.0),
                    explain=str(data.get("explain") or ""),
                )
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
            continue

    # 2) 无 JSON：从 ```sql 块提取
    sql_block = re.search(r"```(?:sql)?\s*(.+?)\s*```", text, re.S)
    if sql_block:
        sql = sql_block.group(1).strip()
        if _is_single_statement(sql):
            return GeneratedSQL(sql=sql, confidence=0.5,
                                explain="（模型未返回结构化说明，SQL 直接提取）")

    # 3) 兜底：整段文本若像单条 SQL
    if _is_single_statement(text):
        return GeneratedSQL(sql=text, confidence=0.3)

    raise OutputParseError("无法从模型输出中提取 SQL")


def _is_single_statement(sql: str) -> bool:
    """粗检：以 SELECT/WITH 开头且不含分号分隔的多条语句（精检由 sql_guard 承担）。"""
    head = sql.lstrip().lower()
    if not (head.startswith("select") or head.startswith("with")):
        return False
    body = sql.rstrip().rstrip(";")
    return ";" not in body


async def generate_sql(llm, messages: list[dict]) -> tuple[GeneratedSQL, int]:
    """调用 LLM 并解析输出，返回 (结果, token 用量)。"""
    resp = await llm.chat(messages, json_mode=True)
    parsed = parse_llm_output(resp.content)
    return parsed, resp.tokens
