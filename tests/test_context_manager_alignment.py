import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import personal_knowledge_base.context_manager as context_manager  # noqa: E402
from personal_knowledge_base.context_manager import (  # noqa: E402
    REDACTED_MARKER,
    consolidate_messages,
    estimate_messages_tokens,
    redact_kb_results,
)


class FakeLLM:
    def __init__(self):
        self.calls = []

    def __call__(self, messages):
        system = messages[0]["content"]
        user = messages[1]["content"]
        if "信息提取助手" in system:
            self.calls.append(("extract", user))
            return "- 保留的关键信息：订单 A 的知识库结果需要继续使用"
        if "对话摘要助手" in system:
            self.calls.append(("summary", user))
            return "早期对话主要围绕订单 A 的资料检索和初步判断。"
        raise AssertionError(system)


class ContextManagerAlignmentTest(unittest.TestCase):
    def test_redacts_only_historical_kb_tool_results_and_infers_tool_name(self):
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "上一轮：查订单 A"},
            {
                "role": "assistant",
                "content": "调用工具",
                "tool_calls": [
                    {"id": "old-call", "type": "function", "function": {"name": "knowledge_search", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "old-call", "content": "历史 KB 原始大段结果"},
            {"role": "assistant", "content": "上一轮结论"},
            {"role": "user", "content": "当前轮：继续查订单 B"},
            {
                "role": "assistant",
                "content": "当前轮调用工具",
                "tool_calls": [
                    {"id": "new-call", "type": "function", "function": {"name": "knowledge_search", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "new-call", "content": "当前轮 KB 结果必须保留给模型回答"},
        ]

        redacted = redact_kb_results(messages)

        self.assertEqual(redacted[3]["content"], REDACTED_MARKER)
        self.assertEqual(redacted[7]["content"], "当前轮 KB 结果必须保留给模型回答")

    def test_consolidator_uses_token_budget_and_keeps_tool_call_group_together(self):
        messages = [
            {"role": "system", "content": "你是助手。"},
            {"role": "user", "content": "很早之前的问题。" * 240},
            {"role": "assistant", "content": "很早之前的回答。" * 240},
            {"role": "user", "content": "最近历史：查订单 A"},
            {
                "role": "assistant",
                "content": "我调用知识库。",
                "tool_calls": [
                    {
                        "id": "call-a",
                        "type": "function",
                        "function": {"name": "knowledge_search", "arguments": "{\"query\":\"订单 A\"}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-a", "name": "knowledge_search", "content": "订单 A 的关键检索结果"},
            {"role": "assistant", "content": "订单 A 的近期结论。"},
            {"role": "user", "content": "当前问题：基于前面信息总结。"},
        ]
        fake_llm = FakeLLM()

        compressed = consolidate_messages(
            messages,
            max_tokens=2000,
            llm_caller=fake_llm,
            extract_key_info=True,
        )

        tool_call_positions = [
            i for i, msg in enumerate(compressed)
            if msg.get("role") == "assistant" and msg.get("tool_calls")
        ]
        tool_positions = [
            i for i, msg in enumerate(compressed)
            if msg.get("role") == "tool" and msg.get("tool_call_id") == "call-a"
        ]
        summary_content = compressed[1]["content"]

        self.assertEqual(fake_llm.calls[0][0], "extract")
        self.assertEqual(fake_llm.calls[1][0], "summary")
        self.assertIn("[Key Information - Preserved from earlier messages]", summary_content)
        self.assertRegex(summary_content, r"\[Memory Summary - [1-9]\d* earlier messages consolidated\]")
        self.assertEqual(len(tool_call_positions), 1)
        self.assertEqual(len(tool_positions), 1)
        self.assertLess(tool_call_positions[0], tool_positions[0])
        self.assertEqual(compressed[-1]["content"], "当前问题：基于前面信息总结。")

    def test_sliding_window_compresses_to_eighty_percent_and_preserves_current_turn(self):
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "旧问题一。" * 120},
            {"role": "assistant", "content": "旧回答一。" * 120},
            {"role": "user", "content": "旧问题二。" * 120},
            {"role": "assistant", "content": "旧回答二。" * 120},
            {"role": "user", "content": "当前轮问题"},
            {"role": "assistant", "content": "当前轮已经生成的中间内容"},
        ]
        current_tokens = estimate_messages_tokens(messages)
        max_tokens = int(current_tokens / 0.9)

        compressed = context_manager._sliding_window_compress(messages, max_tokens)

        self.assertLess(len(compressed), len(messages))
        self.assertEqual(compressed[0], messages[0])
        self.assertEqual(compressed[-2:], messages[-2:])
        self.assertLessEqual(
            estimate_messages_tokens(compressed),
            int(max_tokens * context_manager.CONTEXT_THRESHOLD),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
