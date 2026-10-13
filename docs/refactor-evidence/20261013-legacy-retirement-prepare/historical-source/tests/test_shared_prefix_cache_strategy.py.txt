import json
import os
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from personal_knowledge_base.agent_engine import SYSTEM_PROMPT_STATIC_PREFIX
from personal_knowledge_base.context_manager import sort_tools_for_cache


def build_payload(dynamic_question: str, tools: list[dict]) -> dict:
    return {
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT_STATIC_PREFIX
                + "\n\n## 固定测试说明\n请保持这段 system 前缀完全不变，用于验证自动前缀缓存。",
            },
            {"role": "user", "content": dynamic_question},
        ],
        "tools": sort_tools_for_cache(tools),
    }


class SharedPrefixCacheStrategyTest(unittest.TestCase):
    def test_shared_prefix_payload_keeps_system_and_tool_bytes_stable(self):
        tools = [
            {"type": "function", "function": {"name": "z_tool", "description": "Z", "parameters": {"type": "object", "properties": {}}}},
            {"type": "function", "function": {"name": "a_tool", "description": "A", "parameters": {"type": "object", "properties": {}}}},
        ]
        first = build_payload("第一轮问题：介绍上下文压缩。", tools)
        second = build_payload("第二轮问题：解释缓存命中率。", tools)

        first_prefix = json.dumps(
            {"messages": first["messages"][:1], "tools": first["tools"]},
            ensure_ascii=False,
            sort_keys=True,
        )
        second_prefix = json.dumps(
            {"messages": second["messages"][:1], "tools": second["tools"]},
            ensure_ascii=False,
            sort_keys=True,
        )

        self.assertEqual(first_prefix, second_prefix)
        self.assertEqual([tool["function"]["name"] for tool in first["tools"]], ["a_tool", "z_tool"])
        self.assertNotEqual(first["messages"][1]["content"], second["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
