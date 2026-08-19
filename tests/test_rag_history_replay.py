import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


class RagHistoryReplayTest(unittest.TestCase):
    def test_builds_recent_complete_rag_history_pairs(self):
        from personal_knowledge_base.agent_history import build_rag_history_messages

        history = [
            SimpleNamespace(request_id="old", role="user", content="旧问题", rendered_content="", created_at=1),
            SimpleNamespace(request_id="old", role="assistant", content="旧回答", created_at=2),
            SimpleNamespace(request_id="new", role="user", content="新问题", rendered_content="<context>新增强问题</context>", created_at=3),
            SimpleNamespace(request_id="new", role="assistant", content="<think>隐藏</think>新回答", created_at=4),
        ]

        messages = build_rag_history_messages(history, max_rounds=1)

        self.assertEqual(messages, [
            {"role": "user", "content": "<context>新增强问题</context>"},
            {"role": "assistant", "content": "新回答"},
        ])

    def test_builds_normal_rag_llm_messages_order(self):
        from personal_knowledge_base.agent_history import build_normal_rag_messages

        messages = build_normal_rag_messages(
            system_prompt="system",
            history_messages=[{"role": "user", "content": "历史问"}, {"role": "assistant", "content": "历史答"}],
            user_prompt="当前增强问题",
        )

        self.assertEqual(messages, [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "历史问"},
            {"role": "assistant", "content": "历史答"},
            {"role": "user", "content": "当前增强问题"},
        ])


if __name__ == "__main__":
    unittest.main(verbosity=2)
