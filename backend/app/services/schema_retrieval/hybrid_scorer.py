"""混合检索打分（FR-SCH-22）。

score = w_v * cosine_sim + w_k * keyword_score（权重可配，sys_config: schema.hybrid_weights）
纯函数实现，便于单元测试覆盖权重组合与排序语义。
"""

from dataclasses import dataclass

# 默认权重：关键词精确命中权重较高，避免纯语义检索漏掉字面精确匹配
DEFAULT_VECTOR_WEIGHT = 0.6
DEFAULT_KEYWORD_WEIGHT = 0.4


@dataclass
class Candidate:
    """检索候选：一次查询的命中对象。"""

    object_type: str  # table / column / metric / synonym
    object_id: int
    content_text: str
    vector_sim: float = 0.0
    keyword_score: float = 0.0
    score: float = 0.0


def keyword_score(query_tokens: list[str], content_text: str, field_names: list[str] | None = None) -> float:
    """关键词得分：命中内容文本或字段名字面。

    - 完整词包含命中 1.0；部分 gram 命中按比例；
    - 上限 1.0，无命中为 0。
    """
    if not query_tokens:
        return 0.0
    haystacks = [content_text] + (field_names or [])
    hits = 0
    for tok in query_tokens:
        if any(tok in h for h in haystacks if h):
            hits += 1
    return min(hits / len(query_tokens), 1.0)


def fuse_scores(
    vector_sim: float,
    kw_score: float,
    vector_weight: float = DEFAULT_VECTOR_WEIGHT,
    keyword_weight: float = DEFAULT_KEYWORD_WEIGHT,
) -> float:
    """融合向量相似度与关键词得分。"""
    return vector_weight * vector_sim + keyword_weight * kw_score
