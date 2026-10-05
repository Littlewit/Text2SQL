"""SQLAlchemy ORM 模型汇总（对应系统设计 §4.2 DDL）。

导入本包即完成全部模型注册，供 Alembic 与应用使用。
"""

from app.infra.models.audit import AuditLog
from app.infra.models.base import Base
from app.infra.models.config import SysConfig
from app.infra.models.datasource import Datasource
from app.infra.models.query import Conversation, FewShot, Message, QueryHistory, RowPolicy
from app.infra.models.schema_meta import (
    ColumnMeta,
    EnumDict,
    JoinPath,
    MetaRevision,
    Metric,
    SchemaEmbedding,
    Synonym,
    TableMeta,
)
from app.infra.models.user import DataScope, Role, User

__all__ = [
    "AuditLog",
    "Base",
    "ColumnMeta",
    "Conversation",
    "DataScope",
    "Datasource",
    "EnumDict",
    "FewShot",
    "JoinPath",
    "Message",
    "MetaRevision",
    "Metric",
    "QueryHistory",
    "Role",
    "RowPolicy",
    "SchemaEmbedding",
    "Synonym",
    "SysConfig",
    "TableMeta",
    "User",
]
