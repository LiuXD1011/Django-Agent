import json
from unittest.mock import patch

from django.test import TestCase

from personal_knowledge_base.authentication import issue_tokens
from personal_knowledge_base.models import KnowledgeBase, Message, Session, Tenant, User


class SessionClearMethodTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Clear tenant", api_key="clear-test-key")
        self.user = User.objects.create(
            username="clear-user", password_hash="unused", tenant=self.tenant,
        )
        token, _ = issue_tokens(self.user)
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        self.session = Session.objects.create(tenant=self.tenant, title="Clear test")
        self.message = Message.objects.create(
            session=self.session, role="user", content="必须保留的消息",
        )
        self.url = f"/api/v1/sessions/{self.session.id}/messages"

    def test_non_delete_requests_preserve_messages_and_memory(self):
        with patch("chat.views.delete_session_memory") as delete_memory:
            for method in ("GET", "HEAD", "POST", "PUT", "PATCH", "OPTIONS"):
                with self.subTest(method=method):
                    response = self.client.generic(method, self.url, **self.headers)
                    self.assertEqual(response.status_code, 405)
                    self.assertEqual(response.headers["Allow"], "DELETE")
                    self.assertTrue(Message.objects.filter(pk=self.message.pk).exists())
            delete_memory.assert_not_called()

    def test_delete_still_clears_messages_and_memory(self):
        with patch("chat.views.delete_session_memory") as delete_memory:
            response = self.client.delete(self.url, **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Message.objects.filter(session=self.session).exists())
        delete_memory.assert_called_once_with(self.session.id)


class SessionKnowledgeScopeTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Scope tenant", api_key="scope-test-key")
        self.user = User.objects.create(
            username="scope-user", password_hash="unused", tenant=self.tenant,
        )
        token, _ = issue_tokens(self.user)
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        self.kb = KnowledgeBase.objects.create(tenant=self.tenant, name="当前知识库")

    def create_session(self, **extra):
        response = self.client.post(
            "/api/v1/sessions",
            data=json.dumps({"knowledge_base_id": self.kb.id, **extra}),
            content_type="application/json", **self.headers,
        )
        self.assertEqual(response.status_code, 201)
        return response.json()["data"]["last_request_state"]["knowledge_base_ids"]

    def test_starting_chat_from_knowledge_base_restores_its_scope(self):
        self.assertEqual(self.create_session(), [self.kb.id])

    def test_explicit_empty_selection_is_preserved(self):
        self.assertEqual(self.create_session(knowledge_base_ids=[]), [])

    def test_explicit_multi_selection_is_preserved(self):
        other = KnowledgeBase.objects.create(tenant=self.tenant, name="第二个知识库")
        selected = [self.kb.id, other.id]
        self.assertEqual(self.create_session(agent_config={"knowledge_base_ids": selected}), selected)
