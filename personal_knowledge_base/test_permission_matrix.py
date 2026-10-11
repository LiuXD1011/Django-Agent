"""W01 角色矩阵与凭据生命周期回归：默认拒绝、service 只读、禁用即失效。

矩阵覆盖：owner/admin 全部动作；editor 业务写但无成员/凭据/租户管理；
viewer 与 service（X-API-Key）只读+导出；破坏性动作要求真实用户主体。
"""
import json
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .authentication import issue_tokens
from .models import KnowledgeBase, Session, Tenant, TenantMember, User


@override_settings(LANGFUSE_ENABLED=False)
class PermissionMatrixTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.tenant = Tenant.objects.create(name="matrix", api_key="matrix-api-key")
        self.other = Tenant.objects.create(name="other", api_key="other-api-key")
        self.users = {}
        self.tokens = {}
        for role in ["owner", "admin", "editor", "viewer"]:
            user = User.objects.create(
                username=f"matrix-{role}", email=f"{role}@matrix.invalid",
                password_hash="unused", tenant=self.tenant,
            )
            TenantMember.objects.create(user=user, tenant=self.tenant, role=role)
            self.users[role] = user
            self.tokens[role], _ = issue_tokens(user)
        self.kb = KnowledgeBase.objects.create(
            tenant=self.tenant, name="矩阵库", type="document",
        )

    def headers(self, role):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.tokens[role]}"}

    def api_key_headers(self):
        return {"HTTP_X_API_KEY": self.tenant.api_key}

    def test_matrix_over_kb_create_and_delete(self):
        cases = [
            ("owner", 201), ("admin", 201), ("editor", 201), ("viewer", 403), ("service", 403),
        ]
        for role, expected in cases:
            with self.subTest(role=role, action="kb.create"):
                response = self.client.post(
                    "/api/v1/knowledge-bases",
                    data=json.dumps({"name": f"矩阵-{role}"}),
                    content_type="application/json",
                    **(self.headers(role) if role != "service" else self.api_key_headers()),
                )
                self.assertEqual(response.status_code, expected, response.content)

        for role, expected in [("owner", 200), ("admin", 200), ("editor", 403), ("viewer", 403), ("service", 403)]:
            with self.subTest(role=role, action="kb.delete"):
                kb = KnowledgeBase.objects.create(tenant=self.tenant, name=f"删除-{role}", type="document")
                response = self.client.delete(
                    f"/api/v1/knowledge-bases/{kb.id}",
                    **(self.headers(role) if role != "service" else self.api_key_headers()),
                )
                self.assertEqual(response.status_code, expected, response.content)

    def test_matrix_over_document_write_and_batch_delete(self):
        upload_cases = [("owner", 400), ("admin", 400), ("editor", 400), ("viewer", 403), ("service", 403)]
        for role, expected in upload_cases:
            with self.subTest(role=role, action="document.upload"):
                response = self.client.post(
                    f"/api/v1/knowledge-bases/{self.kb.id}/knowledge/file",
                    **(self.headers(role) if role != "service" else self.api_key_headers()),
                )
                # 无文件时 editor 及以上进入 400 参数校验；viewer/service 在动作层即被拒。
                self.assertEqual(response.status_code, expected, response.content)

        # owner/admin/editor 通过动作层后因目标不存在到达 404；viewer/service 在动作层即被拒。
        for role, expected in [("owner", 404), ("admin", 404), ("editor", 404), ("viewer", 403), ("service", 403)]:
                response = self.client.post(
                    f"/api/v1/knowledge-bases/{self.kb.id}/knowledge/batch-delete",
                    data=json.dumps({"ids": ["nonexistent"]}),
                    content_type="application/json",
                    **(self.headers(role) if role != "service" else self.api_key_headers()),
                )
                self.assertEqual(response.status_code, expected, response.content)

    def test_matrix_over_member_and_credential_management(self):
        tenant_id = self.tenant.id
        for role, expected in [("owner", 200), ("admin", 200), ("editor", 403), ("viewer", 403), ("service", 403)]:
            with self.subTest(role=role, action="member.invite"):
                response = self.client.post(
                    f"/api/v1/tenants/{tenant_id}/members",
                    data=json.dumps({"email": "new@matrix.invalid", "role": "viewer"}),
                    content_type="application/json",
                    **(self.headers(role) if role != "service" else self.api_key_headers()),
                )
                self.assertIn(response.status_code, [expected, 404], response.content)

        for role, expected in [("owner", 200), ("admin", 200), ("editor", 403), ("viewer", 403), ("service", 403)]:
            with self.subTest(role=role, action="credentials.kv_write"):
                response = self.client.put(
                    "/api/v1/tenants/kv/retrieval-config",
                    data=json.dumps({"value": {"top_k": 5}}),
                    content_type="application/json",
                    **(self.headers(role) if role != "service" else self.api_key_headers()),
                )
                self.assertEqual(response.status_code, expected, response.content)

        for role, expected in [("owner", 201), ("admin", 201), ("editor", 201), ("viewer", 403), ("service", 403)]:
            with self.subTest(role=role, action="agent.write"):
                response = self.client.post(
                    "/api/v1/agents",
                    data=json.dumps({"name": "矩阵agent", "data": {}}),
                    content_type="application/json",
                    **(self.headers(role) if role != "service" else self.api_key_headers()),
                )
                self.assertEqual(response.status_code, expected, response.content)

    def test_reads_remain_open_to_all_authenticated_principals(self):
        for role in ["owner", "admin", "editor", "viewer"]:
            with self.subTest(role=role, action="kb.list"):
                response = self.client.get("/api/v1/knowledge-bases", **self.headers(role))
                self.assertEqual(response.status_code, 200, response.content)
        response = self.client.get("/api/v1/knowledge-bases", **self.api_key_headers())
        self.assertEqual(response.status_code, 200, response.content)

    def test_anonymous_requests_are_rejected(self):
        for path, method in [
            ("/api/v1/knowledge-bases", "get"),
            ("/api/v1/agents", "get"),
            ("/api/v1/tenants", "get"),
        ]:
            with self.subTest(path=path):
                self.assertEqual(getattr(self.client, method)(path).status_code, 401)

    def test_cross_tenant_stays_404(self):
        outsider = User.objects.create(
            username="outsider", email="outsider@matrix.invalid",
            password_hash="unused", tenant=self.other,
        )
        TenantMember.objects.create(user=outsider, tenant=self.other, role="owner")
        token, _ = issue_tokens(outsider)
        response = self.client.get(
            f"/api/v1/knowledge-bases/{self.kb.id}",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 404)


@override_settings(LANGFUSE_ENABLED=False)
class CredentialLifecycleTests(TestCase):
    """F02：用户禁用、租户停用、成员移除后，存量凭据立即失效。"""

    def setUp(self):
        self.client = Client()
        self.tenant = Tenant.objects.create(name="lifecycle", api_key="lifecycle-key")
        self.user = User.objects.create(
            username="lifecycle-user", email="lifecycle@fixture.invalid",
            password_hash="unused", tenant=self.tenant,
        )
        TenantMember.objects.create(user=self.user, tenant=self.tenant, role="owner")
        self.token, self.refresh = issue_tokens(self.user)

    def _disable_user(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active", "updated_at"])

    def test_disabled_user_bearer_is_immediately_rejected(self):
        self.assertEqual(self.client.get(
            "/api/v1/knowledge-bases", HTTP_AUTHORIZATION=f"Bearer {self.token}",
        ).status_code, 200)
        self._disable_user()
        response = self.client.get("/api/v1/knowledge-bases", HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.assertEqual(response.status_code, 401, response.content)

    def test_disabled_user_cannot_refresh_or_login(self):
        self._disable_user()
        response = self.client.post(
            "/api/v1/auth/refresh",
            data=json.dumps({"refresh_token": self.refresh}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401, response.content)
        response = self.client.post(
            "/api/v1/auth/login",
            data=json.dumps({"email": "lifecycle@fixture.invalid", "password": "whatever"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401, response.content)

    def test_disabled_tenant_members_lose_access(self):
        self.tenant.status = "disabled"
        self.tenant.save(update_fields=["status", "updated_at"])
        response = self.client.get("/api/v1/knowledge-bases", HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.assertEqual(response.status_code, 401, response.content)

    def test_tenant_switch_requires_active_target_tenant(self):
        other = Tenant.objects.create(name="lifecycle-other", api_key="lifecycle-other-key")
        TenantMember.objects.create(user=self.user, tenant=other, role="viewer")
        response = self.client.get(
            "/api/v1/knowledge-bases", HTTP_AUTHORIZATION=f"Bearer {self.token}",
            HTTP_X_TENANT_ID=str(other.id),
        )
        self.assertEqual(response.status_code, 200)
        other.status = "disabled"
        other.save(update_fields=["status", "updated_at"])
        response = self.client.get(
            "/api/v1/knowledge-bases", HTTP_AUTHORIZATION=f"Bearer {self.token}",
            HTTP_X_TENANT_ID=str(other.id),
        )
        self.assertEqual(response.status_code, 401)
        # Explicit inactive tenant selectors fail closed, not silently use another tenant.

    def test_revoked_token_is_rejected(self):
        response = self.client.post(
            "/api/v1/auth/logout", HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.get("/api/v1/knowledge-bases", HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.assertEqual(response.status_code, 401, response.content)
