"""SQL 生成服务包：LLM 输出健壮解析（FR-SQL-04）+ 生成器。"""

from app.services.sql_gen.generator import generate_sql, parse_llm_output

__all__ = ["generate_sql", "parse_llm_output"]
