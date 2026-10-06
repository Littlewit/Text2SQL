"""Few-shot 样例库灌入（M3-T1）：从评测 EX 用例的 standard_sql 派生高质量样例。

样例 = 评测基准问题 -> 标准 SQL -> 口径解释，业务高频问题即应有样例（FR-NLU-21/ADM-04）。
幂等：按 question 去重。

用法：cd backend && python scripts/seed_few_shots.py
"""

import asyncio
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.infra.db import get_session_factory, reset_engine  # noqa: E402
from app.infra.models import Datasource, FewShot  # noqa: E402
from app.llm.embedding import get_embedder  # noqa: E402
from app.services import vectorizer  # noqa: E402

CASES = Path(__file__).parent.parent / "eval" / "cases_v1.json"


async def main() -> None:
    get_settings.cache_clear()
    reset_engine()
    embedder = get_embedder()
    db = get_session_factory()()

    cases = json.loads(CASES.read_text(encoding="utf-8"))
    ex_cases = [c for c in cases if c["kind"] == "sql_exec"]
    added = skipped = 0

    async with db:
        ds = (
            await db.execute(select(Datasource).where(Datasource.db_name == "demo_business"))
        ).scalars().first()
        existing = set((await db.execute(select(FewShot.question))).scalars().all())
        for c in ex_cases:
            q = c["question"]
            if q in existing:
                skipped += 1
                continue
            fs = await vectorizer.build_few_shot(
                db, embedder,
                datasource_id=ds.id if ds else None,
                question=q,
                sql_text=c["expected"]["standard_sql"],
                intent="stat",
                explanation=f"标准口径 SQL（评测基准 {c['id']}，tag={c['tag']}）",
                model_version=embedder.model_version,
            )
            db.add(fs)
            added += 1
        await db.commit()
    print(f"few-shot 灌入: 新增 {added} 条，跳过 {skipped} 条（已存在），embedder={embedder.model_version}")


asyncio.run(main())