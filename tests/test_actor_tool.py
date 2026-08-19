import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


class ActorToolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import django

        django.setup()

    def setUp(self):
        from personal_knowledge_base.models import AgentActor, Session, Tenant

        self.tenant = Tenant.objects.create(name="actor-tool-tenant", api_key=f"actor-tool-{uuid4()}")
        self.session = Session.objects.create(tenant=self.tenant, title="actor tool test")
        AgentActor.objects.filter(session=self.session).delete()
        self.context = {
            "tenant_id": self.tenant.id,
            "session_id": self.session.id,
            "user_id": "user-1",
            "kb_ids": [],
            "parent_message_id": "assistant-1",
            "actor_id": "main",
            "allow_actor_tool": True,
        }

    def tearDown(self):
        from personal_knowledge_base.models import AgentActor, Session, Tenant

        AgentActor.objects.filter(session=self.session).delete()
        Session.objects.filter(id=self.session.id).delete()
        Tenant.objects.filter(id=self.tenant.id).delete()

    def test_actor_tool_rejects_subagent_recursion(self):
        from personal_knowledge_base.agent_tools import get_tool_registry

        tool = get_tool_registry().get("actor")
        result = tool.execute(
            {"action": "run", "subagent_type": "doc_retriever", "prompt": "查资料"},
            {**self.context, "actor_id": "doc_retriever-1", "allow_actor_tool": False},
        )

        self.assertIn("cannot call actor", result.error)

    def test_actor_tool_run_returns_subagent_result(self):
        from personal_knowledge_base.agent_actor import ActorResult
        from personal_knowledge_base.agent_tools import get_tool_registry

        tool = get_tool_registry().get("actor")
        with patch("personal_knowledge_base.agent_actor.ActorRunner.run_subagent") as run_subagent:
            run_subagent.return_value = ActorResult(
                actor_id="doc_retriever-1",
                status="success",
                output="文档检索结果",
                duration_ms=12,
            )
            result = tool.execute(
                {"action": "run", "subagent_type": "doc_retriever", "prompt": "查资料", "timeout_ms": 1000},
                self.context,
            )

        self.assertFalse(result.error)
        self.assertIn("doc_retriever-1", result.output)
        self.assertIn("文档检索结果", result.output)
        run_subagent.assert_called_once()

    def test_actor_tool_spawn_status_wait_cancel(self):
        from personal_knowledge_base.agent_actor import ActorRegistry
        from personal_knowledge_base.agent_tools import get_tool_registry

        tool = get_tool_registry().get("actor")
        main = ActorRegistry.ensure_main_actor(self.session)

        with patch("personal_knowledge_base.agent_actor.ActorRunner.spawn_subagent") as spawn_subagent:
            spawn_subagent.return_value = ActorRegistry.create_subagent(
                session=self.session,
                parent_actor=main,
                agent_type="wiki_researcher",
                input_prompt="研究 Wiki",
                parent_message_id="assistant-1",
                background=True,
            )
            spawn_result = tool.execute(
                {"action": "spawn", "subagent_type": "wiki_researcher", "prompt": "研究 Wiki"},
                self.context,
            )

        self.assertIn("wiki_researcher-1", spawn_result.output)

        status_result = tool.execute({"action": "status", "actor_id": "wiki_researcher-1"}, self.context)
        self.assertIn("pending", status_result.output)

        cancel_result = tool.execute({"action": "cancel", "actor_id": "wiki_researcher-1"}, self.context)
        self.assertIn("cancelled", cancel_result.output)

        wait_result = tool.execute({"action": "wait", "actor_id": "wiki_researcher-1", "timeout_ms": 10}, self.context)
        self.assertIn("cancelled", wait_result.output)


if __name__ == "__main__":
    unittest.main()
