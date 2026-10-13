"""
Concrete learning example for context_manager.consolidate_messages.

Run:
    python tests/test_consolidator_example.py

The script injects a fake llm_caller, so it does not call a real model. It
prints the exact input, the token-budget retention boundary, the older history sent
to key-info extraction and summarization, and the final compressed messages.
"""

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from personal_knowledge_base.context_manager import (  # noqa: E402
    CONSOLIDATION_THRESHOLD,
    SUMMARY_TOKEN_RESERVE,
    _split_history_by_token_budget,
    _split_system_history_current,
    consolidate_messages,
    estimate_messages_tokens,
)


MAX_TOKENS = 4000


class FakeConsolidatorLLM:
    """Small deterministic replacement for the real model call."""

    def __init__(self):
        self.calls = []
        self.prompts = []
        self.responses = []

    def __call__(self, messages):
        system_prompt = messages[0]["content"]
        user_prompt = messages[1]["content"]
        self.prompts.append(user_prompt)

        if "信息提取助手" in system_prompt:
            self.calls.append("extract_key_info")
            response = "\n".join(
                [
                    "- 用户想查询订单 O-1001 的物流与退款进度",
                    "- 工具结果显示订单 O-1001 已到达上海分拨中心",
                    "- 待处理事项：继续确认退款预计到账时间",
                ]
            )
            self.responses.append(response)
            return response

        if "对话摘要助手" in system_prompt:
            self.calls.append("summarize")
            response = "用户围绕订单 O-1001 咨询物流状态；系统已确认物流到达上海分拨中心，后续还需跟进退款。"
            self.responses.append(response)
            return response

        raise AssertionError(f"Unexpected LLM system prompt: {system_prompt}")


def _shorten(text, limit=92):
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _message_line(index, message):
    name = f", name={message['name']}" if message.get("name") else ""
    tool_call_id = f", tool_call_id={message['tool_call_id']}" if message.get("tool_call_id") else ""
    calls = ", tool_calls=1" if message.get("tool_calls") else ""
    return f"{index}. role={message['role']}{name}{tool_call_id}{calls}: {_shorten(message.get('content', ''))}"


def _message_indices(all_messages, selected):
    return [all_messages.index(message) for message in selected]


class ConsolidatorExampleTest(unittest.TestCase):
    def test_consolidator_extracts_key_info_and_summarizes_older_history(self):
        messages = [
            {"role": "system", "content": "你是一个知识库问答助手。"},
            {"role": "user", "content": "帮我查订单 O-1001 的物流状态。" * 20},
            {
                "role": "assistant",
                "content": "我会先检索订单知识库和物流记录。" * 20,
                "tool_calls": [
                    {
                        "id": "call-logistics",
                        "type": "function",
                        "function": {"name": "knowledge_search", "arguments": "{\"query\":\"O-1001 物流\"}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-logistics",
                "name": "knowledge_search",
                "content": "物流记录：订单 O-1001 已到达上海分拨中心。" * 20,
            },
            {"role": "assistant", "content": "目前看到包裹已经到达上海分拨中心。" * 20},
            {"role": "user", "content": "那退款状态也帮我一起看一下。" * 20},
            {"role": "assistant", "content": "客服系统已返回订单状态：已签收，退款处理中。" * 20},
            {"role": "user", "content": "现在请总结一下我这个订单的问题。"},
        ]
        fake_llm = FakeConsolidatorLLM()

        before_tokens = estimate_messages_tokens(messages)
        system, history, current_round = _split_system_history_current(messages)
        to_compress, to_retain = _split_history_by_token_budget(history, system, current_round, MAX_TOKENS)
        threshold = int(MAX_TOKENS * CONSOLIDATION_THRESHOLD)
        target_tokens = int(MAX_TOKENS * CONSOLIDATION_THRESHOLD * 0.6)
        keep_budget = target_tokens - estimate_messages_tokens([system]) - estimate_messages_tokens(current_round) - SUMMARY_TOKEN_RESERVE

        compressed = consolidate_messages(
            messages,
            max_tokens=MAX_TOKENS,
            llm_caller=fake_llm,
            extract_key_info=True,
        )

        summary_message = compressed[1]
        summary_content = summary_message["content"]

        print("\n=== Consolidator LLM 摘要压缩学习示例 ===")
        print("目的：演示 token 超过 50% 阈值后，旧历史如何先提取关键信息，再被摘要压缩。")
        print(f"max_tokens: {MAX_TOKENS}")
        print(f"50% trigger threshold: {threshold}")
        print(f"Token-budget target tokens: max_tokens * 0.5 * 0.6 = {target_tokens}")
        print(f"summary reserve: {SUMMARY_TOKEN_RESERVE}")
        print(f"recent-history keep budget: {keep_budget}")
        print(f"Token estimate before: {before_tokens}")
        print(f"Triggered: {before_tokens} > {threshold}")

        print("\n[1] 原始输入 messages")
        for index, message in enumerate(messages):
            print(_message_line(index, message))

        print("\n[2] Consolidator 如何切分这些 messages")
        print("system prompt 保留：message 0")
        print("当前轮次保留：最后一个 user 及其后续消息，也就是 message 7")
        print("历史消息：message 1-6")
        print("近期历史不是按固定条数保留，而是按 token 预算从历史尾部倒序保留。")
        print(f"将被压缩的旧历史 index: {_message_indices(messages, to_compress)}")
        for index in _message_indices(messages, to_compress):
            print(_message_line(index, messages[index]))
        print(f"不压缩、直接保留的近期历史 index: {_message_indices(messages, to_retain)}")
        for index in _message_indices(messages, to_retain):
            print(_message_line(index, messages[index]))
        print("当前轮次 current_round：")
        for index in _message_indices(messages, current_round):
            print(_message_line(index, messages[index]))

        print("\n[3] 第一次 LLM 调用：提取关键信息")
        print("调用类型:", fake_llm.calls[0])
        print("LLM 看到的旧历史 prompt 片段：")
        print(fake_llm.prompts[0][:800])
        print("\nLLM 返回的关键信息 key_info_items：")
        print(fake_llm.responses[0])

        print("\n[4] 第二次 LLM 调用：把同一段旧历史压缩成摘要")
        print("调用类型:", fake_llm.calls[1])
        print("LLM 返回的摘要 summary：")
        print(fake_llm.responses[1])

        print("\n[5] 插入到压缩结果里的新 system 消息")
        print(summary_content)

        print("\n[6] 最终输出 compressed messages")
        for index, message in enumerate(compressed):
            print(_message_line(index, message))
        print("\nCompressed message roles:")
        print(json.dumps([m["role"] for m in compressed], ensure_ascii=False))
        print(f"Messages before: {len(messages)}")
        print(f"Messages after: {len(compressed)}")
        print(f"LLM calls: {fake_llm.calls}")

        self.assertGreater(before_tokens, threshold)
        self.assertEqual(fake_llm.calls, ["extract_key_info", "summarize"])
        self.assertEqual(compressed[0], messages[0])
        self.assertEqual(summary_message["role"], "system")
        self.assertIn("[Key Information - Preserved from earlier messages]", summary_content)
        self.assertIn("用户想查询订单 O-1001 的物流与退款进度", summary_content)
        self.assertRegex(summary_content, r"\[Memory Summary - [1-9]\d* earlier messages consolidated\]")
        self.assertIn("上海分拨中心", summary_content)
        self.assertEqual(compressed[-1]["content"], "现在请总结一下我这个订单的问题。")
        self.assertIn(messages[5], compressed)
        self.assertIn(messages[6], compressed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
