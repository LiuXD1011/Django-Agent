"""
Real provider test for shared immutable prefix cache hit rate.

Run:
    /home/liuxuedeng/anaconda3/envs/django-agent/bin/python tests/test_shared_prefix_cache_hit_rate.py

This script sends real chat-completion requests using the project's configured
chat model. It compares:
- shared-prefix requests: same system prompt + same sorted tools, different user text
- changed-leading-prefix requests: system prompt differs from the first byte

The provider must return usage.prompt_tokens_details.cached_tokens or
usage.cached_tokens for a measurable cache hit rate.
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULT_PATH = PROJECT_ROOT / "tests" / "shared_prefix_cache_hit_rate_result.txt"
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

from personal_knowledge_base.agent_engine import SYSTEM_PROMPT_STATIC_PREFIX  # noqa: E402
from personal_knowledge_base.context_manager import sort_tools_for_cache  # noqa: E402
from personal_knowledge_base.model_usage import usage_from_response  # noqa: E402
from personal_knowledge_base.model_providers import openai_compatible_chat_raw  # noqa: E402


def _tool_definitions() -> list[dict]:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "knowledge_search",
                "description": "Search the user's private knowledge base for relevant chunks.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "thinking",
                "description": "Write a concise reasoning note before answering.",
                "parameters": {
                    "type": "object",
                    "properties": {"thought": {"type": "string"}},
                    "required": ["thought"],
                },
            },
        },
    ]
    return sort_tools_for_cache(tools)


def _large_static_prefix(prefix_extra: str = "") -> str:
    stable_policy = (
        "\n\n## 固定缓存测试前缀\n"
        "以下内容模拟 Agent 的长期稳定系统提示、工具使用规则、回答格式要求。"
        "它在多轮请求中保持字节级不变，用来观察 provider 自动前缀缓存。"
    )
    repeated_rules = "\n".join(
        f"- 稳定规则 {i:03d}: 优先复用知识库上下文，保持工具调用参数格式稳定，回答时引用来源。"
        for i in range(180)
    )
    return prefix_extra + SYSTEM_PROMPT_STATIC_PREFIX + stable_policy + "\n" + repeated_rules


def _messages(question: str, *, prefix_extra: str = "") -> list[dict]:
    return [
        {"role": "system", "content": _large_static_prefix(prefix_extra)},
        {"role": "user", "content": question},
    ]


def _cached_tokens(data: dict) -> int:
    return usage_from_response(data)["cached_tokens"]


def _prompt_tokens(data: dict) -> int:
    return usage_from_response(data)["prompt_tokens"]


def _rate(cached: int, prompt: int) -> float:
    return cached / prompt if prompt else 0.0


def _call(label: str, messages: list[dict], tools: list[dict]) -> dict:
    started = time.monotonic()
    data = openai_compatible_chat_raw(
        settings.LLM_CHAT_BASE_URL,
        settings.LLM_CHAT_API_KEY,
        settings.LLM_CHAT_MODEL,
        messages,
        tools=tools,
        temperature=0.1,
    )
    usage = usage_from_response(data)
    return {
        "label": label,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "prompt_tokens": usage["prompt_tokens"],
        "completion_tokens": usage["completion_tokens"],
        "total_tokens": usage["total_tokens"],
        "cached_tokens": usage["cached_tokens"],
        "cache_hit_rate": _rate(usage["cached_tokens"], usage["prompt_tokens"]),
        "raw_usage": data.get("usage") or {},
    }


class SharedPrefixCacheHitRateRealLLMTest(unittest.TestCase):
    def test_real_provider_reports_shared_prefix_cache_hit_rate(self):
        if not settings.LLM_CHAT_API_KEY:
            raise unittest.SkipTest("LLM_CHAT_API_KEY is not configured")

        tools = _tool_definitions()
        calls = [
            _call("shared_prefix_warmup", _messages("请用一句话回答：上下文压缩是什么？"), tools),
            _call("shared_prefix_second", _messages("请用一句话回答：缓存命中率是什么？"), tools),
            _call("changed_leading_prefix_control", _messages("请用一句话回答：为什么前缀改变会影响缓存？", prefix_extra="本次故意从 system 第一字节改变前缀。\n"), tools),
        ]

        shared_second = calls[1]
        changed_control = calls[2]
        lines = [
            "=== 共享不可变前缀缓存命中率真实测试 ===",
            f"base_url: {settings.LLM_CHAT_BASE_URL}",
            f"model: {settings.LLM_CHAT_MODEL}",
            f"tools_order: {[tool['function']['name'] for tool in tools]}",
            "",
        ]
        for item in calls:
            lines.append(
                f"{item['label']}: prompt_tokens={item['prompt_tokens']}, "
                f"cached_tokens={item['cached_tokens']}, "
                f"cache_hit_rate={item['cache_hit_rate']:.2%}, "
                f"duration_ms={item['duration_ms']}, "
                f"raw_usage={json.dumps(item['raw_usage'], ensure_ascii=False)}"
            )
        lines.extend([
            "",
            "结论口径:",
            "- cache_hit_rate = cached_tokens / prompt_tokens",
            "- shared_prefix_second 表示相同 system prefix + 相同排序 tools 后的第二次请求。",
            "- changed_leading_prefix_control 表示从 system 第一字节就改变前缀的对照请求。",
        ])
        RESULT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

        self.assertGreater(shared_second["prompt_tokens"], 0)
        self.assertIn("cached_tokens", shared_second)
        self.assertGreaterEqual(shared_second["cached_tokens"], 0)
        self.assertGreaterEqual(shared_second["cache_hit_rate"], 0)
        self.assertGreaterEqual(changed_control["cache_hit_rate"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
