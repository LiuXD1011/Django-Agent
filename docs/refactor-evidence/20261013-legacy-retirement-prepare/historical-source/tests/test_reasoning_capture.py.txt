#!/usr/bin/env python
"""思考文本（reasoning_content）采集链路单测。

覆盖三处透传点：
1. provider 层 chat_completion_raw 从 message.reasoning_content 提取；
2. 引擎 AgentStep 序列化携带 reasoning；
3. 引擎 thinking 事件 payload 携带 reasoning_content（经 AgentStep 字段验证）。
非思考模型（reasoning_content 为空）行为不变：字段为空串、前端回退 thought。
"""

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.test import override_settings  # noqa: E402

from personal_knowledge_base.agent_engine import AgentEngine, AgentStep  # noqa: E402
from personal_knowledge_base.context_manager import DEFAULT_CONTEXT_WINDOW  # noqa: E402
from personal_knowledge_base.model_providers import chat_completion_raw  # noqa: E402


def _raw_response(content="", reasoning="", tool_calls=None):
    return {
        "choices": [
            {
                "message": {"content": content, "reasoning_content": reasoning, "tool_calls": tool_calls},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


class ChatCompletionRawReasoningTests(unittest.TestCase):
    @override_settings(LLM_USE_ENV_CHAT=True, LLM_CHAT_API_KEY="test-key", LLM_CHAT_BASE_URL="https://example.invalid/v1", LLM_CHAT_MODEL="qwen-test")
    def test_env_model_branch_extracts_reasoning_content(self):
        with patch("personal_knowledge_base.model_providers.openai_compatible_chat_raw", return_value=_raw_response(content="回答", reasoning="推理过程")):
            result = chat_completion_raw(object(), [{"role": "user", "content": "hi"}])
        self.assertEqual(result["content"], "回答")
        self.assertEqual(result["reasoning_content"], "推理过程")

    @override_settings(LLM_USE_ENV_CHAT=True, LLM_CHAT_API_KEY="test-key", LLM_CHAT_BASE_URL="https://example.invalid/v1", LLM_CHAT_MODEL="qwen-test")
    def test_non_thinking_model_gets_empty_reasoning(self):
        with patch("personal_knowledge_base.model_providers.openai_compatible_chat_raw", return_value=_raw_response(content="回答")):
            result = chat_completion_raw(object(), [{"role": "user", "content": "hi"}])
        self.assertEqual(result["reasoning_content"], "")

    @override_settings(LLM_USE_ENV_CHAT=True, LLM_CHAT_API_KEY="test-key", LLM_CHAT_BASE_URL="https://example.invalid/v1", LLM_CHAT_MODEL="qwen-test")
    def test_reasoning_none_normalized_to_empty_string(self):
        payload = _raw_response(content="回答")
        payload["choices"][0]["message"]["reasoning_content"] = None
        with patch("personal_knowledge_base.model_providers.openai_compatible_chat_raw", return_value=payload):
            result = chat_completion_raw(object(), [{"role": "user", "content": "hi"}])
        self.assertEqual(result["reasoning_content"], "")


class AgentStepReasoningTests(unittest.TestCase):
    def test_step_to_dict_includes_reasoning_when_present(self):
        step = AgentStep(iteration=1, thought="回答", reasoning="推理过程")
        d = step.to_dict()
        self.assertEqual(d["reasoning"], "推理过程")
        self.assertEqual(d["thought"], "回答")

    def test_step_to_dict_omits_reasoning_when_empty(self):
        # 非思考模型：不带 reasoning 键，历史消费方零感知
        d = AgentStep(iteration=1, thought="回答").to_dict()
        self.assertNotIn("reasoning", d)


class EngineThinkingEventReasoningTests(unittest.TestCase):
    def _engine_with_fake_llm(self, llm_response):
        class _FakeRegistry:
            def to_openai_tools(self, allowed):
                # 返回一个工具使引擎走 _call_llm_with_tools 分支（真实工具分支）
                return [{"type": "function", "function": {"name": "fake_tool", "description": "fake", "parameters": {"type": "object", "properties": {}}}}]

        engine = AgentEngine.__new__(AgentEngine)
        engine.tenant = SimpleNamespace(id="t")
        engine.session_id = "s"
        engine.user_id = "u"
        engine.config = {"knowledge_base_ids": ["kb"], "allow_actor_tool": False}
        engine.registry = _FakeRegistry()
        engine.max_iterations = 3
        engine.temperature = 0.7
        engine.custom_system_prompt = ""
        engine.allowed_tools = ["fake_tool"]
        engine.model_id = "m"
        engine.context_window = DEFAULT_CONTEXT_WINDOW
        engine.parallel_tools = False
        engine.actor_id = "main"
        engine.parent_message_id = ""
        engine.cancel_check = None

        def fake_call(messages, max_retries=3):
            return llm_response

        engine._call_llm_with_tools = fake_call
        return engine

    def test_thinking_event_carries_reasoning_content(self):
        response = {
            "content": "最终回答",
            "reasoning_content": "先理解问题，再组织答案。",
            "tool_calls": None,
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "provider": "test",
            "model": "qwen-test",
        }
        engine = self._engine_with_fake_llm(response)
        events = []
        result = engine.execute("问题", history=[], context_str="", on_event=lambda t, d: events.append((t, d)))
        thinking = [d for t, d in events if t == "thinking"]
        self.assertTrue(thinking, "thinking 事件缺失")
        self.assertEqual(thinking[-1]["reasoning_content"], "先理解问题，再组织答案。")
        self.assertEqual(thinking[-1]["content"], "最终回答")
        self.assertEqual(result.steps[-1].reasoning, "先理解问题，再组织答案。")
        # thought 语义不变：仍是可见文本（最终回答）
        self.assertEqual(result.steps[-1].thought, "最终回答")


if __name__ == "__main__":
    unittest.main()
