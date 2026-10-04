"""Embedding 适配层（§6.2、NFR-M-02 可替换）。

- OpenAICompatibleEmbedder：OpenAI /embeddings 协议（DeepSeek/SiliconFlow/私有化网关均兼容）；
- HashEmbedder：无外部依赖的确定性向量化，仅供本地开发/测试验证 pgvector 链路，
  不是检索降级方案（检索本身仍走 pgvector，DR-07）；生产必须配置真实模型。

模型与维度通过配置注入；维度变更须全量重建向量并记录版本（DR-04）。
"""

import hashlib
import json
import math
from typing import Protocol

import httpx

from app.core.config import get_settings


class EmbeddingClient(Protocol):
    """Embedding 客户端协议。"""

    model_version: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAICompatibleEmbedder:
    """调用 OpenAI 兼容 /embeddings 端点。"""

    def __init__(self, base_url: str, api_key: str, model: str):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.model_version = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self._base_url}/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self.model_version, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            # 按 index 排序，保证输入输出顺序一致
            return [item["embedding"] for item in sorted(data, key=lambda x: x["index"])]


class HashEmbedder:
    """确定性哈希向量化（dev/test 用）：把文本分词哈希进固定维度向量并归一化。

    特点：同文本必同向量（可重复测试）、语义无关（仅验证链路，不提供语义召回质量）。
    """

    def __init__(self, dim: int):
        self._dim = dim
        self.model_version = f"hash-{dim}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        # 按字符 bigram 分词（对中文友好），每 gram 哈希到固定桶
        tokens = [text[i : i + 2] for i in range(max(len(text) - 1, 1))]
        for tok in tokens:
            h = int.from_bytes(hashlib.md5(tok.encode("utf-8")).digest()[:8], "big")
            idx = h % self._dim
            sign = 1.0 if (h >> 63) % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def get_embedder() -> EmbeddingClient:
    """按配置返回 Embedding 客户端；未配置模型时使用 HashEmbedder（仅限开发/测试）。"""
    settings = get_settings()
    if settings.embedding_model:
        return OpenAICompatibleEmbedder(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.embedding_model,
        )
    return HashEmbedder(dim=settings.embedding_dim)


def content_to_json(vec: list[float]) -> str:
    """向量 → pgvector 文本字面量（如 '[0.1,0.2,...]'），用于原生 SQL 绑定。"""
    return json.dumps([round(v, 6) for v in vec])
