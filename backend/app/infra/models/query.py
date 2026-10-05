"""查询链路模型：会话/消息/查询历史/Few-shot 样例/行级权限策略（§5.1）。"""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.infra.models.base import Base, IntPkMixin


class Conversation(IntPkMixin, Base):
    """会话。context 存最近生效条件摘要，支撑多轮上下文继承（FR-NLU-24、§3.3）。"""

    __tablename__ = "conversation"

    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    title: Mapped[str | None] = mapped_column(String(256))
    context: Mapped[dict | None] = mapped_column(JSON)  # {time_range, filters, last_sql,...}
    status: Mapped[int] = mapped_column(SmallInteger, default=1)


class Message(Base):
    """会话消息流（FR-UI-01 对话呈现的数据源）。"""

    __tablename__ = "message"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("conversation.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user / assistant
    content: Mapped[dict] = mapped_column(JSON)  # 文本与结果引用的结构化载荷
    seq: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QueryHistory(IntPkMixin, Base):
    """查询历史：完整还原一次查询的全过程（FR-HIS-01、FR-SCH-24、FR-HIS-08）。

    只存结果摘要与前 N 行样例，不存完整结果集（DR-02）。
    """

    __tablename__ = "query_history"

    conversation_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    question: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(32))
    entities: Mapped[dict | None] = mapped_column(JSON)  # 实体抽取结果（FR-NLU-04）
    recalled_schema: Mapped[dict | None] = mapped_column(JSON)  # Schema 召回明细（FR-SCH-24）
    prompt_template_version: Mapped[str | None] = mapped_column(String(64))  # 模板版本（FR-NLU-23）
    generated_sql: Mapped[str | None] = mapped_column(Text)
    explain_text: Mapped[str | None] = mapped_column(Text)  # 自然语言解释（FR-SQL-34）
    assumptions: Mapped[dict | None] = mapped_column(JSON)  # 口径假设声明（NFR-A-05）
    validate_result: Mapped[dict | None] = mapped_column(JSON)  # 校验结果（FR-SQL-15）
    exec_status: Mapped[str] = mapped_column(String(32))  # success/failed/timeout/clarify/refused
    error_code: Mapped[int | None] = mapped_column(BigInteger)
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    result_sample: Mapped[dict | None] = mapped_column(JSON)  # 前 N 行样例（DR-02）
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    llm_tokens: Mapped[int | None] = mapped_column(BigInteger)  # token 用量（FR-SEC-33）
    chart_config: Mapped[dict | None] = mapped_column(JSON)
    retry_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)  # 逻辑删除（DR-06）


class FewShot(IntPkMixin, Base):
    """Few-shot 样例库（FR-NLU-21、FR-ADM-04）：问题→标准 SQL，供动态召回。"""

    __tablename__ = "few_shot"

    datasource_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    question: Mapped[str] = mapped_column(Text)
    sql_text: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(32))
    explanation: Mapped[str | None] = mapped_column(Text)
    status: Mapped[int] = mapped_column(SmallInteger, default=1)  # 1=启用
    embedding = mapped_column(Vector(get_settings().embedding_dim))
    model_version: Mapped[str] = mapped_column(String(64))
    hit_count: Mapped[int] = mapped_column(BigInteger, default=0)


class RowPolicy(Base):
    """行级权限策略（FR-SEC-10/12）：模板在 SQL 改写阶段强制注入（FR-SEC-11）。"""

    __tablename__ = "row_policy"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    datasource_id: Mapped[int] = mapped_column(BigInteger, index=True)
    table_meta_id: Mapped[int] = mapped_column(BigInteger)
    filter_template: Mapped[str] = mapped_column(Text)  # SQL 片段，如 region = '华东'
    apply_to_role_ids: Mapped[dict | list] = mapped_column(JSON)  # 角色编码列表
    combine_mode: Mapped[str] = mapped_column(String(8), default="union")  # union/intersect
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
