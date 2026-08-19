import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


class ActorMessageVisibilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import django

        django.setup()

    def setUp(self):
        from personal_knowledge_base.models import AgentActor, Message, Session, Tenant

        self.tenant = Tenant.objects.create(name="actor-visibility-tenant", api_key=f"actor-visibility-{uuid4()}")
        self.session = Session.objects.create(tenant=self.tenant, title="visibility test")
        AgentActor.objects.filter(session=self.session).delete()
        Message.objects.filter(session=self.session).delete()

    def tearDown(self):
        from personal_knowledge_base.models import AgentActor, Message, Session, Tenant

        AgentActor.objects.filter(session=self.session).delete()
        Message.objects.filter(session=self.session).delete()
        Session.objects.filter(id=self.session.id).delete()
        Tenant.objects.filter(id=self.tenant.id).delete()

    def test_hidden_actor_messages_are_not_loaded_but_trace_is_serialized(self):
        from personal_knowledge_base.agent_actor import ActorRegistry
        from personal_knowledge_base.models import Message
        from personal_knowledge_base.serializers import message_dict
        from personal_knowledge_base.views import messages_load

        user = Message.objects.create(
            session=self.session,
            request_id="req-1",
            role="user",
            content="问题",
            is_completed=True,
            agent_id="main",
            visible_to_user=True,
        )
        assistant = Message.objects.create(
            session=self.session,
            request_id="req-1",
            role="assistant",
            content="主回答",
            is_completed=True,
            agent_id="main",
            visible_to_user=True,
        )
        Message.objects.create(
            session=self.session,
            request_id="actor-req",
            role="assistant",
            content="子 Actor 隐藏回答",
            is_completed=True,
            agent_id="doc_retriever-1",
            visible_to_user=False,
        )
        main = ActorRegistry.ensure_main_actor(self.session)
        actor = ActorRegistry.create_subagent(
            session=self.session,
            parent_actor=main,
            agent_type="doc_retriever",
            input_prompt="查资料",
            parent_message_id=assistant.id,
            background=False,
        )
        ActorRegistry.mark_completed(actor, output="子 Actor 摘要", duration_ms=30)

        payload = message_dict(assistant)
        self.assertEqual(payload["agent_id"], "main")
        self.assertTrue(payload["visible_to_user"])
        self.assertEqual(payload["actor_traces"][0]["actor_id"], "doc_retriever-1")
        self.assertEqual(payload["actor_traces"][0]["output"], "子 Actor 摘要")

        request = SimpleNamespace(GET={"limit": "10"})
        response = messages_load(request, self.session.id)
        body = response.content.decode("utf-8")

        self.assertIn(user.id, body)
        self.assertIn(assistant.id, body)
        self.assertNotIn("子 Actor 隐藏回答", body)


if __name__ == "__main__":
    unittest.main()
