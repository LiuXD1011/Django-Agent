import json

from django.test import TestCase

from personal_knowledge_base.authentication import issue_tokens
from personal_knowledge_base.models import GenericResource, Tenant, TenantMember, User


class McpResourceIdentityTests(TestCase):
    def test_form_metadata_cannot_override_the_resource_identity(self):
        tenant = Tenant.objects.create(name="MCP fixture", api_key="mcp-fixture")
        user = User.objects.create(username="owner", email="mcp@fixture.invalid", tenant=tenant)
        TenantMember.objects.create(tenant=tenant, user=user, role="owner")
        token, _ = issue_tokens(user)
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        response = self.client.post("/api/v1/mcp-services", json.dumps({
            "id": "", "tenant_id": 999, "name": "fixture", "url": "http://localhost:9999", "enabled": False,
        }), content_type="application/json", **headers)
        self.assertEqual(response.status_code, 201)
        item = GenericResource.objects.get(tenant=tenant, resource_type="mcp_services")
        data = response.json()["data"]
        self.assertEqual(data["id"], item.id)
        self.assertEqual(data["tenant_id"], tenant.id)
        listed = self.client.get("/api/v1/mcp-services", **headers).json()["data"]["items"]
        self.assertEqual(listed[0]["id"], item.id)
        response = self.client.put(f"/api/v1/mcp-services/{item.id}", json.dumps({"description": "edited"}), content_type="application/json", **headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(GenericResource.objects.filter(tenant=tenant).count(), 1)
        self.assertEqual(response.json()["data"]["description"], "edited")
        self.assertEqual(self.client.delete(f"/api/v1/mcp-services/{item.id}", **headers).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/mcp-services", **headers).json()["data"]["items"], [])
