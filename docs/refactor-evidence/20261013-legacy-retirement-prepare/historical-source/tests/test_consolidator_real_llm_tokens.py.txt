"""
Run a real-LLM Consolidator token comparison.

This script is intentionally educational rather than a pure unit test:
- it builds Agent-style messages with historical KB tool results, tool_calls,
  retained recent history, and the current turn;
- it calls the real project context_manager path;
- it writes a readable before/after token report.

Run:
    python tests/test_consolidator_real_llm_tokens.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULT_PATH = PROJECT_ROOT / "tests" / "consolidator_real_llm_token_result.txt"
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

from personal_knowledge_base.context_manager import (  # noqa: E402
    CONSOLIDATION_THRESHOLD,
    REDACTED_MARKER,
    _build_history_text,
    _split_history_by_token_budget,
    _split_system_history_current,
    estimate_messages_tokens,
    manage_context_window,
    redact_kb_results,
)
from personal_knowledge_base.model_providers import openai_compatible_chat_raw  # noqa: E402


MAX_TOKENS = 10000


def _filler(label: str, repeat: int) -> str:
    return (
        f"{label}。"
        "客户问题涉及订单 O-2026、知识库 MemoryDesign.md、Neo4j 记忆、"
        "Consolidator 摘要压缩、CompressContext 滑动窗口，以及 KB 检索结果。"
    ) * repeat


def build_realistic_agent_messages() -> list[dict]:
    old_tool_args = {
        "query": "订单 O-2026 记忆系统 Consolidator KB 检索",
        "kb_ids": ["kb-memory", "kb-agent"],
        "top_k": 8,
    }
    current_tool_args = {
        "query": "当前轮次是否会被压缩 当前工具结果是否保留",
        "kb_ids": ["kb-memory"],
        "top_k": 5,
    }
    return [
        {"role": "system", "content": "你是个人知识库 Agent，请基于上下文和工具结果回答。"},
        {"role": "user", "content": _filler("第一轮用户询问项目记忆机制和简历描述是否一致", 18)},
        {
            "role": "assistant",
            "content": _filler("助手决定先调用知识库搜索历史实现依据", 8),
            "tool_calls": [
                {
                    "id": "call-old-kb",
                    "type": "function",
                    "function": {
                        "name": "knowledge_search",
                        "arguments": json.dumps(old_tool_args, ensure_ascii=False),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-old-kb",
            "name": "knowledge_search",
            "content": _filler(
                "历史 KB 工具返回：context_manager.py 显示先脱敏历史 KB，再超过 50% 触发 Consolidator",
                35,
            ),
        },
        {
            "role": "assistant",
            "content": _filler("助手给出阶段性结论：上下文层和跨会话层分别对应不同代码路径", 14),
        },
        {"role": "user", "content": _filler("第二轮用户追问 tool_calls 序列化和压缩输入细节", 14)},
        {
            "role": "assistant",
            "content": _filler("助手解释 tool_calls 是模型请求调用工具的结构化 JSON", 12),
            "tool_calls": [
                {
                    "id": "call-recent-graph",
                    "type": "function",
                    "function": {
                        "name": "query_knowledge_graph",
                        "arguments": json.dumps({"entity": "context_manager.py", "depth": 2}, ensure_ascii=False),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-recent-graph",
            "name": "query_knowledge_graph",
            "content": _filler(
                "近期历史图谱工具返回：Consolidator 节点连接 estimate_messages_tokens 和 manage_context_window",
                12,
            ),
        },
        {
            "role": "assistant",
            "content": _filler("助手继续说明当前轮次由最后一个 user 开始，因此不会进入 to_compress", 10),
        },
        {"role": "user", "content": "请现在用真实 LLM 测试压缩前后的 token 数，并解释当前轮次会不会被压缩。"},
        {
            "role": "assistant",
            "content": "我会先查一下当前轮次相关说明，然后再给你最终比较。",
            "tool_calls": [
                {
                    "id": "call-current-kb",
                    "type": "function",
                    "function": {
                        "name": "knowledge_search",
                        "arguments": json.dumps(current_tool_args, ensure_ascii=False),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-current-kb",
            "name": "knowledge_search",
            "content": _filler("当前轮次 KB 工具返回：当前轮次工具结果必须保留给模型生成答案", 10),
        },
    ]


class RecordingRealLLM:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, messages: list[dict]) -> str:
        started = time.monotonic()
        data = openai_compatible_chat_raw(
            settings.LLM_CHAT_BASE_URL,
            settings.LLM_CHAT_API_KEY,
            settings.LLM_CHAT_MODEL,
            messages,
            temperature=0.2,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
        usage = data.get("usage") or {}
        system_prompt = messages[0].get("content", "")
        call_type = "extract_key_info" if "信息提取助手" in system_prompt else "summarize"
        self.calls.append({
            "type": call_type,
            "duration_ms": duration_ms,
            "input_tokens_estimate": estimate_messages_tokens(messages),
            "provider_usage": usage,
            "prompt_preview": messages[1].get("content", "")[:1200],
            "response": content,
        })
        return content


def _line_for_message(index: int, message: dict) -> str:
    role = message.get("role", "")
    name = f", name={message.get('name')}" if message.get("name") else ""
    tool_id = f", tool_call_id={message.get('tool_call_id')}" if message.get("tool_call_id") else ""
    calls = f", tool_calls={len(message.get('tool_calls') or [])}" if message.get("tool_calls") else ""
    content = str(message.get("content") or "").replace("\n", "\\n")
    if len(content) > 140:
        content = content[:140] + "..."
    return f"{index}. role={role}{name}{tool_id}{calls}, content={content}"


def write_report(
    messages: list[dict],
    compressed: list[dict],
    recorder: RecordingRealLLM,
    to_compress: list[dict],
    to_retain: list[dict],
    current_round: list[dict],
) -> None:
    before_tokens = estimate_messages_tokens(messages)
    after_tokens = estimate_messages_tokens(compressed)
    history_text = _build_history_text(to_compress)
    lines = [
        "=== 真实 LLM Consolidator 压缩 token 对比 ===",
        f"LLM configured: {bool(settings.LLM_CHAT_API_KEY)}",
        f"LLM base_url: {settings.LLM_CHAT_BASE_URL}",
        f"LLM model: {settings.LLM_CHAT_MODEL}",
        f"max_tokens: {MAX_TOKENS}",
        f"50% threshold: {int(MAX_TOKENS * CONSOLIDATION_THRESHOLD)}",
        f"before_tokens_estimate: {before_tokens}",
        f"after_tokens_estimate: {after_tokens}",
        f"token_delta: {before_tokens - after_tokens}",
        f"compression_ratio: {after_tokens / before_tokens:.2%}",
        "",
        "[1] 脱敏后的输入 messages",
    ]
    lines.extend(_line_for_message(i, m) for i, m in enumerate(messages))
    lines.extend([
        "",
        "[2] 切分结果",
        f"to_compress_count: {len(to_compress)}",
        f"to_retain_count: {len(to_retain)}",
        f"current_round_count: {len(current_round)}",
        "当前轮次 current_round：从最后一个 user 开始，到后续 assistant/tool 结束；这部分不会进入 to_compress。",
        "",
        "to_compress roles:",
        json.dumps([m.get("role") for m in to_compress], ensure_ascii=False),
        "to_retain roles:",
        json.dumps([m.get("role") for m in to_retain], ensure_ascii=False),
        "current_round roles:",
        json.dumps([m.get("role") for m in current_round], ensure_ascii=False),
        "",
        "[3] 被送去压缩的 history_text 片段",
        history_text[:2500],
        "",
        "[4] LLM 调用记录",
    ])
    for index, call in enumerate(recorder.calls, 1):
        lines.extend([
            f"LLM call {index}: {call['type']}",
            f"duration_ms: {call['duration_ms']}",
            f"input_tokens_estimate: {call['input_tokens_estimate']}",
            f"provider_usage: {json.dumps(call['provider_usage'], ensure_ascii=False)}",
            "response:",
            call["response"][:2500],
            "",
        ])
    lines.extend([
        "[5] 压缩后的 messages",
    ])
    lines.extend(_line_for_message(i, m) for i, m in enumerate(compressed))
    lines.extend([
        "",
        "[6] 压缩后新增的 system memory message",
        compressed[1].get("content", "") if len(compressed) > 1 else "",
    ])
    RESULT_PATH.write_text("\n".join(lines), encoding="utf-8")


class ConsolidatorRealLLMTokenTest(unittest.TestCase):
    def test_real_llm_consolidation_reduces_tokens_and_preserves_current_turn(self):
        if not settings.LLM_CHAT_API_KEY:
            self.skipTest("LLM_CHAT_API_KEY is not configured; cannot call real LLM.")

        messages = build_realistic_agent_messages()
        before_tokens = estimate_messages_tokens(messages)
        redacted_messages = redact_kb_results(messages)
        system, history, current_round = _split_system_history_current(redacted_messages)
        to_compress, to_retain = _split_history_by_token_budget(history, system, current_round, MAX_TOKENS)
        recorder = RecordingRealLLM()

        compressed = manage_context_window(
            messages,
            max_tokens=MAX_TOKENS,
            llm_caller=recorder,
            enable_redact=True,
            enable_key_info=True,
        )

        after_tokens = estimate_messages_tokens(compressed)
        write_report(redacted_messages, compressed, recorder, to_compress, to_retain, current_round)

        self.assertGreater(before_tokens, int(MAX_TOKENS * CONSOLIDATION_THRESHOLD))
        self.assertLess(after_tokens, before_tokens)
        self.assertEqual([call["type"] for call in recorder.calls], ["extract_key_info", "summarize"])
        self.assertEqual(compressed[0]["role"], "system")
        self.assertIn("[Key Information - Preserved from earlier messages]", compressed[1]["content"])
        self.assertIn("[Memory Summary -", compressed[1]["content"])
        self.assertEqual(compressed[-3:], messages[-3:])
        self.assertIn(REDACTED_MARKER, _build_history_text(to_compress))


if __name__ == "__main__":
    unittest.main(verbosity=2)
