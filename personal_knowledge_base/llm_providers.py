"""LLM 多厂商统一调用层：基于 LiteLLM 的 Provider 适配与降级。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Generator

import requests


@dataclass
class ProviderConfig:
    """供应商调用配置快照，用于工厂创建和缓存隔离 Provider 实例。"""

    base_url: str
    api_key: str
    model_name: str
    provider_name: str = "openai"
    model_type: str = "KnowledgeQA"
    model_id: str = ""
    dimension: int | None = None
    timeout: int = 60
    batch_size: int = 32
    max_candidates: int | None = None
    fallback_priority: int = 0
    num_retries: int = 2
    litellm_model_name: str = ""

    def signature(self) -> str:
        """计算配置签名；签名变化时工厂缓存自动失效。"""
        parts = [
            self.base_url,
            self.api_key,
            self.model_name,
            self.provider_name,
            str(self.dimension),
            str(self.timeout),
            str(self.num_retries),
            self.litellm_model_name,
        ]
        raw = "|".join(parts)
        return hashlib.md5(raw.encode()).hexdigest()

    def api_base(self, endpoint: str = "") -> str:
        """LiteLLM 的 api_base 需要根路径，不能带 /chat/completions 或 /embeddings。"""
        base = (self.base_url or "").rstrip("/")
        suffixes = [endpoint, "/chat/completions", "/embeddings"]
        for suffix in suffixes:
            if suffix and base.endswith(suffix):
                return base[: -len(suffix)].rstrip("/")
        return base

    def litellm_model(self) -> str:
        """把业务 Provider 配置映射为 LiteLLM model 字符串。"""
        if self.litellm_model_name:
            return self.litellm_model_name
        if self.base_url:
            return f"openai/{self.model_name}"
        if "/" in self.model_name:
            return self.model_name
        prefix = {
            "openai": "openai",
            "deepseek": "deepseek",
            "aliyun-bailian": "dashscope",
            "qwen": "dashscope",
            "zhipu": "zhipu",
            "ollama": "ollama",
            "gemini": "gemini",
        }.get(self.provider_name)
        return f"{prefix}/{self.model_name}" if prefix else self.model_name


def _load_litellm():
    try:
        import litellm
    except ImportError as exc:
        raise RuntimeError("LiteLLM is not installed. Install project requirements before calling LLM providers.") from exc
    return litellm


def _to_plain_response(value):
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if hasattr(value, "json"):
        return json.loads(value.json())
    return dict(value)


def _drop_none(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in kwargs.items() if value is not None}


def _litellm_completion(
    config: ProviderConfig,
    messages: list[dict],
    *,
    stream: bool = False,
    tools: list[dict] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    enable_thinking: bool | None = None,
    total_timeout: int | None = None,
):
    litellm = _load_litellm()
    timeout = config.timeout
    if total_timeout:
        timeout = min(config.timeout, int(total_timeout))
    kwargs = _drop_none(
        {
            "model": config.litellm_model(),
            "messages": messages,
            "api_key": config.api_key or None,
            "api_base": config.api_base("/chat/completions") or None,
            "timeout": timeout,
            "num_retries": max(int(config.num_retries or 0), 0),
            "stream": stream,
            "tools": tools,
            "temperature": temperature,
            "max_tokens": int(max_tokens) if max_tokens is not None else None,
            "enable_thinking": bool(enable_thinking) if enable_thinking is not None else None,
            "drop_params": True,
        }
    )
    response = litellm.completion(**kwargs)
    if stream:
        return (_to_plain_response(chunk) for chunk in response)
    return _to_plain_response(response)


def _litellm_embedding(config: ProviderConfig, texts: list[str]) -> dict:
    litellm = _load_litellm()
    response = litellm.embedding(
        **_drop_none(
            {
                "model": config.litellm_model(),
                "input": texts,
                "api_key": config.api_key or None,
                "api_base": config.api_base("/embeddings") or None,
                "timeout": config.timeout,
                "num_retries": max(int(config.num_retries or 0), 0),
                "drop_params": True,
            }
        )
    )
    return _to_plain_response(response)


class BaseLLMProvider:
    """供应商抽象基类：Chat/Embedding 走 LiteLLM，Rerank 保留 HTTP 调用。"""

    provider_name: str = "base"
    display_name: str = "Base"
    supported_types: tuple[str, ...] = ("chat",)

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    @property
    def session(self) -> requests.Session:
        return self._session

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _rerank_url(self) -> str:
        return f"{self.config.base_url.rstrip('/')}/rerank"

    def chat(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        enable_thinking: bool | None = None,
        total_timeout: int | None = None,
    ) -> dict:
        """非流式 Chat 调用，返回统一 OpenAI-compatible 响应 JSON。"""
        return _litellm_completion(
            self.config,
            messages,
            stream=False,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            enable_thinking=enable_thinking,
            total_timeout=total_timeout,
        )

    def chat_stream(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float | None = None,
    ) -> Generator[dict, None, None]:
        """流式 Chat 调用，逐 chunk yield 统一响应片段。"""
        yield from _litellm_completion(
            self.config,
            messages,
            stream=True,
            tools=tools,
            temperature=temperature,
        )

    def embedding(self, texts: list[str]) -> list[list[float]]:
        """Embedding 调用，返回向量列表。"""
        data = _litellm_embedding(self.config, texts)
        return [item["embedding"] for item in data.get("data", [])]

    def rerank(self, query: str, documents: list[str]) -> dict:
        """POST /rerank，返回原始响应 JSON。"""
        url = self._rerank_url()
        resp = self._session.post(
            url, headers=self._build_headers(),
            json={"model": self.config.model_name, "query": query, "documents": documents},
            timeout=self.config.timeout,
        )
        resp.raise_for_status()
        return resp.json()


class OpenAIProvider(BaseLLMProvider):
    provider_name = "openai"
    display_name = "OpenAI Compatible"
    supported_types = ("chat", "embedding", "rerank", "vlm")


class DeepSeekProvider(BaseLLMProvider):
    provider_name = "deepseek"
    display_name = "DeepSeek"
    supported_types = ("chat",)


class BailianProvider(BaseLLMProvider):
    provider_name = "aliyun-bailian"
    display_name = "阿里云百炼"
    supported_types = ("chat", "embedding", "rerank", "vlm")


class QwenProvider(BaseLLMProvider):
    provider_name = "qwen"
    display_name = "Qwen"
    supported_types = ("chat", "embedding")


class ZhipuProvider(BaseLLMProvider):
    provider_name = "zhipu"
    display_name = "Zhipu"
    supported_types = ("chat", "embedding", "rerank")


_BUILTIN_PROVIDERS: dict[str, type[BaseLLMProvider]] = {
    "openai": OpenAIProvider,
    "deepseek": DeepSeekProvider,
    "aliyun-bailian": BailianProvider,
    "qwen": QwenProvider,
    "zhipu": ZhipuProvider,
    "ollama": OpenAIProvider,
    "gemini": OpenAIProvider,
}

_DISPLAY_INFO: dict[str, dict] = {
    "openai": {"name": "openai", "display_name": "OpenAI Compatible", "types": ["chat", "embedding", "rerank", "vlm"]},
    "deepseek": {"name": "deepseek", "display_name": "DeepSeek", "types": ["chat"]},
    "aliyun-bailian": {"name": "aliyun-bailian", "display_name": "阿里云百炼", "types": ["chat", "embedding", "rerank", "vlm"]},
    "qwen": {"name": "qwen", "display_name": "Qwen", "types": ["chat", "embedding"]},
    "zhipu": {"name": "zhipu", "display_name": "Zhipu", "types": ["chat", "embedding", "rerank"]},
    "ollama": {"name": "ollama", "display_name": "Ollama", "types": ["chat", "embedding"]},
    "gemini": {"name": "gemini", "display_name": "Gemini", "types": ["chat", "embedding", "vlm"]},
}


class ProviderFactory:
    """Provider 工厂：注册、路由与缓存隔离。"""

    def __init__(self) -> None:
        self._registry: dict[str, type[BaseLLMProvider]] = {}
        self._cache: dict[str, tuple[str, BaseLLMProvider]] = {}
        for name, cls in _BUILTIN_PROVIDERS.items():
            self.register(name, cls)

    def register(self, name: str, cls: type[BaseLLMProvider]) -> None:
        self._registry[name] = cls

    def list_providers(self) -> list[str]:
        return list(self._registry.keys())

    def create(self, config: ProviderConfig) -> BaseLLMProvider:
        """按 config.provider_name 从注册表路由创建实例。未知供应商回退到 OpenAI。"""
        cls = self._registry.get(config.provider_name, OpenAIProvider)
        return cls(config)

    def get_or_create(self, cache_key: str, config: ProviderConfig) -> BaseLLMProvider:
        """查缓存 → 签名匹配则复用，否则创建新实例并缓存。"""
        sig = config.signature()
        cached = self._cache.get(cache_key)
        if cached and cached[0] == sig:
            return cached[1]
        provider = self.create(config)
        self._cache[cache_key] = (sig, provider)
        return provider

    def invalidate_key(self, cache_key: str) -> None:
        self._cache.pop(cache_key, None)

    def invalidate_tenant(self, tenant_id: str) -> None:
        prefix = f"{tenant_id}:"
        for key in [k for k in self._cache if k.startswith(prefix)]:
            self._cache.pop(key, None)

    def clear_cache(self) -> None:
        self._cache.clear()

def provider_display_list() -> list[dict]:
    """供 model_providers.provider_types() 调用，返回展示信息。"""
    result: list[dict] = []
    seen: set[str] = set()
    for name, info in _DISPLAY_INFO.items():
        if name not in seen:
            result.append(info)
            seen.add(name)
    return result


factory = ProviderFactory()
