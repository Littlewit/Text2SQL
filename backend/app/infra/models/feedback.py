"""用户反馈模型（FR-UI-08、§5.1 feedback）。

反馈是数据质量闭环的入口：赞踩/纠错 → 数据管理员审核 → 转入 Few-shot 样例库（R-10）。
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.models.base import Base


class Feedback(Base):
    """对某次查询结果的反馈：rating=up/down，纠错可附正确 SQL。

    review_status: pending（待审核）/ approved（已采纳）/ rejected（已驳回）。
    采纳后由服务自动创建 Few-shot 样例（记录 sample_id 便于追溯）。
    """

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    query_history_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("query_history.id"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    rating: Mapped[str] = mapped_column(String(8))  # up / down
    correction_sql: Mapped[str | None] = mapped_column(Text)  # 用户提供的正确 SQL（纠错）
    comment: Mapped[str | None] = mapped_column(Text)  # 文字说明
    review_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    reviewer_id: Mapped[int | None] = mapped_column(BigInteger)
    sample_id: Mapped[int | None] = mapped_column(BigInteger)  # 采纳后生成的样例 ID
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
