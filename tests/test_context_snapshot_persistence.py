import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


class ContextSnapshotPersistenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import django

        django.setup()

    def setUp(self):
        from personal_knowledge_base.models import ContextSnapshot, Message, Session, Tenant

        self.tenant = Tenant.objects.create(name="snapshot-test-tenant", api_key=f"snapshot-test-{uuid4()}")
        self.session = Session.objects.create(tenant=self.tenant, title="snapshot test")
        ContextSnapshot.objects.filter(session=self.session).delete()
        Message.objects.filter(session=self.session).delete()

    def tearDown(self):
        from personal_knowledge_base.models import ContextSnapshot, Message, Session, Tenant

        ContextSnapshot.objects.filter(session=self.session).delete()
        Message.objects.filter(session=self.session).delete()
        Session.objects.filter(id=self.session.id).delete()
        Tenant.objects.filter(id=self.tenant.id).delete()

    def test_build_persistent_summary_payload_reuses_consolidator_format(self):
        from personal_knowledge_base.context_manager import build_persistent_summary_payload

        llm_calls = []

        def fake_llm(messages):
            llm_calls.append(messages)
            prompt = messages[-1]["content"]
            if "请提取关键信息" in prompt:
                return "- 用户要分析订单 A\n- 工具查到订单 A 金额 100 元"
            return "用户围绕订单 A 进行了查询，工具返回金额 100 元，最终需要继续跟进发货状态。"

        messages = [
            {"role": "user", "content": "帮我查订单 A。" + "请保留这段历史细节。" * 80},
            {
                "role": "assistant",
                "content": "我先查知识库。" + "需要结合历史检索结果。" * 40,
                "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "knowledge_search", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "call-1", "name": "knowledge_search", "content": "订单 A 金额 100 元。" * 120},
            {"role": "assistant", "content": "订单 A 金额 100 元。" + "历史结论已确认。" * 40},
        ]

        payload = build_persistent_summary_payload(messages, llm_caller=fake_llm)

        self.assertIn("[Key Information - Preserved from earlier messages]", payload["content"])
        self.assertIn("订单 A 金额 100 元", payload["content"])
        self.assertIn("[Memory Summary - 4 earlier messages consolidated]", payload["content"])
        self.assertEqual(payload["source_message_count"], 4)
        self.assertGreater(payload["token_before"], payload["token_after"])
        self.assertEqual(len(payload["key_info"]), 2)
        self.assertEqual(len(llm_calls), 2)

    def test_context_snapshot_replaces_old_history_and_keeps_boundary_tail(self):
        from personal_knowledge_base.context_snapshot import (
            build_history_with_snapshot,
            clear_context_snapshots,
            maybe_update_context_snapshot,
        )
        from personal_knowledge_base.models import ContextSnapshot, Message

        old_user = Message.objects.create(
            session=self.session,
            request_id="old",
            role="user",
            content="旧问题" + "很多细节" * 200,
            is_completed=True,
        )
        Message.objects.create(
            session=self.session,
            request_id="old",
            role="assistant",
            content="旧回答" + "很多结论" * 200,
            rendered_content="旧回答" + "很多结论" * 200,
            is_completed=True,
        )
        new_user = Message.objects.create(
            session=self.session,
            request_id="new",
            role="user",
            content="新问题",
            rendered_content="<context>新问题增强</context>",
            is_completed=True,
        )
        Message.objects.create(
            session=self.session,
            request_id="new",
            role="assistant",
            content="新回答",
            rendered_content="新回答",
            is_completed=True,
        )

        def fake_llm(messages):
            prompt = messages[-1]["content"]
            if "请提取关键信息" in prompt:
                return "- 旧问题已经查询\n- 旧回答包含很多结论"
            return "旧轮次已压缩为摘要，保留订单和结论。"

        snapshot = maybe_update_context_snapshot(
            session=self.session,
            mode="rag",
            max_rounds=1,
            llm_caller=fake_llm,
            max_tokens=200,
        )

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.boundary_message_id, new_user.id)
        self.assertTrue(snapshot.is_active)
        self.assertIn("[Memory Summary", snapshot.content)
        self.assertGreater(snapshot.token_before, snapshot.token_after)

        history = build_history_with_snapshot(
            session=self.session,
            mode="rag",
            current_user_message=SimpleNamespace(id="current"),
            max_rounds=5,
            history_builder=lambda rows, max_rounds: [{"role": m.role, "content": m.rendered_content or m.content} for m in rows],
        )

        self.assertEqual(history[0]["role"], "system")
        self.assertIn("旧轮次已压缩为摘要", history[0]["content"])
        replayed_text = "\n".join(m["content"] for m in history[1:])
        self.assertIn("<context>新问题增强</context>", replayed_text)
        self.assertIn("新回答", replayed_text)
        self.assertNotIn("旧问题很多细节", replayed_text)

        debug_path = PROJECT_ROOT / "tests" / "context_snapshot_debug_result.txt"
        debug_path.write_text(
            "\n".join([
                "Context Snapshot Debug",
                f"token_before={snapshot.token_before}",
                f"token_after={snapshot.token_after}",
                f"boundary_message_id={snapshot.boundary_message_id}",
                f"boundary_created_at={snapshot.boundary_created_at.isoformat() if snapshot.boundary_created_at else ''}",
                "next_messages=",
                *[f"- {item['role']}: {item['content'][:120]}" for item in history],
            ]),
            encoding="utf-8",
        )

        replacement = maybe_update_context_snapshot(
            session=self.session,
            mode="rag",
            max_rounds=1,
            llm_caller=fake_llm,
            max_tokens=60,
        )

        self.assertIsNotNone(replacement)
        self.assertEqual(ContextSnapshot.objects.filter(session=self.session, mode="rag", is_active=True).count(), 1)
        self.assertGreater(ContextSnapshot.objects.filter(session=self.session, mode="rag", is_active=False).count(), 0)

        clear_context_snapshots(self.session)
        self.assertEqual(ContextSnapshot.objects.filter(session=self.session).count(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
