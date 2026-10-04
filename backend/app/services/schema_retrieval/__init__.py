"""Schema 检索服务包：混合检索（向量 + 关键词，FR-SCH-21/22）。"""

from app.services.schema_retrieval.hybrid_scorer import fuse_scores

__all__ = ["fuse_scores"]
