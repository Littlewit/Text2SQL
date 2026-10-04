"""Schema 检索器：给定用户问题，返回 Top-K 相关表/字段/指标（FR-SCH-21/22/24）。

检索结果带得分与命中详情，供 T3 Prompt 组装与 query_history.recalled_schema 可解释落库。
"""

from dataclasses import asdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.embedding import EmbeddingClient, content_to_json
from app.services.schema_retrieval.hybrid_scorer import (
    DEFAULT_KEYWORD_WEIGHT,
    DEFAULT_VECTOR_WEIGHT,
    Candidate,
    fuse_scores,
    keyword_score,
)


def tokenize(query: str) -> list[str]:
    """中文分词的轻量替代：按标点/空白切分后取 2-gram + 原词。

    足够支撑字面精确命中（字段英文名、指标名），语义部分交给向量。
    """
    import re

    words = [w for w in re.split(r"[\s，。？、！,\.?\!]+", query) if w]
    tokens: list[str] = []
    for w in words:
        tokens.append(w)
        if len(w) > 2:
            tokens.extend(w[i : i + 2] for i in range(len(w) - 1))
    return list(dict.fromkeys(tokens))  # 去重保序


async def search(
    db: AsyncSession,
    embedder: EmbeddingClient,
    query: str,
    datasource_id: int | None = None,
    top_k: int = 10,
    vector_weight: float = DEFAULT_VECTOR_WEIGHT,
    keyword_weight: float = DEFAULT_KEYWORD_WEIGHT,
) -> list[Candidate]:
    """混合检索：pgvector cosine Top-50 ∪ 关键词命中，融合打分后取 Top-K。

    仅返回 datasource 范围内（FR-SCH-03 候选池约束由向量行与元数据归属保证）。
    """
    tokens = tokenize(query)
    qvec = (await embedder.embed([query]))[0]
    vec_literal = content_to_json(qvec)

    # 1) 向量召回 Top-50（cosine 相似度）
    sql = text(
        """
        SELECT object_type, object_id, content_text,
               1 - (embedding <=> CAST(:qvec AS vector)) AS sim
        FROM schema_embedding
        WHERE (:ds_id IS NULL OR datasource_id = :ds_id)
        ORDER BY embedding <=> CAST(:qvec AS vector)
        LIMIT 50
        """
    )
    rows = (
        await db.execute(sql, {"qvec": vec_literal, "ds_id": datasource_id})
    ).fetchall()

    # 2) 关键词命中：从元数据表取全部候选的字面信息（元数据量级小，全量可行）
    kw_rows = (
        await db.execute(
            text(
                """
                SELECT 'table' AS object_type, tm.id AS object_id,
                       concat_ws(' ', tm.cn_name, tm.description) AS content_text,
                       tm.table_name AS field_name, tm.datasource_id
                FROM table_meta tm
                UNION ALL
                SELECT 'column', cm.id, concat_ws(' ', cm.cn_name, cm.description, cm.column_name),
                       cm.column_name, tm.datasource_id
                FROM column_meta cm JOIN table_meta tm ON tm.id = cm.table_meta_id
                UNION ALL
                SELECT 'metric', m.id, concat_ws(' ', m.name, m.description, m.code), m.code, m.datasource_id
                FROM metric m
                UNION ALL
                SELECT 'synonym', s.id, s.term, s.term, s.datasource_id
                FROM synonym s
                """
            )
        )
    ).fetchall()

    # 3) 融合打分
    candidates: dict[tuple[str, int], Candidate] = {}
    for r in rows:
        key = (r.object_type, r.object_id)
        candidates[key] = Candidate(
            object_type=r.object_type,
            object_id=r.object_id,
            content_text=r.content_text or "",
            vector_sim=float(r.sim),
        )
    for r in kw_rows:
        if datasource_id is not None and r.datasource_id not in (None, datasource_id):
            continue  # 数据源范围过滤（FR-SCH-03）
        key = (r.object_type, r.object_id)
        kw = keyword_score(tokens, r.content_text or "", [r.field_name] if r.field_name else [])
        if key in candidates:
            candidates[key].keyword_score = kw
        elif kw > 0:
            candidates[key] = Candidate(
                object_type=r.object_type,
                object_id=r.object_id,
                content_text=r.content_text or "",
                keyword_score=kw,
            )

    for c in candidates.values():
        c.score = fuse_scores(c.vector_sim, c.keyword_score, vector_weight, keyword_weight)

    ranked = sorted(candidates.values(), key=lambda c: c.score, reverse=True)
    return ranked[:top_k]


def to_explainable(results: list[Candidate]) -> list[dict]:
    """检索结果 → 可解释 JSON（FR-SCH-24：记录候选、得分与选中项）。"""
    return [asdict(c) for c in results]
