"""
LLM 多厂商统一调用层 — Provider 工厂管理机制。

基于 AgenticX 架构理念，将 OpenAI、DeepSeek、百炼(DashScope)、Qwen、Zhipu 等
供应商收敛为统一的 Provider 抽象，通过工厂路由实现运行时模型切换、实例隔离与失败降级。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Generator

import requests

logger = logging.getLogger(__name__)


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

    _sig_fields = ("base_url", "api_key", "model_name", "provider_name", "dimension", "timeout")

    def signature(self) -> str:
        """计算配置签名；签名变化时工厂缓存自动失效。"""
        parts = [
            self.base_url,
            self.api_key,
            self.model_name,
            self.provider_name,
            str(self.dimension),
            str(self.timeout),
        ]
        raw = "|".join(parts)
        return hashlib.md5(raw.encode()).hexdigest()


class BaseLLMProvider:
    """供应商抽象基类：封装 OpenAI 兼容 HTTP 调用，每个实例持有独立的 requests.Session。"""

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

    def _chat_url(self) -> str:
        url = self.config.base_url.rstrip("/")
        return url if url.endswith("/chat/completions") else f"{url}/chat/completions"

    def _embedding_url(self) -> str:
        url = self.config.base_url.rstrip("/")
        return url if url.endswith("/embeddings") else f"{url}/embeddings"

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
        """POST /chat/completions（非流式），返回完整响应 JSON。"""
        url = self._chat_url()
        body: dict[str, Any] = {"model": self.config.model_name, "messages": messages, "stream": False}
        if tools:
            body["tools"] = tools
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = int(max_tokens)
        if enable_thinking is not None:
            body["enable_thinking"] = bool(enable_thinking)
        timeout = self.config.timeout
        if total_timeout:
            timeout = min(self.config.timeout, int(total_timeout))
        resp = self._session.post(url, headers=self._build_headers(), json=body, timeout=timeout, stream=bool(total_timeout))
        resp.raise_for_status()
        return resp.json()

    def chat_stream(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float | None = None,
    ) -> Generator[dict, None, None]:
        """POST /chat/completions（流式），逐 chunk yield 解析后的 JSON。"""
        url = self._chat_url()
        body: dict[str, Any] = {"model": self.config.model_name, "messages": messages, "stream": True}
        if tools:
            body["tools"] = tools
        if temperature is not None:
            body["temperature"] = temperature
        resp = self._session.post(
            url, headers=self._build_headers(), json=body, timeout=self.config.timeout, stream=True,
        )
        resp.raise_for_status()
        buffer = ""
        for chunk in resp.iter_content(chunk_size=None):
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        return
                    try:
                        yield json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

    def embedding(self, texts: list[str]) -> list[list[float]]:
        """POST /embeddings，返回向量列表。"""
        url = self._embedding_url()
        resp = self._session.post(
            url, headers=self._build_headers(),
            json={"model": self.config.model_name, "input": texts},
            timeout=self.config.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
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
    """Provider 工厂：注册、路由、缓存隔离与失败降级。"""

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

    def get_fallback_chain(self, models: list) -> list[BaseLLMProvider]:
        """按 fallback_priority 降序排列模型，返回 Provider 实例列表。"""
        ordered = sorted(
            [m for m in models if getattr(m, "fallback_priority", 0) > 0],
            key=lambda m: getattr(m, "fallback_priority", 0),
            reverse=True,
        )
        chain: list[BaseLLMProvider] = []
        for model in ordered:
            cfg = _model_to_config(model)
            if cfg:
                chain.append(self.get_or_create(f"{model.tenant_id}:{model.id}", cfg))
        return chain

    def chat_with_fallback(
        self, tenant, messages: list[dict], model_id: str = "",
    ) -> dict:
        """带失败降级的 chat 调用：主模型失败后依次尝试同类型备用模型。"""
        from .model_providers import ModelConfigurationError
        from .models import ModelConfig

        primary = ModelConfig.objects.filter(id=model_id, tenant=tenant, deleted_at__isnull=True).first() if model_id else None
        if not primary:
            raise ModelConfigurationError(f"No model found for id={model_id}")

        primary_cfg = _model_to_config(primary)
        if not primary_cfg:
            raise ModelConfigurationError(f"Model {model_id} has no valid base_url")

        primary_provider = self.get_or_create(f"{tenant.id}:{model_id}", primary_cfg)

        siblings = ModelConfig.objects.filter(
            tenant=tenant, type=primary.type, deleted_at__isnull=True, status="active",
        ).exclude(id=model_id)
        chain = self.get_fallback_chain(list(siblings))

        errors: list[str] = []
        attempts = [(model_id, primary_provider)] + [
            (p.config.model_id or p.config.model_name, p) for p in chain
        ]

        for i, (attempt_id, provider) in enumerate(attempts):
            try:
                data = provider.chat(messages)
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                result: dict[str, Any] = {
                    "content": content,
                    "tool_calls": data.get("choices", [{}])[0].get("message", {}).get("tool_calls"),
                    "finish_reason": data.get("choices", [{}])[0].get("finish_reason"),
                }
                if i > 0:
                    result["degradation_info"] = {
                        "from_model": model_id,
                        "to_model": str(attempt_id),
                        "reason": errors[-1] if errors else "primary model failed",
                    }
                return result
            except Exception as exc:
                errors.append(f"{attempt_id}: {exc}")
                logger.warning("Provider %s failed: %s", attempt_id, exc)
                continue

        raise ModelConfigurationError(
            f"All models failed in fallback chain: {'; '.join(errors)}"
        )


def _model_to_config(model) -> ProviderConfig | None:
    """从 ModelConfig ORM 对象解析出 ProviderConfig。"""
    params = model.parameters or {}
    base_url = (params.get("base_url") or params.get("baseURL") or "").rstrip("/")
    if not base_url:
        return None
    api_key = params.get("api_key") or params.get("apiKey") or params.get("token") or ""
    model_name = params.get("model") or model.name
    provider_name = model.source or "openai"

    def _int(key, default=None):
        try:
            return int(params.get(key)) if params.get(key) not in (None, "") else default
        except (TypeError, ValueError):
            return default

    return ProviderConfig(
        base_url=base_url,
        api_key=api_key,
        model_name=model_name,
        provider_name=provider_name,
        model_type=getattr(model, "type", "KnowledgeQA"),
        model_id=model.id,
        dimension=_int("dimension"),
        timeout=_int("timeout", 60),
        batch_size=_int("batch_size", 32),
        max_candidates=_int("max_candidates"),
        fallback_priority=getattr(model, "fallback_priority", 0),
    )


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
