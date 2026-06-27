import json
import time
from typing import Iterable

from django.conf import settings
import requests

from .model_usage import estimate_tokens, record_model_usage, usage_from_response
from .model_types import canonical_model_type, frontend_model_group, model_type_aliases
from .models import ModelConfig, Tenant


class ModelConfigurationError(RuntimeError):
    pass


TEXT_ROLE_TYPES = {
    "chat": "chat",
    "summary": "chat",
    "title": "chat",
    "question": "chat",
    "extract": "chat",
}

def _role_config(role: str) -> dict:
    role = role.lower()
    base = settings.ALIYUN_BAILIAN_BASE_URL
    configured = bool(settings.DASHSCOPE_API_KEY)
    configs = {
        "chat": {
            "type": "KnowledgeQA",
            "model": settings.ALIYUN_BAILIAN_CHAT_MODEL,
            "enabled": settings.WEKNORA_USE_BAILIAN_CHAT,
            "description": "知识库问答与 Agent 对话",
        },
        "summary": {
            "type": "KnowledgeQA",
            "model": settings.ALIYUN_BAILIAN_SUMMARY_MODEL,
            "enabled": settings.WEKNORA_USE_BAILIAN_SUMMARY,
            "description": "知识条目摘要生成",
        },
        "title": {
            "type": "KnowledgeQA",
            "model": settings.ALIYUN_BAILIAN_TITLE_MODEL,
            "enabled": settings.WEKNORA_USE_BAILIAN_TITLE,
            "description": "会话标题生成",
        },
        "question": {
            "type": "KnowledgeQA",
            "model": settings.ALIYUN_BAILIAN_QUESTION_MODEL,
            "enabled": settings.WEKNORA_USE_BAILIAN_QUESTION,
            "description": "推荐问题生成",
        },
        "extract": {
            "type": "KnowledgeQA",
            "model": settings.ALIYUN_BAILIAN_EXTRACT_MODEL,
            "enabled": settings.WEKNORA_USE_BAILIAN_EXTRACT,
            "description": "Wiki 与结构化信息抽取",
        },
        "embedding": {
            "type": "Embedding",
            "model": settings.ALIYUN_BAILIAN_EMBEDDING_MODEL,
            "enabled": settings.WEKNORA_USE_BAILIAN_EMBEDDING,
            "dimension": settings.ALIYUN_BAILIAN_EMBEDDING_DIM,
            "description": "知识切片向量化",
        },
        "rerank": {
            "type": "Rerank",
            "model": settings.ALIYUN_BAILIAN_RERANK_MODEL,
            "enabled": settings.WEKNORA_USE_BAILIAN_RERANK,
            "description": "混合检索候选重排序",
        },
        "vlm": {
            "type": "VLLM",
            "model": settings.ALIYUN_BAILIAN_VLM_MODEL,
            "enabled": settings.WEKNORA_USE_BAILIAN_VLM,
            "description": "图片内容识别与描述",
        },
        "asr": {
            "type": "ASR",
            "model": settings.ALIYUN_BAILIAN_ASR_MODEL,
            "enabled": settings.WEKNORA_USE_BAILIAN_ASR,
            "description": "音频与视频转写",
            "asr_url": settings.ALIYUN_BAILIAN_ASR_URL,
        },
    }
    cfg = configs[role]
    cfg.update({"role": role, "base_url": base, "configured": configured, "api_key_configured": configured})
    return cfg


def bailian_status():
    roles = {role: _role_config(role) for role in ["chat", "summary", "title", "question", "extract", "embedding", "rerank", "vlm", "asr"]}
    return {
        "enabled": roles["chat"]["enabled"],
        "configured": bool(settings.DASHSCOPE_API_KEY),
        "base_url": settings.ALIYUN_BAILIAN_BASE_URL,
        "chat_model": settings.ALIYUN_BAILIAN_CHAT_MODEL,
        "api_key_configured": bool(settings.DASHSCOPE_API_KEY),
        "embedding_dimension": settings.ALIYUN_BAILIAN_EMBEDDING_DIM,
        "local_embedding_dimension": settings.WEKNORA_EMBEDDING_DIM,
        "roles": roles,
    }


def env_models(tenant: Tenant, model_type: str = "") -> list[dict]:
    aliases = model_type_aliases(model_type) if model_type else set()
    grouped: dict[tuple[str, str], dict] = {}
    type_order = {"KnowledgeQA": 0, "Embedding": 1, "Rerank": 2, "VLLM": 3, "ASR": 4}

    for role, cfg in bailian_status()["roles"].items():
        canonical_type = canonical_model_type(cfg["type"])
        if not model_type and canonical_type == "ASR":
            continue
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
                "legacy_type": frontend_model_group(canonical_type),
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
        if "asr_url" in cfg:
            item["parameters"]["asr_url"] = cfg["asr_url"]

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
        data = openai_compatible_chat_raw(cfg["base_url"], settings.DASHSCOPE_API_KEY, cfg["model"], messages)
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
    if (not model_id or is_env_chat_model_id(model_id)) and settings.WEKNORA_USE_BAILIAN_CHAT and settings.DASHSCOPE_API_KEY:
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


def chat_completion_raw(
    tenant: Tenant, messages: list[dict], model_id: str = "",
    tools: list[dict] | None = None, temperature: float | None = None,
) -> dict:
    """
    支持 function calling 的 LLM 调用。
    返回 {"content": str, "tool_calls": list | None}
    """
    if (not model_id or is_env_chat_model_id(model_id)) and settings.WEKNORA_USE_BAILIAN_CHAT and settings.DASHSCOPE_API_KEY:
        base_url = settings.ALIYUN_BAILIAN_BASE_URL
        api_key = settings.DASHSCOPE_API_KEY
        model_name = settings.ALIYUN_BAILIAN_CHAT_MODEL
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

    data = openai_compatible_chat_raw(base_url, api_key, model_name, messages, tools=tools, temperature=temperature)
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
    resp = requests.post(url, headers=headers, json=body, timeout=settings.WEKNORA_CHAT_MODEL_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def embedding(tenant: Tenant, texts: Iterable[str], model_id: str = "") -> list[list[float]]:
    from .search import stable_embedding

    values = list(texts)
    if not values:
        return []
    if not model_id and settings.WEKNORA_USE_BAILIAN_EMBEDDING and settings.DASHSCOPE_API_KEY:
        started = time.monotonic()
        try:
            vectors = openai_compatible_embedding(
                settings.ALIYUN_BAILIAN_BASE_URL,
                settings.DASHSCOPE_API_KEY,
                settings.ALIYUN_BAILIAN_EMBEDDING_MODEL,
                values,
            )
            if len(vectors) == len(values):
                record_model_usage(
                    tenant,
                    model_id="env-aliyun-bailian-embedding",
                    model_name=settings.ALIYUN_BAILIAN_EMBEDDING_MODEL,
                    model_type="embedding",
                    provider="aliyun-bailian",
                    scenario="embedding",
                    prompt_tokens=estimate_tokens(values),
                    total_tokens=estimate_tokens(values),
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
                return _fit_vectors(vectors, settings.WEKNORA_EMBEDDING_DIM)
        except Exception as exc:
            record_model_usage(
                tenant,
                model_id="env-aliyun-bailian-embedding",
                model_name=settings.ALIYUN_BAILIAN_EMBEDDING_MODEL,
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
            return _fit_vectors(vectors, settings.WEKNORA_EMBEDDING_DIM)
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


def transcribe_audio(file_name: str, data: bytes, tenant: Tenant | None = None) -> str:
    cfg = _role_config("asr")
    if not data or not cfg["enabled"] or not cfg["configured"]:
        return ""
    headers = {}
    if settings.DASHSCOPE_API_KEY:
        headers["Authorization"] = f"Bearer {settings.DASHSCOPE_API_KEY}"
    started = time.monotonic()
    try:
        resp = requests.post(
            cfg["asr_url"],
            headers=headers,
            data={"model": cfg["model"]},
            files={"file": (file_name or "audio", data)},
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data.get("text") or data.get("output", {}).get("text") or data.get("transcription") or ""
        tokens = estimate_tokens(text)
        record_model_usage(
            tenant,
            model_id="env-aliyun-bailian-asr",
            model_name=cfg["model"],
            model_type="asr",
            provider="aliyun-bailian",
            scenario="asr",
            completion_tokens=tokens,
            total_tokens=tokens,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return text
    except Exception as exc:
        record_model_usage(
            tenant,
            model_id="env-aliyun-bailian-asr",
            model_name=cfg["model"],
            model_type="asr",
            provider="aliyun-bailian",
            scenario="asr",
            success=False,
            duration_ms=int((time.monotonic() - started) * 1000),
            error_message=str(exc),
        )
        return ""


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
    if settings.DASHSCOPE_API_KEY:
        headers["Authorization"] = f"Bearer {settings.DASHSCOPE_API_KEY}"
    return headers


def provider_types():
    return [
        {"name": "aliyun-bailian", "display_name": "阿里云百炼", "types": ["chat", "embedding", "rerank", "vlm", "asr"]},
        {"name": "openai", "display_name": "OpenAI Compatible", "types": ["chat", "embedding", "rerank", "vlm", "asr"]},
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
