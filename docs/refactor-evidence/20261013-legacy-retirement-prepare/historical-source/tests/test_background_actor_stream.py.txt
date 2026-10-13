import os
import sys
import unittest
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


class BackgroundActorStreamTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import django

        django.setup()

    def setUp(self):
        from personal_knowledge_base.models import AgentActor, Session, Tenant

        self.tenant = Tenant.objects.create(name="actor-stream-tenant", api_key=f"actor-stream-{uuid4()}")
        self.session = Session.objects.create(tenant=self.tenant, title="stream test")
        AgentActor.objects.filter(session=self.session).delete()

    def tearDown(self):
        from personal_knowledge_base.models import AgentActor, Session, Tenant
        from personal_knowledge_base.stream_manager import stream_manager

        stream_manager.remove_stream("assistant-1")
        AgentActor.objects.filter(session=self.session).delete()
        Session.objects.filter(id=self.session.id).delete()
        Tenant.objects.filter(id=self.tenant.id).delete()

    def test_actor_events_are_replayable_from_stream_manager_offset_zero(self):
        from personal_knowledge_base.agent_actor import ActorRegistry, emit_actor_event
        from personal_knowledge_base.stream_manager import stream_manager

        stream_manager.create_stream("assistant-1", self.session.id)
        main = ActorRegistry.ensure_main_actor(self.session)
        actor = ActorRegistry.create_subagent(
            session=self.session,
            parent_actor=main,
            agent_type="wiki_researcher",
            input_prompt="研究 Wiki",
            parent_message_id="assistant-1",
            background=True,
        )

        emit_actor_event("assistant-1", "actor_started", actor, {"summary": "开始"})
        ActorRegistry.mark_completed(actor, output="Wiki 摘要", duration_ms=40)
        actor.refresh_from_db()
        emit_actor_event("assistant-1", "actor_completed", actor, {"output": actor.output})

        events = stream_manager.get_events("assistant-1", 0)
        self.assertEqual([event.event_type for event in events], ["actor_started", "actor_completed"])
        self.assertEqual(events[0].data["response_type"], "actor_started")
        self.assertEqual(events[1].data["actor_id"], "wiki_researcher-1")
        self.assertEqual(events[1].data["output"], "Wiki 摘要")


if __name__ == "__main__":
    unittest.main()
