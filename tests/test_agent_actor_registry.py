import os
import sys
import unittest
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


class AgentActorRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import django

        django.setup()

    def setUp(self):
        from personal_knowledge_base.models import AgentActor, Session, Tenant

        self.tenant = Tenant.objects.create(name="actor-test-tenant", api_key=f"actor-test-{uuid4()}")
        self.session = Session.objects.create(tenant=self.tenant, title="actor test")
        AgentActor.objects.filter(session=self.session).delete()

    def tearDown(self):
        from personal_knowledge_base.models import AgentActor, Session, Tenant

        AgentActor.objects.filter(session=self.session).delete()
        Session.objects.filter(id=self.session.id).delete()
        Tenant.objects.filter(id=self.tenant.id).delete()

    def test_ensure_main_actor_and_allocate_subagent_ids(self):
        from personal_knowledge_base.agent_actor import ActorRegistry

        main = ActorRegistry.ensure_main_actor(self.session)
        again = ActorRegistry.ensure_main_actor(self.session)

        self.assertEqual(main.actor_id, "main")
        self.assertEqual(main.mode, "main")
        self.assertEqual(main.id, again.id)

        first = ActorRegistry.allocate_actor_id(self.session, "wiki_researcher")
        second = ActorRegistry.allocate_actor_id(self.session, "wiki_researcher")

        self.assertEqual(first, "wiki_researcher-1")
        self.assertEqual(second, "wiki_researcher-2")

    def test_status_lifecycle_and_cancel_flag(self):
        from personal_knowledge_base.agent_actor import ActorRegistry

        main = ActorRegistry.ensure_main_actor(self.session)
        actor = ActorRegistry.create_subagent(
            session=self.session,
            parent_actor=main,
            agent_type="doc_retriever",
            input_prompt="查一下订单 A",
            parent_message_id="assistant-1",
            background=True,
            tool_whitelist=["knowledge_search"],
        )

        self.assertEqual(actor.status, "pending")
        self.assertEqual(actor.parent_actor_id, "main")
        self.assertTrue(actor.background)

        ActorRegistry.mark_running(actor)
        actor.refresh_from_db()
        self.assertEqual(actor.status, "running")
        self.assertIsNotNone(actor.started_at)

        cancelled = ActorRegistry.cancel_actor(self.session, actor.actor_id)
        actor.refresh_from_db()

        self.assertTrue(cancelled)
        self.assertEqual(actor.status, "cancelled")
        self.assertEqual(actor.last_outcome, "cancelled")
        self.assertTrue(actor.metadata.get("cancel_requested"))


if __name__ == "__main__":
    unittest.main()
