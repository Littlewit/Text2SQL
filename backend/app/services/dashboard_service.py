"""运营监控看板聚合服务（FR-ADM-06、M2-T5）。

从 query_history 聚合：查询量/成功率/耗时分布/重试率/token 用量/Top 失败原因/高频问题。
窗口天数由前端传入（默认 7 天）；数据与历史页同源，保证一致性。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import QueryHistory


def _bucket(ms: int | None) -> str:
    """耗时毫秒 → 分桶标签。"""
    if ms is None:
        return ">10s"
    for bound, label in ((1000, "<1s"), (3000, "1~3s"), (10000, "3~10s")):
        if ms < bound:
            return label
    return ">10s"


async def get_dashboard(db: AsyncSession, days: int = 7) -> dict:
    """聚合近 N 天查询运营指标。"""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    histories = (
        await db.execute(
            select(QueryHistory).where(
                QueryHistory.created_at >= since, QueryHistory.is_deleted.is_(False)
            )
        )
    ).scalars().all()

    total = len(histories)
    by_status: dict[str, int] = {}
    durations: list[int] = []
    buckets: dict[str, int] = {"<1s": 0, "1~3s": 0, "3~10s": 0, ">10s": 0}
    retries = 0
    tokens = 0
    by_day: dict[str, dict[str, int]] = {}
    question_cnt: dict[str, int] = {}
    fail_cnt: dict[str, int] = {}

    for h in histories:
        by_status[h.exec_status] = by_status.get(h.exec_status, 0) + 1
        if h.duration_ms is not None:
            durations.append(h.duration_ms)
            buckets[_bucket(h.duration_ms)] += 1
        if h.retry_count and h.retry_count > 0:
            retries += 1
        tokens += h.llm_tokens or 0
        day = (h.created_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
        d = by_day.setdefault(day, {"total": 0, "success": 0})
        d["total"] += 1
        d["success"] += 1 if h.exec_status == "success" else 0
        question_cnt[h.question] = question_cnt.get(h.question, 0) + 1
        if h.exec_status in ("failed", "timeout") and h.error_code:
            fail_cnt[str(h.error_code)] = fail_cnt.get(str(h.error_code), 0) + 1

    return {
        "days": days,
        "summary": {
            "total": total,
            "success": by_status.get("success", 0),
            "success_rate": round(by_status.get("success", 0) / total, 4) if total else 0,
            "clarify": by_status.get("clarify", 0),
            "refused": by_status.get("refused", 0),
            "retry_rate": round(retries / total, 4) if total else 0,
            "avg_duration_ms": int(sum(durations) / len(durations)) if durations else 0,
            "llm_tokens": tokens,
        },
        "duration_buckets": buckets,
        "by_day": [{"day": k, **v} for k, v in sorted(by_day.items())],
        "top_questions": sorted(question_cnt.items(), key=lambda x: -x[1])[:10],
        "top_failures": sorted(fail_cnt.items(), key=lambda x: -x[1])[:10],
    }
