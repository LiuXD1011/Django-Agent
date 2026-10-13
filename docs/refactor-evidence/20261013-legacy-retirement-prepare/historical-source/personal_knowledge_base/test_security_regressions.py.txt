import json
from unittest.mock import patch

from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from personal_knowledge_base.agent_tools import GetDocumentInfoTool, WikiReadSourceDocTool
from personal_knowledge_base.authentication import issue_tokens
from personal_knowledge_base.mcp_client import load_mcp_services_from_db
from personal_knowledge_base.models import (
    AgentActor,
    Chunk,
    GenericResource,
    Knowledge,
    KnowledgeBase,
    Message,
    Session,
    Tenant,
    TenantMember,
    User,
)


class SecurityRegressionTests(TestCase):
    def setUp(self):
        self.tenant_a = Tenant.objects.create(name="tenant-a", api_key="security-a")
        self.tenant_b = Tenant.objects.create(name="tenant-b", api_key="security-b")
        self.user_a = User.objects.create(
            username="security-a-user",
            email="security-a@example.com",
            password_hash="unused",
            tenant=self.tenant_a,
        )
        self.user_b = User.objects.create(
            username="security-b-user",
            email="security-b@example.com",
            password_hash="unused",
            tenant=self.tenant_b,
        )
        token_a, _ = issue_tokens(self.user_a)
        token_b, _ = issue_tokens(self.user_b)
        self.headers_a = {"HTTP_AUTHORIZATION": f"Bearer {token_a}"}
        self.headers_b = {"HTTP_AUTHORIZATION": f"Bearer {token_b}"}
        self.session_b = Session.objects.create(tenant=self.tenant_b, title="private session")
        self.message_b = Message.objects.create(
            session=self.session_b,
            role="user",
            content="private message",
            is_completed=True,
        )
        self.kb_b = KnowledgeBase.objects.create(tenant=self.tenant_b, name="private kb")
        self.doc_b = Knowledge.objects.create(
            tenant=self.tenant_b,
            knowledge_base=self.kb_b,
            type="file",
            title="private document",
            source="private.txt",
        )
        self.chunk_b = Chunk.objects.create(
            tenant=self.tenant_b,
            knowledge_base=self.kb_b,
            knowledge=self.doc_b,
            content="private chunk",
            chunk_index=0,
        )

    def test_session_actions_and_messages_are_tenant_scoped(self):
        urls = [
            ("get", f"/api/v1/messages/{self.session_b.id}/load"),
            ("delete", f"/api/v1/messages/{self.session_b.id}/{self.message_b.id}"),
            ("delete", f"/api/v1/sessions/{self.session_b.id}/messages"),
            ("post", f"/api/v1/sessions/{self.session_b.id}/pin"),
            ("post", f"/api/v1/sessions/{self.session_b.id}/stop"),
        ]
        for method, url in urls:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, **self.headers_a)
                self.assertEqual(response.status_code, 404)
        self.message_b.refresh_from_db()
        self.assertTrue(Message.objects.filter(id=self.message_b.id).exists())

    def test_generic_resource_detail_is_tenant_scoped_and_credentials_are_masked(self):
        resource = GenericResource.objects.create(
            tenant=self.tenant_b,
            resource_type="mcp_services",
            name="private mcp",
            data={"url": "https://example.invalid", "api_key": "secret-value", "nested": {"token": "nested-secret"}},
        )
        response = self.client.get(f"/api/v1/mcp-services/{resource.id}", **self.headers_a)
        self.assertEqual(response.status_code, 404)

        own = GenericResource.objects.create(
            tenant=self.tenant_a,
            resource_type="mcp_services",
            name="own mcp",
            data={"api_key": "own-secret", "password": "own-password"},
        )
        response = self.client.get(f"/api/v1/mcp-services/{own.id}", **self.headers_a)
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertEqual(payload["api_key"], "******")
        self.assertEqual(payload["password"], "******")

    def test_tenant_management_requires_membership_and_admin_role(self):
        response = self.client.get(f"/api/v1/tenants/{self.tenant_b.id}", **self.headers_a)
        self.assertEqual(response.status_code, 404)
        response = self.client.post(
            "/api/v1/auth/switch-tenant",
            data=json.dumps({"tenant_id": self.tenant_b.id}),
            content_type="application/json",
            **self.headers_a,
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.get(f"/api/v1/tenants/{self.tenant_b.id}/members", **self.headers_a)
        self.assertEqual(response.status_code, 404)

    def test_embed_exchange_requires_enabled_channel_and_uses_channel_tenant(self):
        channel = GenericResource.objects.create(
            tenant=self.tenant_b,
            resource_type="embed_channels",
            data={"enabled": False, "token": "private-channel-token"},
        )
        response = self.client.post(f"/api/v1/embed/{channel.id}/exchange")
        self.assertEqual(response.status_code, 404)

        channel.data = {"enabled": True, "token": "private-channel-token", "api_key": "private-api-key"}
        channel.save(update_fields=["data", "updated_at"])
        response = self.client.post(f"/api/v1/embed/{channel.id}/exchange")
        self.assertEqual(response.status_code, 200)
        embed_token = response.json()["data"]["token"]
        response = self.client.get(
            f"/api/v1/embed/{channel.id}/config",
            HTTP_AUTHORIZATION=f"Bearer {embed_token}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("token", response.json()["data"])
        self.assertNotIn("api_key", response.json()["data"])

        response = self.client.post(
            f"/api/v1/embed/{channel.id}/sessions",
            HTTP_AUTHORIZATION=f"Bearer {embed_token}",
        )
        self.assertEqual(response.status_code, 201)
        session_id = response.json()["data"]["id"]
        session = Session.objects.get(id=session_id)
        self.assertEqual(session.tenant, self.tenant_b)
        self.assertEqual(session.agent_config["embed_channel_id"], channel.id)

        with patch("personal_knowledge_base.views.chat_endpoint", return_value=self.client.get("/health")) as chat:
            response = self.client.post(
                f"/api/v1/embed/{channel.id}/knowledge-chat/{session_id}",
                data=json.dumps({"query": "hello"}),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {embed_token}",
            )
            self.assertEqual(response.status_code, 200)
            chat.assert_called_once()

        response = self.client.get(
            f"/api/v1/embed/{channel.id}/messages/{session_id}/load",
            HTTP_AUTHORIZATION=f"Bearer {embed_token}",
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.post(
            f"/api/v1/embed/{channel.id}/sessions/{session_id}/stop",
            HTTP_AUTHORIZATION=f"Bearer {embed_token}",
        )
        self.assertEqual(response.status_code, 200)

    def test_agent_document_tools_reject_foreign_documents(self):
        context = {"tenant_id": self.tenant_a.id, "kb_ids": [], "session_id": "missing"}
        for tool in [GetDocumentInfoTool(), WikiReadSourceDocTool()]:
            with self.subTest(tool=tool.name()):
                result = tool.execute({"knowledge_id": self.doc_b.id}, context)
                self.assertEqual(result.output, "")
                self.assertIn("not found", result.error.lower())

    @patch("personal_knowledge_base.mcp_client.MCPManager.register_service_tools")
    def test_mcp_loading_requires_tenant_scope(self, register_tools):
        own = GenericResource.objects.create(
            tenant=self.tenant_a,
            resource_type="mcp_services",
            name="own service",
            data={"url": "https://own.invalid", "enabled": True},
        )
        GenericResource.objects.create(
            tenant=self.tenant_b,
            resource_type="mcp_services",
            name="foreign service",
            data={"url": "https://foreign.invalid", "enabled": True},
        )

        self.assertEqual(load_mcp_services_from_db(object(), tenant=self.tenant_a), 1)
        self.assertEqual(register_tools.call_args.args[0], str(own.id))
        self.assertEqual(load_mcp_services_from_db(object()), 0)

    @override_settings(MEDIA_ROOT="/tmp/django-agent-security-media")
    def test_generic_file_endpoint_requires_signed_access(self):
        path = default_storage.save("security/private.txt", ContentFile(b"private"))
        try:
            response = self.client.get(f"/files?file_path={path}")
            self.assertIn(response.status_code, {401, 403, 404})
        finally:
            default_storage.delete(path)
