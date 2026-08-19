import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


class MultiAgentEngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import django

        django.setup()

    def setUp(self):
        from personal_knowledge_base.models import AgentActor, Session, Tenant

        self.tenant = Tenant.objects.create(name="multi-agent-tenant", api_key=f"multi-agent-{uuid4()}")
        self.session = Session.objects.create(tenant=self.tenant, title="multi agent")
        AgentActor.objects.filter(session=self.session).delete()

    def tearDown(self):
        from personal_knowledge_base.models import AgentActor, Session, Tenant

        AgentActor.objects.filter(session=self.session).delete()
        Session.objects.filter(id=self.session.id).delete()
        Tenant.objects.filter(id=self.tenant.id).delete()

    def test_main_agent_can_call_actor_tool_and_use_subagent_result(self):
        from personal_knowledge_base.agent_engine import AgentEngine
        from personal_knowledge_base.agent_actor import ActorResult

        responses = [
            {
                "content": "我让文档子 Agent 检索。",
                "tool_calls": [
                    {
                        "id": "call-actor-1",
                        "type": "function",
                        "function": {
                            "name": "actor",
                            "arguments": '{"action":"run","subagent_type":"doc_retriever","prompt":"查订单 A"}',
                        },
                    }
                ],
            },
            {"content": "根据子 Agent 结果：订单 A 金额 100 元。", "tool_calls": None},
        ]

        def fake_llm(_messages, max_retries=3):
            return responses.pop(0)

        engine = AgentEngine(
            tenant=self.tenant,
            session_id=self.session.id,
            user_id="user-1",
            agent_config={
                "agent_mode": "multi-agent",
                "allowed_tools": ["actor"],
                "max_rounds": 3,
                "parent_message_id": "assistant-1",
            },
        )

        with patch.object(engine, "_call_llm_with_tools", side_effect=fake_llm):
            with patch("personal_knowledge_base.agent_actor.ActorRunner.run_subagent") as run_subagent:
                run_subagent.return_value = ActorResult(
                    actor_id="doc_retriever-1",
                    status="success",
                    output="订单 A 金额 100 元",
                    duration_ms=10,
                )
                result = engine.execute("订单 A 是多少钱？")

        self.assertEqual(result.content, "根据子 Agent 结果：订单 A 金额 100 元。")
        self.assertEqual(result.steps[0].tool_calls[0].name, "actor")
        self.assertIn("订单 A 金额 100 元", result.steps[0].tool_calls[0].result.output)
        run_subagent.assert_called_once()


if __name__ == "__main__":
    unittest.main()
