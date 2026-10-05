"""T2 Schema 元数据 API 契约（Pydantic v2）。"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class TablePatch(BaseModel):
    cn_name: str | None = Field(default=None, max_length=128)
    description: str | None = None
    included: bool | None = None  # 白名单纳入（FR-SCH-03）


class ColumnPatch(BaseModel):
    cn_name: str | None = Field(default=None, max_length=128)
    description: str | None = None
    unit: str | None = Field(default=None, max_length=32)
    usage_type: Literal["dimension", "metric", "both"] | None = None
    is_sensitive: bool | None = None
    hidden_roles: list[str] | None = None  # FR-SEC-15：对这些角色不可见


class SchemaSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=512)
    datasource_id: int | None = None
    top_k: int = Field(default=10, ge=1, le=50)


class MetricCreate(BaseModel):
    datasource_id: int | None = None
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=64, pattern="^[a-z][a-z0-9_]*$")
    description: str | None = None
    formula: dict[str, Any] | None = None  # 结构化口径公式（FR-SCH-12）
    agg_type: Literal["sum", "count", "count_distinct", "avg", "max", "min"] | None = None
    default_time_column: str | None = Field(default=None, max_length=256)
    unit: str | None = Field(default=None, max_length=32)


class MetricPatch(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    description: str | None = None
    formula: dict[str, Any] | None = None
    agg_type: Literal["sum", "count", "count_distinct", "avg", "max", "min"] | None = None
    default_time_column: str | None = Field(default=None, max_length=256)
    unit: str | None = Field(default=None, max_length=32)
    status: int | None = Field(default=None, ge=0, le=1)


class SynonymCreate(BaseModel):
    term: str = Field(min_length=1, max_length=128)
    target_type: Literal["metric", "column", "dimension_value"]
    target_id: int
    datasource_id: int | None = None


class EnumDictUpsert(BaseModel):
    column_meta_id: int
    raw_value: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)


class JoinPathCreate(BaseModel):
    datasource_id: int
    left_table_id: int
    right_table_id: int
    left_column: str = Field(min_length=1, max_length=128)
    right_column: str = Field(min_length=1, max_length=128)
    join_type: Literal["inner", "left"] = "inner"
    description: str | None = None
