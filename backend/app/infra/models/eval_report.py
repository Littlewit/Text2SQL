"""评测报告模型（FR-ADM-07、M2-T6）：每次评测运行一行，支持历史对比。"""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.models.base import Base


class EvalReportRun(Base):
    """评测运行记录：触发（offline/full）→ running → done/failed。"""

    __tablename__ = "eval_report"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(16))  # offline / full
    status: Mapped[str] = mapped_column(String(16), default="running")
    total: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    pass_rate: Mapped[float] = mapped_column(Float, default=0.0)
    by_tag: Mapped[dict | None] = mapped_column(JSON)  # 分维度统计
    failures: Mapped[dict | list | None] = mapped_column(JSON)  # 失败明细（截断）
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    model_version: Mapped[str | None] = mapped_column(String(64))
    operator_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
