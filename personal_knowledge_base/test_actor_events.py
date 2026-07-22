from unittest.mock import patch

from django.test import TestCase

from .agent_actor import actor_to_trace, emit_actor_event
from .models import AgentActor, Session, Tenant


class ActorEventPayloadTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Actor event tenant", api_key="actor-event-key")
        self.session = Session.objects.create(tenant=self.tenant, title="Actor event session")

    def test_terminal_actor_event_includes_persisted_metadata(self):
        actor = AgentActor.objects.create(
            session=self.session,
            actor_id="wiki_researcher-1",
            agent_type="wiki_researcher",
            status="idle",
            last_outcome="success",
            parent_message_id="assistant-message-1",
            metadata={"duration_ms": 321},
        )

        with patch("personal_knowledge_base.agent_actor.stream_manager.append_event") as append_event:
            emit_actor_event(actor.parent_message_id, "actor_completed", actor, {"output": "done"})

        payload = append_event.call_args.args[2]
        self.assertEqual(payload["status"], "idle")
        self.assertEqual(payload["last_outcome"], "success")
        self.assertEqual(payload["metadata"], {"duration_ms": 321})

    def test_persisted_actor_trace_starts_with_an_empty_event_history(self):
        actor = AgentActor.objects.create(
            session=self.session,
            actor_id="wiki_researcher-1",
            agent_type="wiki_researcher",
            parent_message_id="assistant-message-1",
        )

        trace = actor_to_trace(actor)

        self.assertEqual(trace["events"], [])

    def test_tool_payload_cannot_overwrite_actor_identity(self):
        actor = AgentActor.objects.create(
            session=self.session,
            actor_id="wiki_researcher-1",
            agent_type="wiki_researcher",
            status="running",
            last_outcome="",
            parent_message_id="assistant-message-1",
        )
        tool_payload = {
            "name": "wiki_search",
            "agent_type": "tool",
            "status": "failed",
            "output": "tool output",
            "error": "tool error",
            "tool_call_id": "call-1",
        }

        with patch("personal_knowledge_base.agent_actor.stream_manager.append_event") as append_event:
            emit_actor_event(actor.parent_message_id, "actor_tool_result", actor, tool_payload)

        payload = append_event.call_args.args[2]
        self.assertEqual(payload["actor_id"], actor.actor_id)
        self.assertEqual(payload["agent_type"], actor.agent_type)
        self.assertEqual(payload["name"], "Wiki 研究子 Agent")
        self.assertEqual(payload["status"], actor.status)
        self.assertEqual(payload["response_type"], "actor_tool_result")
        self.assertEqual(payload["output"], "tool output")
        self.assertEqual(payload["error"], "tool error")
        self.assertEqual(payload["tool_call_id"], "call-1")
