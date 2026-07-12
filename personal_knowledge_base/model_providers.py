import json
import time
from typing import Generator, Iterable

from django.conf import settings
from django.core.cache import cache
import requests

from .model_usage import estimate_tokens, record_model_usage, usage_from_response
from .model_types import canonical_model_type, frontend_model_group, model_type_aliases
from .models import ModelConfig, Tenant


# ── 连接池：复用 TCP 连接，避免每次请求都建立新连接 ──────────────────
_http_session = requests.Session()
_http_session.headers.update({"Content-Type": "application/json"})


class ModelConfigurationError(RuntimeError):
    pass


class ModelAccessDeniedError(ModelConfigurationError):
    def __init__(self, status_code: int, upstream_code: str, message: str):
        self.status_code = status_code
        self.upstream_code = upstream_code
        self.safe_message = message
        super().__init__(f"{upstream_code or 'model_access_denied'}: {message}")


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
    error = payload.get("error") or {}
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


def _env_text_completion(role: str, messages: list[dict], tenant: Tenant | None = None, scenario: str = "") -> str:
    cfg = _role_config(role)
    if not cfg["enabled"] or not cfg["configured"]:
        raise ModelConfigurationError(f"Bailian {role} model is not configured")
    started = time.monotonic()
    try:
        data = openai_compatible_chat_raw(cfg["base_url"], cfg["api_key"], cfg["model"], messages)
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


def role_completion(role: str, prompt: str, fallback: str = "", max_chars: int | None = None, tenant: Tenant | None = None, scenario: str = "") -> str:
    try:
        content = _env_text_completion(
            role,
            [
                {"role": "system", "content": "你是个人轻量知识库的内置助手，请只输出用户要求的结果。"},
                {"role": "user", "content": prompt},
            ],
            tenant,
            scenario or role,
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
    # 使用连接池复用 TCP 连接
    resp = _http_session.post(url, headers=headers, json=body, timeout=settings.LLM_CHAT_MODEL_TIMEOUT)
    _raise_for_model_status(resp)
    return resp.json()


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


def embedding(tenant: Tenant, texts: Iterable[str], model_id: str = "") -> list[list[float]]:
    from .search import stable_embedding

    values = list(texts)
    if not values:
        return []
    if not model_id and settings.LLM_USE_ENV_EMBEDDING and settings.LLM_CHAT_API_KEY:
        started = time.monotonic()
        try:
            vectors = openai_compatible_embedding(
                settings.LLM_CHAT_BASE_URL,
                settings.LLM_CHAT_API_KEY,
                settings.LLM_EMBEDDING_MODEL,
                values,
            )
            if len(vectors) == len(values):
                record_model_usage(
                    tenant,
                    model_id="env-aliyun-bailian-embedding",
                    model_name=settings.LLM_EMBEDDING_MODEL,
                    model_type="embedding",
                    provider="aliyun-bailian",
                    scenario="embedding",
                    prompt_tokens=estimate_tokens(values),
                    total_tokens=estimate_tokens(values),
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
                return _fit_vectors(vectors, settings.APP_EMBEDDING_DIM)
        except Exception as exc:
            record_model_usage(
                tenant,
                model_id="env-aliyun-bailian-embedding",
                model_name=settings.LLM_EMBEDDING_MODEL,
                model_type="embedding",
                provider="aliyun-bailian",
                scenario="embedding",
                success=False,
                prompt_tokens=estimate_tokens(values),
                duration_ms=int((time.monotonic() - started) * 1000),
                error_message=str(exc),
            )
            pass
        return [stable_embedding(text) for text in values]
    model = ModelConfig.objects.filter(id=model_id, tenant=tenant).first() if model_id else default_model(tenant, "embedding")
    if not model or model.source == "local":
        return [stable_embedding(text) for text in values]
    params = model.parameters or {}
    base_url = (params.get("base_url") or params.get("baseURL") or "").rstrip("/")
    api_key = params.get("api_key") or params.get("apiKey") or params.get("token")
    model_name = params.get("model") or model.name
    if not base_url:
        return [stable_embedding(text) for text in values]
    started = time.monotonic()
    try:
        vectors = openai_compatible_embedding(base_url, api_key, model_name, values)
        if len(vectors) == len(values):
            record_model_usage(
                tenant,
                model_id=model.id,
                model_name=model_name,
                model_type=model.type,
                provider=model.source,
                scenario="embedding",
                prompt_tokens=estimate_tokens(values),
                total_tokens=estimate_tokens(values),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return _fit_vectors(vectors, settings.APP_EMBEDDING_DIM)
        return [stable_embedding(text) for text in values]
    except Exception as exc:
        record_model_usage(
            tenant,
            model_id=model.id,
            model_name=model_name,
            model_type=model.type,
            provider=model.source,
            scenario="embedding",
            success=False,
            prompt_tokens=estimate_tokens(values),
            duration_ms=int((time.monotonic() - started) * 1000),
            error_message=str(exc),
        )
        return [stable_embedding(text) for text in values]


def openai_compatible_embedding(base_url: str, api_key: str, model_name: str, texts: list[str]) -> list[list[float]]:
    url = f"{base_url.rstrip('/')}/embeddings" if not base_url.endswith("/embeddings") else base_url
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    resp = requests.post(url, headers=headers, json={"model": model_name, "input": texts}, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return [item["embedding"] for item in data.get("data", [])]


def _fit_vectors(vectors: list[list[float]], dim: int) -> list[list[float]]:
    fitted = []
    for vec in vectors:
        if len(vec) == dim:
            fitted.append(vec)
        elif len(vec) > dim:
            fitted.append(vec[:dim])
        else:
            fitted.append(vec + [0.0] * (dim - len(vec)))
    return fitted


def rerank(query: str, results: list[dict], top_k: int | None = None, tenant: Tenant | None = None) -> list[dict]:
    cfg = _role_config("rerank")
    if not results or not cfg["enabled"] or not cfg["configured"]:
        return results[:top_k] if top_k else results
    url = f"{cfg['base_url'].rstrip('/')}/rerank"
    payload = {"model": cfg["model"], "query": query, "documents": [r["content"] for r in results]}
    started = time.monotonic()
    try:
        resp = requests.post(url, headers=_json_headers(), json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        usage = usage_from_response(data)
        if not usage["total_tokens"]:
            usage["prompt_tokens"] = estimate_tokens(payload["query"]) + estimate_tokens(payload["documents"])
            usage["total_tokens"] = usage["prompt_tokens"]
        record_model_usage(
            tenant,
            model_id="env-aliyun-bailian-rerank",
            model_name=cfg["model"],
            model_type="rerank",
            provider="aliyun-bailian",
            scenario="rerank",
            duration_ms=int((time.monotonic() - started) * 1000),
            **usage,
        )
        raw_items = data.get("results") or data.get("output", {}).get("results") or []
        scored = []
        for item in raw_items:
            idx = item.get("index")
            if idx is None:
                idx = item.get("document_index")
            if idx is None or idx >= len(results):
                continue
            result = {**results[int(idx)]}
            score = item.get("relevance_score", item.get("score", result.get("score", 0)))
            result["score"] = float(score)
            result.setdefault("metadata", {})["rerank_model"] = cfg["model"]
            scored.append(result)
        return (scored or results)[:top_k] if top_k else (scored or results)
    except Exception as exc:
        record_model_usage(
            tenant,
            model_id="env-aliyun-bailian-rerank",
            model_name=cfg["model"],
            model_type="rerank",
            provider="aliyun-bailian",
            scenario="rerank",
            success=False,
            prompt_tokens=estimate_tokens(payload["query"]) + estimate_tokens(payload["documents"]),
            duration_ms=int((time.monotonic() - started) * 1000),
            error_message=str(exc),
        )
        return results[:top_k] if top_k else results


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


def _json_headers():
    headers = {"Content-Type": "application/json"}
    if settings.LLM_CHAT_API_KEY:
        headers["Authorization"] = f"Bearer {settings.LLM_CHAT_API_KEY}"
    return headers


def provider_types():
    return [
        {"name": "aliyun-bailian", "display_name": "阿里云百炼", "types": ["chat", "embedding", "rerank", "vlm"]},
        {"name": "openai", "display_name": "OpenAI Compatible", "types": ["chat", "embedding", "rerank", "vlm"]},
        {"name": "ollama", "display_name": "Ollama", "types": ["chat", "embedding"]},
        {"name": "deepseek", "display_name": "DeepSeek", "types": ["chat"]},
        {"name": "qwen", "display_name": "Qwen", "types": ["chat", "embedding"]},
        {"name": "zhipu", "display_name": "Zhipu", "types": ["chat", "embedding", "rerank"]},
        {"name": "gemini", "display_name": "Gemini", "types": ["chat", "embedding", "vlm"]},
    ]


def safe_json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {}
    return value or {}
