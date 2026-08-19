import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


class AgentHistoryMemoryTest(unittest.TestCase):
    def test_rebuilds_agent_history_with_tool_calls_and_tool_result_names(self):
        from personal_knowledge_base.agent_history import build_agent_history_messages

        history = [
            SimpleNamespace(
                request_id="req-1",
                role="user",
                content="原始问题",
                rendered_content="<context>增强后的问题</context>",
                agent_steps=None,
                created_at=1,
            ),
            SimpleNamespace(
                request_id="req-1",
                role="assistant",
                content="最终回答",
                rendered_content="",
                created_at=2,
                agent_steps=[
                    {
                        "iteration": 1,
                        "thought": "我先查知识库。",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "name": "knowledge_search",
                                "arguments": {"query": "订单 A"},
                                "result": {"output": "订单 A 的历史 KB 结果"},
                            }
                        ],
                    }
                ],
            ),
        ]

        messages = build_agent_history_messages(history, max_rounds=5)

        self.assertEqual(messages[0], {"role": "user", "content": "<context>增强后的问题</context>"})
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[1]["content"], "我先查知识库。")
        self.assertEqual(messages[1]["tool_calls"][0]["function"]["name"], "knowledge_search")
        self.assertEqual(messages[2]["role"], "tool")
        self.assertEqual(messages[2]["name"], "knowledge_search")
        self.assertEqual(messages[2]["tool_call_id"], "call-1")
        self.assertEqual(messages[2]["content"], "订单 A 的历史 KB 结果")
        self.assertEqual(messages[3], {"role": "assistant", "content": "最终回答"})

    def test_agent_history_strips_think_and_compacts_tool_output(self):
        from personal_knowledge_base.agent_history import build_agent_history_messages

        history = [
            SimpleNamespace(
                request_id="req-1",
                role="user",
                content="原始问题",
                rendered_content="",
                images=[{"caption": "图片里是一张发票"}],
                attachments=[{"file_name": "invoice.pdf", "file_size": 1024}],
                agent_steps=None,
            ),
            SimpleNamespace(
                request_id="req-1",
                role="assistant",
                content="<think>内部推理不要回放</think>\n最终回答",
                agent_steps=[
                    {
                        "thought": "我先查资料。",
                        "tool_calls": [
                            {
                                "id": "call-search",
                                "name": "knowledge_search",
                                "arguments": {"query": "发票"},
                                "result": {"output": "检索结果" * 800},
                            },
                        ],
                    }
                ],
            ),
        ]

        messages = build_agent_history_messages(history, max_rounds=5)

        self.assertIn("[用户上传图片内容]", messages[0]["content"])
        self.assertIn("图片里是一张发票", messages[0]["content"])
        self.assertIn("[用户上传附件]", messages[0]["content"])
        self.assertIn("invoice.pdf", messages[0]["content"])
        self.assertEqual(len(messages[1]["tool_calls"]), 1)
        self.assertEqual(messages[1]["tool_calls"][0]["function"]["name"], "knowledge_search")
        self.assertLessEqual(len(messages[2]["content"]), 1200)
        self.assertEqual(messages[-1], {"role": "assistant", "content": "最终回答"})
        self.assertNotIn("内部推理", messages[-1]["content"])

    def test_builds_agent_context_when_only_memory_is_present(self):
        from personal_knowledge_base.agent_history import build_agent_context_if_needed

        context = build_agent_context_if_needed(
            lambda refs, memory, kb_names: "\n\n".join(part for part in [kb_names, memory, str(len(refs))] if part),
            refs=[],
            memory_context="<relevant_memory>\n- 用户关心订单 A\n</relevant_memory>",
            kb_names="",
        )

        self.assertIn("<relevant_memory>", context)
        self.assertIn("0", context)

    def test_normalizes_max_rounds_from_config_values(self):
        from personal_knowledge_base.agent_history import normalize_max_rounds

        self.assertEqual(normalize_max_rounds("7"), 7)
        self.assertEqual(normalize_max_rounds("bad"), 5)
        self.assertEqual(normalize_max_rounds(0), 1)
        self.assertEqual(normalize_max_rounds(99), 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
