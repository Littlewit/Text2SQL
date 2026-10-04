"""API 契约 Schema（Pydantic v2，§6.1）。

T1 覆盖认证、用户管理、数据源与系统配置。
"""

from typing import Any

from pydantic import BaseModel, Field


# --- 认证 ---
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserInfo(BaseModel):
    id: int
    username: str
    display_name: str | None
    roles: list[str]
    must_change_password: bool


class LoginResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    user: UserInfo


# --- 用户管理 ---
class ScopeIn(BaseModel):
    scope_type: str = Field(pattern="^(shop|region|department)$")
    scope_value: str = Field(min_length=1, max_length=128)


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    display_name: str | None = Field(default=None, max_length=128)
    password: str = Field(min_length=8, max_length=128)  # 弱口令策略（FR-SEC-40）
    roles: list[str] = Field(default_factory=list)
    scopes: list[ScopeIn] = Field(default_factory=list)


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    status: int | None = Field(default=None, ge=0, le=1)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    roles: list[str] | None = None
    scopes: list[ScopeIn] | None = None


# --- 数据源 ---
class DataSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    host: str = Field(min_length=1, max_length=256)
    port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = Field(min_length=1, max_length=128)
    readonly_user: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128)


# --- 系统配置 ---
class ConfigUpsert(BaseModel):
    value: Any
    description: str | None = Field(default=None, max_length=256)
