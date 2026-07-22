import json
import math
import re
import time
from typing import Generator, Iterable

from django.conf import settings
from django.core.cache import cache
import requests

from .model_usage import estimate_tokens, record_model_usage, usage_from_response
from .model_types import canonical_model_type, frontend_model_group, model_type_aliases
from .models import ModelConfig, Tenant


# ── Provider 工厂 ────────────────────────────────────────────────────
from .llm_providers import factory as _provider_factory
from .llm_providers import provider_display_list as _provider_display_list


# ── 连接池：复用 TCP 连接，避免每次请求都建立新连接 ──────────────────
_http_session = requests.Session()
_http_session.headers.update({"Content-Type": "application/json"})


class ModelConfigurationError(RuntimeError):
    pass


_CREDENTIAL_LIKE_RE = re.compile(
    r"\b(?:api[_ -]?key|access[_ -]?token|authorization|bearer)\b|\bsk-[A-Za-z0-9_-]{6,}\b",
    re.IGNORECASE,
)


def _safe_model_error_text(value, fallback: str, max_length: int) -> str:
    text = " ".join(str(value or fallback).split())
    if _CREDENTIAL_LIKE_RE.search(text):
        return fallback
    return text[:max_length] or fallback


class ModelAccessDeniedError(ModelConfigurationError):
    def __init__(self, status_code: int, upstream_code: str, message: str):
        self.status_code = status_code
        self.upstream_code = _safe_model_error_text(upstream_code, "model_access_denied", 200)
        self.safe_message = _safe_model_error_text(message, "Model access was denied", 500)
        super().__init__(f"{self.upstream_code}: {self.safe_message}")


def _vlm_access_key(tenant: Tenant) -> str:
    return f"vlm:access-denied:{tenant.id}"


def vlm_access_state(tenant: Tenant) -> dict | None:
    return cache.get(_vlm_access_key(tenant))


def mark_vlm_access_denied(tenant: Tenant, exc: ModelAccessDeniedError) -> None:
    cache.set(
        _vlm_access_key(tenant),
        {"status_code": exc.status_code, "code": exc.upstream_code, "message": exc.safe_message},
        timeout=300,
    )


def clear_vlm_access_denied(tenant: Tenant) -> None:
    cache.delete(_vlm_access_key(tenant))


def _raise_for_model_status(response) -> None:
    if response.status_code not in {401, 403}:
        response.raise_for_status()
        return
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    error = payload.get("error") if "error" in payload else payload
    if not isinstance(error, dict):
        error = {"message": str(error)}
    raise ModelAccessDeniedError(
        response.status_code,
        str(error.get("code") or "model_access_denied"),
        str(error.get("message") or "Model access was denied"),
    )


TEXT_ROLE_TYPES = {
    "chat": "chat",
    "summary": "chat",
    "title": "chat",
    "question": "chat",
    "extract": "chat",
}

def _get_model_config(model_type: str) -> tuple[str, str, str]:
    """获取指定模型类型的 (base_url, api_key, model_name)。"""
    model_type = model_type.upper()
    base_url = getattr(settings, f"LLM_{model_type}_BASE_URL", None) or settings.LLM_CHAT_BASE_URL
    api_key = getattr(settings, f"LLM_{model_type}_API_KEY", None) or settings.LLM_CHAT_API_KEY
    model_name = getattr(settings, f"LLM_{model_type}_MODEL", None) or settings.LLM_CHAT_MODEL
    return base_url, api_key, model_name


def _role_config(role: str) -> dict:
    role = role.lower()

    # 获取该角色对应的模型配置
    role_to_type = {
        "chat": "CHAT",
        "summary": "CHAT",
        "title": "CHAT",
        "question": "CHAT",
        "extract": "CHAT",
        "embedding": "EMBEDDING",
        "rerank": "RERANK",
        "vlm": "VLM",
    }
    model_type = role_to_type.get(role, "CHAT")
    base, api_key, model_name = _get_model_config(model_type)
    configured = bool(api_key)

    configs = {
        "chat": {
            "type": "KnowledgeQA",
            "model": settings.LLM_CHAT_MODEL,
            "enabled": settings.LLM_USE_ENV_CHAT,
            "description": "知识库问答与 Agent 对话",
        },
        "summary": {
            "type": "KnowledgeQA",
            "model": settings.LLM_SUMMARY_MODEL,
            "enabled": settings.LLM_USE_ENV_SUMMARY,
            "description": "知识条目摘要生成",
        },
        "title": {
            "type": "KnowledgeQA",
            "model": settings.LLM_TITLE_MODEL,
            "enabled": settings.LLM_USE_ENV_TITLE,
            "description": "会话标题生成",
        },
        "question": {
            "type": "KnowledgeQA",
            "model": settings.LLM_QUESTION_MODEL,
            "enabled": settings.LLM_USE_ENV_QUESTION,
            "description": "推荐问题生成",
        },
        "extract": {
            "type": "KnowledgeQA",
            "model": settings.LLM_EXTRACT_MODEL,
            "enabled": settings.LLM_USE_ENV_EXTRACT,
            "description": "Wiki 与结构化信息抽取",
        },
        "embedding": {
            "type": "Embedding",
            "model": settings.LLM_EMBEDDING_MODEL,
            "enabled": settings.LLM_USE_ENV_EMBEDDING,
            "dimension": settings.LLM_EMBEDDING_DIM,
            "description": "知识切片向量化",
        },
        "rerank": {
            "type": "Rerank",
            "model": settings.LLM_RERANK_MODEL,
            "enabled": settings.LLM_USE_ENV_RERANK,
            "description": "混合检索候选重排序",
        },
        "vlm": {
            "type": "VLLM",
            "model": settings.LLM_VLM_MODEL,
            "enabled": settings.LLM_USE_ENV_VLM,
            "description": "图片内容识别与描述",
        },
    }
    cfg = configs[role]
    cfg.update({"role": role, "base_url": base, "configured": configured, "api_key": api_key, "api_key_configured": configured})
    return cfg


def bailian_status():
    roles = {role: _role_config(role) for role in ["chat", "summary", "title", "question", "extract", "embedding", "rerank", "vlm"]}
    return {
        "enabled": roles["chat"]["enabled"],
        "configured": bool(settings.LLM_CHAT_API_KEY),
        "base_url": settings.LLM_CHAT_BASE_URL,
        "chat_model": settings.LLM_CHAT_MODEL,
        "api_key_configured": bool(settings.LLM_CHAT_API_KEY),
        "embedding_dimension": settings.LLM_EMBEDDING_DIM,
        "local_embedding_dimension": settings.APP_EMBEDDING_DIM,
        "roles": roles,
    }


def env_models(tenant: Tenant, model_type: str = "") -> list[dict]:
    aliases = model_type_aliases(model_type) if model_type else set()
    grouped: dict[tuple[str, str], dict] = {}
    type_order = {"KnowledgeQA": 0, "Embedding": 1, "Rerank": 2, "VLLM": 3}

    for role, cfg in bailian_status()["roles"].items():
        canonical_type = canonical_model_type(cfg["type"])
        if aliases and canonical_type not in aliases and role not in aliases:
            continue

        key = (canonical_type, cfg["model"])
        item = grouped.setdefault(
            key,
            {
                "id": f"env-aliyun-bailian-{canonical_type.lower()}-{cfg['model']}",
                "tenant_id": tenant.id,
                "name": cfg["model"],
                "display_name": cfg["model"],
                "type": canonical_type,
                "raw_type": canonical_type,
                "source": "aliyun-bailian",
                "description": cfg["description"],
                "parameters": {
                    "base_url": cfg["base_url"],
                    "model": cfg["model"],
                    "api_key_configured": cfg["api_key_configured"],
                },
                "roles": [],
                "role": "",
                "is_default": False,
                "is_builtin": True,
                "managed_by": "env",
                "status": "active" if cfg["configured"] else "missing_api_key",
            },
        )
        item["roles"].append(
            {
                "key": role,
                "description": cfg["description"],
                "enabled": bool(cfg["enabled"]),
                "configured": bool(cfg["configured"]),
            }
        )
        item["is_default"] = bool(item["is_default"] or cfg["enabled"])
        if "dimension" in cfg:
            item["parameters"]["dimension"] = cfg["dimension"]

    return sorted(grouped.values(), key=lambda item: (type_order.get(item["type"], 99), item["name"]))


def default_model(tenant: Tenant, model_type: str) -> ModelConfig | None:
    return (
        ModelConfig.objects.filter(tenant=tenant, type__in=model_type_aliases(model_type), status="active", deleted_at__isnull=True)
        .order_by("-is_default", "created_at")
        .first()
    )


def is_env_chat_model_id(model_id: str = "") -> bool:
    return str(model_id or "").startswith("env-aliyun-bailian-knowledgeqa-") or str(model_id or "").startswith("env-aliyun-bailian-chat")


def _env_text_completion(role: str, messages: list[dict], tenant: Tenant | None = None, scenario: str = "", **request_options) -> str:
    cfg = _role_config(role)
    if not cfg["enabled"] or not cfg["configured"]:
        raise ModelConfigurationError(f"Bailian {role} model is not configured")
    started = time.monotonic()
    try:
        data = openai_compatible_chat_raw(cfg["base_url"], cfg["api_key"], cfg["model"], messages, **request_options)
        usage = usage_from_response(data)
        if not usage["total_tokens"]:
            usage["prompt_tokens"] = estimate_tokens(messages)
            usage["completion_tokens"] = estimate_tokens(data.get("choices", [{}])[0].get("message", {}).get("content", ""))
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        record_model_usage(
            tenant,
            model_id=f"env-aliyun-bailian-{role}",
            model_name=cfg["model"],
            model_type=role,
            provider="aliyun-bailian",
            scenario=scenario or role,
            duration_ms=int((time.monotonic() - started) * 1000),
            **usage,
        )
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as exc:
        record_model_usage(
            tenant,
            model_id=f"env-aliyun-bailian-{role}",
            model_name=cfg["model"],
            model_type=role,
            provider="aliyun-bailian",
            scenario=scenario or role,
            success=False,
            prompt_tokens=estimate_tokens(messages),
            duration_ms=int((time.monotonic() - started) * 1000),
            error_message=str(exc),
        )
        raise


def chat_completion(tenant: Tenant, messages: list[dict], model_id: str = "", stream: bool = False) -> str:
    if (not model_id or is_env_chat_model_id(model_id)) and settings.LLM_USE_ENV_CHAT and settings.LLM_CHAT_API_KEY:
        return _env_text_completion("chat", messages, tenant, "chat")
    if is_env_chat_model_id(model_id):
        raise ModelConfigurationError("Bailian chat model is not configured")
    model = ModelConfig.objects.filter(id=model_id, tenant=tenant).first() if model_id else default_model(tenant, "chat")
    if not model:
        raise ModelConfigurationError("No chat model configured")
    params = model.parameters or {}
    base_url = (params.get("base_url") or params.get("baseURL") or "").rstrip("/")
    api_key = params.get("api_key") or params.get("apiKey") or params.get("token")
    model_name = params.get("model") or model.name
    if not base_url:
        raise ModelConfigurationError("Model base_url is required")
    started = time.monotonic()
    try:
        data = openai_compatible_chat_raw(base_url, api_key, model_name, messages)
        usage = usage_from_response(data)
        if not usage["total_tokens"]:
            usage["prompt_tokens"] = estimate_tokens(messages)
            usage["completion_tokens"] = estimate_tokens(data.get("choices", [{}])[0].get("message", {}).get("content", ""))
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        record_model_usage(
            tenant,
            model_id=model.id,
            model_name=model_name,
            model_type=model.type,
            provider=model.source,
            scenario="chat",
            duration_ms=int((time.monotonic() - started) * 1000),
            **usage,
        )
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as exc:
        record_model_usage(
            tenant,
            model_id=model.id,
            model_name=model_name,
            model_type=model.type,
            provider=model.source,
            scenario="chat",
            success=False,
            prompt_tokens=estimate_tokens(messages),
            duration_ms=int((time.monotonic() - started) * 1000),
            error_message=str(exc),
        )
        raise


def chat_completion_stream(
    tenant: Tenant, messages: list[dict], model_id: str = "",
) -> Generator[str, None, None]:
    """
    真正的逐 token 流式输出。
    参考同类知识库系统的 streamLLMToEventBus 实现。

    Yields:
        每个 token 或小片段的文本内容

    使用方式:
        for token in chat_completion_stream(tenant, messages):
            yield token
    """
    if (not model_id or is_env_chat_model_id(model_id)) and settings.LLM_USE_ENV_CHAT and settings.LLM_CHAT_API_KEY:
        base_url = settings.LLM_CHAT_BASE_URL
        api_key = settings.LLM_CHAT_API_KEY
        model_name = settings.LLM_CHAT_MODEL
    elif is_env_chat_model_id(model_id):
        raise ModelConfigurationError("Bailian chat model is not configured")
    else:
        model = ModelConfig.objects.filter(id=model_id, tenant=tenant).first() if model_id else default_model(tenant, "chat")
        if not model:
            raise ModelConfigurationError("No chat model configured")
        params = model.parameters or {}
        base_url = (params.get("base_url") or params.get("baseURL") or "").rstrip("/")
        api_key = params.get("api_key") or params.get("apiKey") or params.get("token")
        model_name = params.get("model") or model.name
        if not base_url:
            raise ModelConfigurationError("Model base_url is required")

    started = time.monotonic()
    total_content = ""
    try:
        for chunk in openai_compatible_chat_stream(base_url, api_key, model_name, messages):
            choices = chunk.get("choices", [])
            if not choices:
                continue
            delta = choices[0].get("delta", {})
            content = delta.get("content", "")
            if content:
                total_content += content
                yield content
    except Exception as exc:
        # 记录失败的使用情况
        record_model_usage(
            tenant,
            model_id=f"env-aliyun-bailian-chat" if is_env_chat_model_id(model_id) else (model_id or ""),
            model_name=model_name,
            model_type="chat",
            provider="aliyun-bailian" if is_env_chat_model_id(model_id) else "custom",
            scenario="chat",
            success=False,
            prompt_tokens=estimate_tokens(messages),
            duration_ms=int((time.monotonic() - started) * 1000),
            error_message=str(exc),
        )
        raise
    else:
        # 记录成功的使用情况
        duration_ms = int((time.monotonic() - started) * 1000)
        usage = {
            "prompt_tokens": estimate_tokens(messages),
            "completion_tokens": estimate_tokens(total_content),
        }
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        record_model_usage(
            tenant,
            model_id=f"env-aliyun-bailian-chat" if is_env_chat_model_id(model_id) else (model_id or ""),
            model_name=model_name,
            model_type="chat",
            provider="aliyun-bailian" if is_env_chat_model_id(model_id) else "custom",
            scenario="chat",
            duration_ms=duration_ms,
            **usage,
        )


def chat_completion_raw(
    tenant: Tenant, messages: list[dict], model_id: str = "",
    tools: list[dict] | None = None, temperature: float | None = None,
) -> dict:
    """
    支持 function calling 的 LLM 调用。
    返回 {"content": str, "tool_calls": list | None}
    """
    model = None
    provider = "aliyun-bailian"
    recorded_model_id = "env-aliyun-bailian-chat"
    if (not model_id or is_env_chat_model_id(model_id)) and settings.LLM_USE_ENV_CHAT and settings.LLM_CHAT_API_KEY:
        base_url = settings.LLM_CHAT_BASE_URL
        api_key = settings.LLM_CHAT_API_KEY
        model_name = settings.LLM_CHAT_MODEL
    elif is_env_chat_model_id(model_id):
        raise ModelConfigurationError("Bailian chat model is not configured")
    else:
        model = ModelConfig.objects.filter(id=model_id, tenant=tenant).first() if model_id else default_model(tenant, "chat")
        if not model:
            raise ModelConfigurationError("No chat model configured")
        params = model.parameters or {}
        base_url = (params.get("base_url") or params.get("baseURL") or "").rstrip("/")
        api_key = params.get("api_key") or params.get("apiKey") or params.get("token")
        model_name = params.get("model") or model.name
        provider = model.source
        recorded_model_id = model.id
        if not base_url:
            raise ModelConfigurationError("Model base_url is required")

    started = time.monotonic()
    data = openai_compatible_chat_raw(base_url, api_key, model_name, messages, tools=tools, temperature=temperature)
    usage = usage_from_response(data)
    if not usage["total_tokens"]:
        usage["prompt_tokens"] = estimate_tokens(messages)
        usage["completion_tokens"] = estimate_tokens(data.get("choices", [{}])[0].get("message", {}).get("content", ""))
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
    record_model_usage(
        tenant,
        model_id=recorded_model_id,
        model_name=model_name,
        model_type=(model.type if model else "KnowledgeQA"),
        provider=provider,
        scenario="agent_reasoning",
        duration_ms=int((time.monotonic() - started) * 1000),
        **usage,
    )
    choice = data.get("choices", [{}])[0]
    message = choice.get("message", {})
    return {
        "content": message.get("content", ""),
        "tool_calls": message.get("tool_calls"),
        "finish_reason": choice.get("finish_reason"),
    }


def role_completion(role: str, prompt: str, fallback: str = "", max_chars: int | None = None, tenant: Tenant | None = None, scenario: str = "", *, max_tokens: int | None = None, enable_thinking: bool | None = None, total_timeout: int | None = None) -> str:
    try:
        content = _env_text_completion(
            role,
            [
                {"role": "system", "content": "你是个人轻量知识库的内置助手，请只输出用户要求的结果。"},
                {"role": "user", "content": prompt},
            ],
            tenant,
            scenario or role,
            max_tokens=max_tokens,
            enable_thinking=enable_thinking,
            total_timeout=total_timeout,
        ).strip()
        if max_chars:
            content = content[:max_chars].strip()
        return content or fallback
    except Exception:
        return fallback


def openai_compatible_chat(base_url: str, api_key: str, model_name: str, messages: list[dict]) -> str:
    data = openai_compatible_chat_raw(base_url, api_key, model_name, messages)
    return data.get("choices", [{}])[0].get("message", {}).get("content", "")


def openai_compatible_chat_raw(
    base_url: str, api_key: str, model_name: str, messages: list[dict],
    tools: list[dict] | None = None, temperature: float | None = None,
    max_tokens: int | None = None, enable_thinking: bool | None = None,
    total_timeout: int | None = None,
) -> dict:
    url = f"{base_url.rstrip('/')}/chat/completions" if not base_url.endswith("/chat/completions") else base_url
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {"model": model_name, "messages": messages, "stream": False}
    if tools:
        body["tools"] = tools
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens is not None:
        body["max_tokens"] = int(max_tokens)
    if enable_thinking is not None:
        body["enable_thinking"] = bool(enable_thinking)
    # 使用连接池复用 TCP 连接
    request_started = time.monotonic()
    timeout = min(settings.LLM_CHAT_MODEL_TIMEOUT, int(total_timeout)) if total_timeout else settings.LLM_CHAT_MODEL_TIMEOUT
    resp = _http_session.post(url, headers=headers, json=body, timeout=timeout, stream=bool(total_timeout))
    _raise_for_model_status(resp)
    if not total_timeout:
        return resp.json()
    deadline = request_started + int(total_timeout)
    payload = bytearray()
    for block in resp.iter_content(chunk_size=8192):
        if time.monotonic() > deadline:
            resp.close()
            raise requests.Timeout(f"LLM request exceeded total timeout of {total_timeout}s")
        if block:
            payload.extend(block)
        if len(payload) > 8 * 1024 * 1024:
            resp.close()
            raise ValueError("LLM response exceeded 8 MiB")
    return json.loads(payload.decode("utf-8"))


def openai_compatible_chat_stream(
    base_url: str, api_key: str, model_name: str, messages: list[dict],
    tools: list[dict] | None = None, temperature: float | None = None,
) -> Generator[dict, None, None]:
    """
    流式调用 OpenAI 兼容 API，逐 chunk 返回。
    参考同类知识库系统的 streamLLMToEventBus 实现。

    Yields:
        每个 SSE chunk 的 parsed JSON（包含 delta.content）
    """
    url = f"{base_url.rstrip('/')}/chat/completions" if not base_url.endswith("/chat/completions") else base_url
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {"model": model_name, "messages": messages, "stream": True}
    if tools:
        body["tools"] = tools
    if temperature is not None:
        body["temperature"] = temperature

    resp = _http_session.post(url, headers=headers, json=body, timeout=settings.LLM_CHAT_MODEL_TIMEOUT, stream=True)
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


# ── 检索模型配置解析（严格模式：环境变量优先，数据库默认模型兜底）────────
# 约定：embedding/rerank 未配置或调用失败必须抛出 ModelConfigurationError，
# 由检索层显式降级；禁止用本地哈希向量静默伪装远程模型结果。


class EmbeddingDimensionMismatchError(ModelConfigurationError):
    """Embedding 返回维度与配置维度不一致。"""

    code = "embedding_dimension_mismatch"


class RerankResultIncompleteError(ModelConfigurationError):
    """Rerank 返回结果不完整（缺少索引或分数）。"""

    code = "rerank_result_incomplete"


def _env_embedding_config(require_enabled: bool = True) -> dict | None:
    if require_enabled and not settings.LLM_USE_ENV_EMBEDDING:
        return None
    if not settings.LLM_EMBEDDING_API_KEY:
        return None
    return {
        "source": "env",
        "model_id": "env-aliyun-bailian-embedding",
        "provider": "aliyun-bailian",
        "base_url": settings.LLM_EMBEDDING_BASE_URL.rstrip("/"),
        "api_key": settings.LLM_EMBEDDING_API_KEY,
        "model": settings.LLM_EMBEDDING_MODEL,
        "dimension": settings.LLM_EMBEDDING_DIM,
        "timeout": settings.LLM_CHAT_MODEL_TIMEOUT,
        "batch_size": 32,
        "max_candidates": None,
    }


def _env_rerank_config(require_enabled: bool = True) -> dict | None:
    if require_enabled and not settings.LLM_USE_ENV_RERANK:
        return None
    if not settings.LLM_RERANK_API_KEY:
        return None
    return {
        "source": "env",
        "model_id": "env-aliyun-bailian-rerank",
        "provider": "aliyun-bailian",
        "base_url": settings.LLM_RERANK_BASE_URL.rstrip("/"),
        "api_key": settings.LLM_RERANK_API_KEY,
        "model": settings.LLM_RERANK_MODEL,
        "dimension": None,
        "timeout": settings.LLM_CHAT_MODEL_TIMEOUT,
        "batch_size": 32,
        "max_candidates": None,
    }


def _db_model_config(tenant: Tenant | None, model_id: str, model_type: str) -> dict | None:
    if model_id:
        model = ModelConfig.objects.filter(id=model_id, tenant=tenant, deleted_at__isnull=True).first()
    elif tenant is not None:
        model = default_model(tenant, model_type)
    else:
        model = None
    if not model or model.source == "local":
        return None
    params = model.parameters or {}
    base_url = (params.get("base_url") or params.get("baseURL") or "").rstrip("/")
    if not base_url:
        return None

    def _int_param(key, default=None):
        try:
            return int(params.get(key)) if params.get(key) not in (None, "") else default
        except (TypeError, ValueError):
            return default

    return {
        "source": "db",
        "model_id": model.id,
        "provider": model.source,
        "base_url": base_url,
        "api_key": params.get("api_key") or params.get("apiKey") or params.get("token") or "",
        "model": params.get("model") or model.name,
        "dimension": _int_param("dimension", settings.LLM_EMBEDDING_DIM),
        "timeout": _int_param("timeout", settings.LLM_CHAT_MODEL_TIMEOUT),
        "batch_size": _int_param("batch_size", 32),
        "max_candidates": _int_param("max_candidates"),
    }


def active_embedding_config(tenant: Tenant | None = None, model_id: str = "") -> dict | None:
    """当前生效的 Embedding 配置；未配置返回 None。"""
    if not model_id:
        env = _env_embedding_config()
        if env:
            return env
    return _db_model_config(tenant, model_id, "embedding")


def active_rerank_config(tenant: Tenant | None = None, model_id: str = "") -> dict | None:
    """当前生效的 Rerank 配置；未配置返回 None。"""
    if not model_id:
        env = _env_rerank_config()
        if env:
            return env
    return _db_model_config(tenant, model_id, "rerank")


def embedding_signature(tenant: Tenant | None = None, model_id: str = "") -> str:
    """向量索引签名（模型名:维度），用于识别模型变更并触发索引重建。"""
    cfg = active_embedding_config(tenant, model_id)
    if not cfg:
        return ""
    return f"{cfg['model']}:{cfg.get('dimension') or settings.LLM_EMBEDDING_DIM}"


def _validate_embedding_vectors(vectors: list[list[float]], expected_count: int, expected_dim: int, model_name: str = "") -> None:
    if len(vectors) != expected_count:
        raise ModelConfigurationError(
            f"embedding result count mismatch for {model_name}: expected {expected_count}, got {len(vectors)}"
        )
    for vec in vectors:
        if len(vec) != expected_dim:
            raise EmbeddingDimensionMismatchError(
                f"embedding dimension mismatch for {model_name}: expected {expected_dim}, got {len(vec)}"
            )
        if not all(math.isfinite(float(v)) for v in vec):
            raise ModelConfigurationError(f"embedding vector for {model_name} contains non-finite values")


def embedding(tenant: Tenant, texts: Iterable[str], model_id: str = "") -> list[list[float]]:
    """严格模式 Embedding：未配置或维度不符直接抛错，绝不回退本地哈希向量。"""
    values = list(texts)
    if not values:
        return []
    cfg = active_embedding_config(tenant, model_id)
    if not cfg:
        raise ModelConfigurationError("No embedding model configured")
    started = time.monotonic()
    try:
        vectors = openai_compatible_embedding(
            cfg["base_url"], cfg["api_key"], cfg["model"], values, timeout=cfg.get("timeout") or 60
        )
        _validate_embedding_vectors(
            vectors, len(values), int(cfg.get("dimension") or settings.LLM_EMBEDDING_DIM), cfg["model"]
        )
    except Exception as exc:
        record_model_usage(
            tenant,
            model_id=cfg["model_id"],
            model_name=cfg["model"],
            model_type="embedding",
            provider=cfg["provider"],
            scenario="embedding",
            success=False,
            prompt_tokens=estimate_tokens(values),
            duration_ms=int((time.monotonic() - started) * 1000),
            error_message=str(exc),
        )
        raise
    record_model_usage(
        tenant,
        model_id=cfg["model_id"],
        model_name=cfg["model"],
        model_type="embedding",
        provider=cfg["provider"],
        scenario="embedding",
        prompt_tokens=estimate_tokens(values),
        total_tokens=estimate_tokens(values),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return vectors


def openai_compatible_embedding(base_url: str, api_key: str, model_name: str, texts: list[str], timeout: int = 60) -> list[list[float]]:
    url = f"{base_url.rstrip('/')}/embeddings" if not base_url.endswith("/embeddings") else base_url
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    resp = requests.post(url, headers=headers, json={"model": model_name, "input": texts}, timeout=timeout)
    _raise_for_model_status(resp)
    data = resp.json()
    return [item["embedding"] for item in data.get("data", [])]


def rerank(query: str, results: list[dict], top_k: int | None = None, tenant: Tenant | None = None, model_id: str = "") -> list[dict]:
    """严格模式 Rerank：未配置或调用失败抛错；成功时按重排分数排序并写入 rerank_score。"""
    if not results:
        return results[:top_k] if top_k else results
    cfg = active_rerank_config(tenant, model_id)
    if not cfg:
        raise ModelConfigurationError("No rerank model configured")
    max_candidates = cfg.get("max_candidates")
    candidates = results[:max_candidates] if max_candidates else list(results)
    remainder = results[len(candidates):]
    url = f"{cfg['base_url'].rstrip('/')}/rerank"
    payload = {"model": cfg["model"], "query": query, "documents": [r["content"] for r in candidates]}
    started = time.monotonic()
    try:
        resp = requests.post(url, headers=_json_headers(cfg.get("api_key")), json=payload, timeout=cfg.get("timeout") or 60)
        _raise_for_model_status(resp)
        data = resp.json()
    except Exception as exc:
        record_model_usage(
            tenant,
            model_id=cfg["model_id"],
            model_name=cfg["model"],
            model_type="rerank",
            provider=cfg["provider"],
            scenario="rerank",
            success=False,
            prompt_tokens=estimate_tokens(payload["query"]) + estimate_tokens(payload["documents"]),
            duration_ms=int((time.monotonic() - started) * 1000),
            error_message=str(exc),
        )
        raise
    usage = usage_from_response(data)
    if not usage["total_tokens"]:
        usage["prompt_tokens"] = estimate_tokens(payload["query"]) + estimate_tokens(payload["documents"])
        usage["total_tokens"] = usage["prompt_tokens"]
    record_model_usage(
        tenant,
        model_id=cfg["model_id"],
        model_name=cfg["model"],
        model_type="rerank",
        provider=cfg["provider"],
        scenario="rerank",
        duration_ms=int((time.monotonic() - started) * 1000),
        **usage,
    )
    raw_items = data.get("results") or data.get("output", {}).get("results") or []
    scored: list[dict] = []
    seen: set[int] = set()
    for item in raw_items:
        idx = item.get("index")
        if idx is None:
            idx = item.get("document_index")
        if idx is None or int(idx) >= len(candidates) or int(idx) in seen:
            continue
        seen.add(int(idx))
        result = {**candidates[int(idx)]}
        score = item.get("relevance_score", item.get("score", 0))
        result["rerank_score"] = float(score)
        result["score"] = float(score)
        result.setdefault("metadata", {})["rerank_model"] = cfg["model"]
        scored.append(result)
    if not scored:
        raise RerankResultIncompleteError(f"rerank returned no usable results for {cfg['model']}")
    scored.sort(key=lambda row: row["rerank_score"], reverse=True)
    # 未被重排返回的候选保持原顺序附加在尾部，避免结果丢失
    ordered = scored + [candidates[i] for i in range(len(candidates)) if i not in seen] + remainder
    return ordered[:top_k] if top_k else ordered


def testable_model_config(tenant: Tenant, model_id: str) -> tuple[str, dict | None] | None:
    """解析模型测试目标，返回 (canonical_type, cfg)；模型不存在返回 None。"""
    if model_id.startswith("env-aliyun-bailian-embedding"):
        return ("Embedding", _env_embedding_config(require_enabled=False))
    if model_id.startswith("env-aliyun-bailian-rerank"):
        return ("Rerank", _env_rerank_config(require_enabled=False))
    model = ModelConfig.objects.filter(id=model_id, tenant=tenant, deleted_at__isnull=True).first()
    if not model:
        return None
    canonical = canonical_model_type(model.type)
    if canonical not in {"Embedding", "Rerank"}:
        return (canonical, None)
    return (canonical, _db_model_config(tenant, model_id, canonical))


def test_embedding_config(cfg: dict) -> dict:
    """真实执行一次 Embedding 请求，校验返回数量、有限数值与配置维度。"""
    started = time.monotonic()
    vectors = openai_compatible_embedding(
        cfg["base_url"],
        cfg.get("api_key") or "",
        cfg["model"],
        ["BGE-M3 向量维度校验", "embedding dimension check"],
        timeout=cfg.get("timeout") or 60,
    )
    expected_dim = int(cfg.get("dimension") or settings.LLM_EMBEDDING_DIM)
    _validate_embedding_vectors(vectors, 2, expected_dim, cfg["model"])
    return {
        "ok": True,
        "model": cfg["model"],
        "dimension": len(vectors[0]),
        "latency_ms": int((time.monotonic() - started) * 1000),
    }


def test_rerank_config(cfg: dict) -> dict:
    """真实执行一次 Rerank 请求，校验索引、分数与排序完整性（至少两篇文档）。"""
    documents = [
        "BGE-Reranker 用于对检索候选文档进行相关性排序",
        "今天天气怎么样，适合出门吗",
        "检索增强生成结合了外部知识检索与语言模型生成",
    ]
    started = time.monotonic()
    resp = requests.post(
        f"{cfg['base_url'].rstrip('/')}/rerank",
        headers=_json_headers(cfg.get("api_key")),
        json={"model": cfg["model"], "query": "什么是重排序模型", "documents": documents},
        timeout=cfg.get("timeout") or 60,
    )
    _raise_for_model_status(resp)
    data = resp.json()
    raw_items = data.get("results") or data.get("output", {}).get("results") or []
    indices: list[int] = []
    for item in raw_items:
        idx = item.get("index", item.get("document_index"))
        score = item.get("relevance_score", item.get("score"))
        if idx is None or score is None or not math.isfinite(float(score)):
            raise RerankResultIncompleteError(
                f"rerank result incomplete for {cfg['model']}: missing index or non-finite score"
            )
        indices.append(int(idx))
    if sorted(indices) != list(range(len(documents))):
        raise RerankResultIncompleteError(
            f"rerank result incomplete for {cfg['model']}: expected indices 0..{len(documents) - 1}, got {sorted(indices)}"
        )
    return {
        "ok": True,
        "model": cfg["model"],
        "documents": len(documents),
        "latency_ms": int((time.monotonic() - started) * 1000),
    }


def describe_image(image_url: str, title: str = "", tenant: Tenant | None = None) -> str:
    cfg = _role_config("vlm")
    if not image_url or not cfg["enabled"] or not cfg["configured"]:
        return ""
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"请简洁描述这张图片中可用于知识库检索的信息。文件名：{title}"},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }
    ]
    try:
        return _env_text_completion("vlm", messages, tenant, "vlm").strip()
    except Exception:
        return ""


def vision_completion(tenant: Tenant, image_data_url: str, prompt: str, scenario: str, model_id: str = "") -> str:
    messages = [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": image_data_url}}]}]
    env_config = _role_config("vlm")
    if model_id.startswith("env-") or (not model_id and env_config["enabled"] and env_config["configured"]):
        try:
            content = _env_text_completion("vlm", messages, tenant, scenario).strip()
        except ModelAccessDeniedError as exc:
            mark_vlm_access_denied(tenant, exc)
            raise
        clear_vlm_access_denied(tenant)
        return content
    model = ModelConfig.objects.filter(id=model_id, tenant=tenant, deleted_at__isnull=True, status="active").first() if model_id else None
    if not model:
        model = default_model(tenant, "vlm")
    if not model:
        raise ModelConfigurationError("No VLM model configured")
    params = model.parameters or {}
    base_url = (params.get("base_url") or params.get("baseURL") or "").rstrip("/")
    api_key = params.get("api_key") or params.get("apiKey") or params.get("token") or ""
    model_name = params.get("model") or model.name
    if not base_url:
        raise ModelConfigurationError("VLM base_url is required")
    started = time.monotonic()
    try:
        data = openai_compatible_chat_raw(base_url, api_key, model_name, messages)
        usage = usage_from_response(data)
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not usage["total_tokens"]:
            usage["prompt_tokens"] = estimate_tokens(prompt)
            usage["completion_tokens"] = estimate_tokens(content)
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        record_model_usage(tenant, model_id=model.id, model_name=model_name, model_type="vlm", provider=model.source, scenario=scenario, duration_ms=int((time.monotonic() - started) * 1000), **usage)
        clear_vlm_access_denied(tenant)
        return content
    except Exception as exc:
        record_model_usage(tenant, model_id=model.id, model_name=model_name, model_type="vlm", provider=model.source, scenario=scenario, success=False, prompt_tokens=estimate_tokens(prompt), duration_ms=int((time.monotonic() - started) * 1000), error_message=str(exc))
        if isinstance(exc, ModelAccessDeniedError):
            mark_vlm_access_denied(tenant, exc)
        raise


def generate_questions(text: str, limit: int = 5, tenant: Tenant | None = None) -> list[str]:
    fallback = []
    prompt = f"基于以下知识内容生成 {limit} 个用户可能会问的问题。每行一个问题，不要编号。\n\n{text[:6000]}"
    content = role_completion("question", prompt, "", tenant=tenant, scenario="question")
    for line in content.splitlines():
        item = line.strip().lstrip("-0123456789.、) ")
        if item:
            fallback.append(item)
        if len(fallback) >= limit:
            break
    return fallback


def extract_metadata(text: str, tenant: Tenant | None = None) -> dict:
    prompt = f"从以下知识内容中提取核心主题、实体和关键词，输出 JSON，字段为 topics、entities、keywords。\n\n{text[:6000]}"
    content = role_completion("extract", prompt, "", tenant=tenant, scenario="extract_metadata")
    try:
        value = json.loads(content)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _json_headers(api_key: str | None = None):
    headers = {"Content-Type": "application/json"}
    key = api_key if api_key is not None else settings.LLM_CHAT_API_KEY
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def provider_types():
    return _provider_display_list()


def safe_json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {}
    return value or {}
