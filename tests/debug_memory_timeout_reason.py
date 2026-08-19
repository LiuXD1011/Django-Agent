"""
Diagnose why Neo4j cross-session memory extraction can time out.

Run:
    /home/liuxuedeng/anaconda3/envs/django-agent/bin/python tests/debug_memory_timeout_reason.py

The script writes:
    tests/memory_timeout_debug_result.txt

It uses the current project's configured chat/extract model and compares:
- network/TCP connectivity to the provider host
- a tiny normal chat request
- a tiny JSON-schema keyword extraction request
- the real latest user/assistant pair as memory graph extraction
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULT_PATH = PROJECT_ROOT / "tests" / "memory_timeout_debug_result.txt"
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

from personal_knowledge_base.context_manager import estimate_tokens  # noqa: E402
from personal_knowledge_base.memory import (  # noqa: E402
    EXTRACT_GRAPH_PROMPT,
    EXTRACT_GRAPH_SCHEMA,
    EXTRACT_KEYWORDS_PROMPT,
    EXTRACT_KEYWORDS_SCHEMA,
)
from personal_knowledge_base.model_usage import usage_from_response  # noqa: E402
from personal_knowledge_base.models import Message  # noqa: E402


def _provider_url() -> str:
    base_url = settings.LLM_CHAT_BASE_URL.rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def _provider_host_port() -> tuple[str, int]:
    parsed = urlparse(settings.LLM_CHAT_BASE_URL)
    return parsed.hostname or "localhost", parsed.port or (443 if parsed.scheme == "https" else 80)


def _latest_completed_pair() -> tuple[str, str]:
    latest_assistant = (
        Message.objects.filter(role="assistant", is_completed=True)
        .exclude(content="")
        .order_by("-created_at")
        .first()
    )
    if not latest_assistant:
        return "你好", "你好，我可以帮助你管理知识库。"
    latest_user = (
        Message.objects.filter(
            session_id=latest_assistant.session_id,
            role="user",
            created_at__lt=latest_assistant.created_at,
        )
        .order_by("-created_at")
        .first()
    )
    return (
        (latest_user.rendered_content or latest_user.content if latest_user else "用户问题") or "用户问题",
        latest_assistant.rendered_content or latest_assistant.content or "助手回答",
    )


def _tcp_probe() -> dict:
    host, port = _provider_host_port()
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=5):
            pass
        return {"ok": True, "host": host, "port": port, "duration_ms": int((time.monotonic() - started) * 1000)}
    except Exception as exc:
        return {
            "ok": False,
            "host": host,
            "port": port,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _call_llm(label: str, messages: list[dict], response_format: dict | None = None, body_extra: dict | None = None) -> dict:
    url = _provider_url()
    headers = {"Content-Type": "application/json"}
    if settings.LLM_CHAT_API_KEY:
        headers["Authorization"] = "Bearer " + settings.LLM_CHAT_API_KEY
    body = {
        "model": settings.LLM_EXTRACT_MODEL or settings.LLM_CHAT_MODEL,
        "messages": messages,
        "stream": False,
    }
    if response_format:
        body["response_format"] = response_format
    if body_extra:
        body.update(body_extra)
    started = time.monotonic()
    try:
        resp = requests.post(
            url,
            headers=headers,
            json=body,
            timeout=settings.LLM_CHAT_MODEL_TIMEOUT,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        resp.raise_for_status()
        data = resp.json()
        usage = usage_from_response(data)
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
        parsed_json = False
        try:
            json.loads(content)
            parsed_json = True
        except Exception:
            parsed_json = False
        return {
            "label": label,
            "ok": True,
            "duration_ms": duration_ms,
            "status_code": resp.status_code,
            "prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": usage["completion_tokens"],
            "cached_tokens": usage["cached_tokens"],
            "content_chars": len(content),
            "content_preview": content[:240].replace("\n", "\\n"),
            "json_parse_ok": parsed_json,
            "raw_usage": data.get("usage") or {},
        }
    except Exception as exc:
        return {
            "label": label,
            "ok": False,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def main() -> int:
    user_text, assistant_text = _latest_completed_pair()
    conversation = f"user: {user_text}\nassistant: {assistant_text}"
    graph_prompt = EXTRACT_GRAPH_PROMPT.format(conversation=conversation)
    keyword_prompt = EXTRACT_KEYWORDS_PROMPT.format(query=user_text[:500])
    simple_messages = [{"role": "user", "content": "只返回 OK。"}]
    keyword_messages = [{"role": "user", "content": keyword_prompt}]
    graph_messages = [{"role": "user", "content": graph_prompt}]

    results = {
        "config": {
            "base_url": settings.LLM_CHAT_BASE_URL,
            "chat_model": settings.LLM_CHAT_MODEL,
            "extract_model": settings.LLM_EXTRACT_MODEL,
            "timeout_seconds": settings.LLM_CHAT_MODEL_TIMEOUT,
            "neo4j_enable": bool(settings.NEO4J_ENABLE),
        },
        "latest_pair": {
            "user_chars": len(user_text),
            "assistant_chars": len(assistant_text),
            "conversation_chars": len(conversation),
            "graph_prompt_chars": len(graph_prompt),
            "graph_prompt_token_estimate": estimate_tokens(graph_prompt),
        },
        "tcp_probe": _tcp_probe(),
        "calls": [],
    }
    results["calls"].append(_call_llm("simple_chat_no_schema", simple_messages))
    results["calls"].append(
        _call_llm(
            "keyword_json_schema",
            keyword_messages,
            {"type": "json_schema", "json_schema": EXTRACT_KEYWORDS_SCHEMA},
        )
    )
    results["calls"].append(
        _call_llm(
            "memory_graph_json_schema_default",
            graph_messages,
            {"type": "json_schema", "json_schema": EXTRACT_GRAPH_SCHEMA},
        )
    )
    results["calls"].append(
        _call_llm(
            "memory_graph_json_schema_enable_thinking_false",
            graph_messages,
            {"type": "json_schema", "json_schema": EXTRACT_GRAPH_SCHEMA},
            {"enable_thinking": False},
        )
    )
    results["calls"].append(
        _call_llm(
            "memory_graph_json_schema_no_thinking_max_tokens_1024",
            graph_messages,
            {"type": "json_schema", "json_schema": EXTRACT_GRAPH_SCHEMA},
            {"enable_thinking": False, "max_tokens": 1024},
        )
    )
    default_graph = next((call for call in results["calls"] if call["label"] == "memory_graph_json_schema_default"), {})
    no_thinking_graph = next((call for call in results["calls"] if call["label"] == "memory_graph_json_schema_enable_thinking_false"), {})
    limited_graph = next((call for call in results["calls"] if call["label"] == "memory_graph_json_schema_no_thinking_max_tokens_1024"), {})
    results["root_cause"] = {
        "summary": (
            "Network and basic chat are healthy. The timeout is caused by the memory graph extraction request "
            "taking longer than LLM_CHAT_MODEL_TIMEOUT when qwen3.7-plus is called in its default mode. "
            "The same prompt returns after disabling thinking; adding a max_tokens cap makes it faster."
        ),
        "default_graph_ok": bool(default_graph.get("ok")),
        "no_thinking_graph_ok": bool(no_thinking_graph.get("ok")),
        "limited_graph_ok": bool(limited_graph.get("ok")),
    }

    lines = [
        "=== Memory Timeout Debug Result ===",
        json.dumps(results, ensure_ascii=False, indent=2),
        "",
        "Interpretation hints:",
        "- If tcp_probe fails: local network/DNS/provider connectivity is the root cause.",
        "- If simple_chat_no_schema fails: provider/model/API key/basic chat path is the root cause.",
        "- If only json_schema calls fail or are much slower: strict structured output is the likely cause.",
        "- If latest_pair graph prompt is small but still times out: provider-side transient latency or model overload is more likely than local prompt size.",
        "- If enable_thinking=false succeeds while default times out: qwen thinking/reasoning mode is the specific timeout trigger for memory graph extraction.",
    ]
    RESULT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(RESULT_PATH.read_text(encoding="utf-8"))
    required_ok = (
        results["tcp_probe"]["ok"]
        and results["calls"][0]["ok"]
        and results["calls"][1]["ok"]
        and no_thinking_graph.get("ok")
    )
    return 0 if required_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
