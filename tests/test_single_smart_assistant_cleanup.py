import os
import sys
import unittest
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


class SingleSmartAssistantCleanupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import django

        django.setup()
        from django.test import RequestFactory

        cls.request_factory = RequestFactory()

    def setUp(self):
        from personal_knowledge_base.models import GenericResource, Session, Tenant

        self.tenant = Tenant.objects.create(name="single-assistant-tenant", api_key=f"single-assistant-{uuid4()}")
        GenericResource.objects.filter(tenant=self.tenant, resource_type="agents").delete()
        self.session = Session.objects.create(
            tenant=self.tenant,
            title="legacy agent session",
            agent_id=f"builtin-quick-answer-{self.tenant.id}",
        )

    def tearDown(self):
        from personal_knowledge_base.models import GenericResource, Session, Tenant

        GenericResource.objects.filter(tenant=self.tenant).delete()
        Session.objects.filter(id=self.session.id).delete()
        Tenant.objects.filter(id=self.tenant.id).delete()

    def _request(self):
        return self.request_factory.get(
            "/api/v1/agents",
            HTTP_X_API_KEY=self.tenant.api_key,
        )

    def test_agent_collection_only_exposes_smart_assistant(self):
        from agent.views import generic_collection

        response = generic_collection(self._request(), "agents")
        payload = response.content.decode("utf-8")

        self.assertIn("智能助手", payload)
        self.assertIn("multi-agent", payload)
        self.assertNotIn("快速问答", payload)
        self.assertNotIn("智能推理", payload)
        self.assertNotIn("Wiki 问答", payload)

    def test_type_presets_do_not_expose_legacy_modes(self):
        from agent.views import static_types
        from personal_knowledge_base.views import static_types as pkb_static_types

        for items in (static_types("agents", "type-presets"), pkb_static_types("agents", "type-presets")):
            serialized = str(items)
            self.assertNotIn("quick-answer", serialized)
            self.assertNotIn("smart-reasoning", serialized)
            self.assertNotIn("wiki-researcher", serialized)
            self.assertTrue(not items or items[0]["agent_mode"] == "multi-agent")

    def test_legacy_session_agent_id_is_ignored_by_multi_agent_defaults(self):
        from chat.views import apply_multi_agent_defaults

        config = apply_multi_agent_defaults(
            {
                "agent_mode": "quick-answer",
                "system_prompt": "legacy prompt",
                "allowed_tools": [],
                "actor_id": "legacy",
                "allow_actor_tool": False,
            },
            {"model_id": "chat-model"},
            ["kb-1"],
            parent_message_id="assistant-1",
        )

        self.assertEqual(config["agent_mode"], "multi-agent")
        self.assertEqual(config["allowed_tools"], ["actor", "thinking"])
        self.assertEqual(config["actor_id"], "main")
        self.assertTrue(config["allow_actor_tool"])
        self.assertIn("多 Agent", config["system_prompt"])
        self.assertEqual(config["parent_message_id"], "assistant-1")


if __name__ == "__main__":
    unittest.main()
