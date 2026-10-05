"""Prompt 组装服务包：模板版本化 + Schema 片段 + 动态 Few-shot（FR-NLU-20~23）。"""

from app.services.prompt.builder import build_sql_prompt

__all__ = ["build_sql_prompt", "PROMPT_TEMPLATE_VERSION"]
