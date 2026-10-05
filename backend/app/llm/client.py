"""LLM 适配层（§6.1）：统一协议 + OpenAI 兼容实现 + Fake 实现 + 简易熔断。

- 零信任原则：LLM 输出视为不可信输入，调用方必须校验（FR-SEC-05）；
- Prompt 内容约束（CMP-02）由 Prompt 组装器保证，适配层不感知业务；
- 熔断：连续错误超阈值进入 OPEN 状态，冷却后半开（FR-SEC-34，生产可换 Redis 计数）。
"""

import time
from typing import Protocol

import httpx
from pydantic import BaseModel

from app.core.config import get_settings  # noqa: F401 —— get_llm 使用


class LLMResult(BaseModel):
    content: str
    tokens: int = 0


class LLMClient(Protocol):
    model_version: str

    async def chat(self, messages: list[dict], json_mode: bool = False) -> LLMResult: ...


class OpenAICompatibleLLM:
    """OpenAI /chat/completions 协议实现（DeepSeek 兼容）。"""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.model_version = model
        self._timeout = timeout

    async def chat(self, messages: list[dict], json_mode: bool = False) -> LLMResult:
        body: dict = {
            "model": self.model_version,
            "messages": messages,
            "temperature": 0.0,  # Text2SQL 需要确定性输出
            "max_tokens": 2048,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            return LLMResult(
                content=data["choices"][0]["message"]["content"],
                tokens=data.get("usage", {}).get("total_tokens", 0),
            )


class FakeLLM:
    """确定性 LLM 替身（测试/开发）：按 prompt 标记路由到预设响应。

    usage: fake.routes["<标记>"] = "<响应文本>"；未命中标记时按队列弹出。
    """

    def __init__(self, routes: dict[str, str] | None = None, queue: list[str] | None = None):
        self.routes = routes or {}
        self.queue = list(queue or [])
        self.model_version = "fake"
        self.calls: list[str] = []

    async def chat(self, messages: list[dict], json_mode: bool = False) -> LLMResult:
        # 扫描全部消息内容做标记匹配（错误回灌重试时标记不在最后一条）
        text = "\n".join(m.get("content", "") for m in messages)
        self.calls.append(text)
        for marker, resp in self.routes.items():
            if marker in text:
                return LLMResult(content=resp)
        if self.queue:
            return LLMResult(content=self.queue.pop(0))
        raise RuntimeError("FakeLLM: no route matched and queue empty")


class CircuitBreaker:
    """简易熔断器：连续失败 ≥ 阈值则 OPEN，冷却后半开尝试（FR-SEC-34）。"""

    def __init__(self, threshold: int = 5, cooldown_s: float = 30.0):
        self._threshold = threshold
        self._cooldown = cooldown_s
        self._fails = 0
        self._opened_at: float | None = None

    def allow(self) -> bool:
        if self._opened_at is None:
            return True
        if time.monotonic() - self._opened_at >= self._cooldown:
            self._opened_at = None  # 半开：放行一次尝试
            return True
        return False

    def record_success(self) -> None:
        self._fails = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._fails += 1
        if self._fails >= self._threshold:
            self._opened_at = time.monotonic()


_breaker = CircuitBreaker()


def reset_breaker() -> None:
    """测试/运维辅助：复位熔断器状态。"""
    _breaker.record_success()

# FakeLLM 单例：未配置 API Key 时全局复用，测试可注入路由（见 set_fake_routes）
_fake_llm = FakeLLM()


def set_fake_routes(routes: dict[str, str]) -> None:
    """测试辅助：为 FakeLLM 注入按标记路由的预设响应。"""
    _fake_llm.routes.update(routes)


def clear_fake_routes() -> None:
    """测试辅助：清空 FakeLLM 路由与队列。"""
    _fake_llm.routes.clear()
    _fake_llm.queue.clear()


def get_llm() -> LLMClient:
    """按配置返回 LLM 客户端；未配置 API Key 时返回 FakeLLM（仅限开发/测试）。"""
    settings = get_settings()
    if settings.llm_api_key:
        return OpenAICompatibleLLM(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout=settings.llm_timeout_s,
        )
    return _fake_llm


async def chat_with_breaker(llm: LLMClient, messages: list[dict], json_mode: bool = False) -> LLMResult:
    """带熔断的 LLM 调用入口：OPEN 状态快速失败，避免请求挂起（FR-SEC-34）。"""
    if not _breaker.allow():
        raise RuntimeError("LLM circuit breaker is OPEN")
    try:
        result = await llm.chat(messages, json_mode=json_mode)
    except Exception:
        _breaker.record_failure()
        raise
    _breaker.record_success()
    return result
