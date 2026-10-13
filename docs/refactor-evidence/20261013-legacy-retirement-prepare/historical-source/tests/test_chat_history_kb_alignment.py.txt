import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


class ChatHistoryKBAlignmentTest(unittest.TestCase):
    def test_render_qa_pair_contains_user_and_assistant(self):
        from personal_knowledge_base.chat_history_kb import render_qa_pair_for_index

        user = SimpleNamespace(content="用户问了什么", rendered_content="<context>增强后的用户问题</context>")
        assistant = SimpleNamespace(content="助手回答")

        content = render_qa_pair_for_index(user, assistant)

        self.assertIn("User:", content)
        self.assertIn("<context>增强后的用户问题</context>", content)
        self.assertIn("Assistant:", content)
        self.assertIn("助手回答", content)

    def test_format_chat_history_context_sanitizes_internal_kb_name(self):
        from personal_knowledge_base.chat_history_kb import format_chat_history_context

        tenant = SimpleNamespace()
        results = [
            {
                "knowledge_title": "__chat_history__",
                "knowledge_base_name": "__chat_history__",
                "content": "用户曾经问过 __chat_history__ 有哪些知识库",
                "score": 0.9,
            }
        ]

        context = format_chat_history_context(results, tenant=tenant)

        self.assertIn("<chat_history_context>", context)
        self.assertIn("[internal history]", context)
        self.assertNotIn("__chat_history__", context)

if __name__ == "__main__":
    unittest.main(verbosity=2)
