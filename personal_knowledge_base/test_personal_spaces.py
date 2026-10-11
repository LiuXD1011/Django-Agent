import json
import secrets
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import Client, TestCase, SimpleTestCase, override_settings

from .authentication import has_tenant_access, hash_password, issue_tokens
from .capabilities import service_id
from .models import Tenant, TenantMember, User
from .personal_spaces import create_personal_user
from .permissions import principal_role
from .serializers import tenant_dict


class PersonalSpaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password_hash = hash_password("test-password")
        cls.owner = create_personal_user(username="owner", email="owner@example.test", password_hash=cls.password_hash)
        cls.other = create_personal_user(username="other", email="other@example.test", password_hash=cls.password_hash)

    def test_new_account_has_explicit_private_space(self):
        self.assertEqual(self.owner.tenant.space_type, "personal")
        self.assertEqual(self.owner.tenant.personal_owner_id, self.owner.id)
        self.assertEqual(TenantMember.objects.get(user=self.owner, tenant=self.owner.tenant).role, "owner")
        self.assertTrue(has_tenant_access(self.owner, self.owner.tenant))

    def test_creation_rolls_back_all_rows_on_membership_failure(self):
        counts = User.objects.count(), Tenant.objects.count()
        with patch("personal_knowledge_base.personal_spaces.TenantMember.objects.create", side_effect=RuntimeError("fixture failure")):
            with self.assertRaises(RuntimeError):
                create_personal_user(username="failed", email="failed@example.test", password_hash=self.password_hash)
        self.assertEqual((User.objects.count(), Tenant.objects.count()), counts)

    def test_one_active_personal_space_per_owner(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Tenant.objects.create(name="duplicate", api_key=secrets.token_hex(16), space_type="personal", personal_owner=self.owner)

    def test_personal_space_requires_owner(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Tenant.objects.create(name="orphan", api_key=secrets.token_hex(16), space_type="personal")

    def test_legacy_space_is_not_automatically_claimed(self):
        space = Tenant.objects.create(name="existing team", api_key=secrets.token_hex(16))
        TenantMember.objects.create(tenant=space, user=self.owner, role="owner")
        TenantMember.objects.create(tenant=space, user=self.other, role="editor")
        space.refresh_from_db()
        self.assertEqual(space.space_type, "legacy")
        self.assertIsNone(space.personal_owner_id)
        self.assertTrue(has_tenant_access(self.other, space))

    def test_membership_cannot_grant_another_persons_private_space(self):
        TenantMember.objects.create(tenant=self.owner.tenant, user=self.other, role="owner")
        self.assertFalse(has_tenant_access(self.other, self.owner.tenant))
        self.other.is_system_admin = True
        self.other.can_access_all_tenants = True
        self.assertFalse(has_tenant_access(self.other, self.owner.tenant))

    def test_owner_membership_revocation_still_denies(self):
        TenantMember.objects.filter(user=self.owner, tenant=self.owner.tenant).update(status="revoked")
        self.assertFalse(has_tenant_access(self.owner, self.owner.tenant))

    def test_personal_owner_role_comes_from_explicit_ownership(self):
        TenantMember.objects.filter(user=self.owner, tenant=self.owner.tenant).update(role="viewer")
        self.assertEqual(principal_role(self.owner, self.owner.tenant), "owner")

    def test_public_private_space_payload_has_no_api_key(self):
        data = tenant_dict(self.owner.tenant)
        self.assertNotIn("api_key", data)
        self.assertTrue(data["api_key_configured"])
        self.assertEqual(tenant_dict(self.owner.tenant, include_api_key=True)["api_key"], self.owner.tenant.api_key)

    def test_two_devices_read_same_private_resources(self):
        first, _ = issue_tokens(self.owner)
        second, _ = issue_tokens(self.owner)
        a = Client(HTTP_AUTHORIZATION=f"Bearer {first}")
        b = Client(HTTP_AUTHORIZATION=f"Bearer {second}")
        created = a.post("/api/v1/knowledge-bases", json.dumps({"name": "cross-device"}), content_type="application/json")
        self.assertEqual(created.status_code, 201)
        resource = created.json()["data"]["id"]
        self.assertEqual(b.get(f"/api/v1/knowledge-bases/{resource}").status_code, 200)
        outsider_token, _ = issue_tokens(self.other)
        outsider = Client(HTTP_AUTHORIZATION=f"Bearer {outsider_token}")
        self.assertEqual(outsider.get(f"/api/v1/knowledge-bases/{resource}").status_code, 404)


class CapabilitiesTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(APP_DATA_DIR=Path(self.directory.name))
        self.override.enable()
        self.addCleanup(self.override.disable)

    def test_identity_persists_across_requests_and_host_changes(self):
        first = Client().get("/api/v1/capabilities")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["data"]["service_id"], service_id())
        second = Client().get("/api/v1/capabilities")
        self.assertEqual(first.json()["data"], second.json()["data"])
        self.assertEqual(first["Cache-Control"], "no-store")

    def test_public_contract_does_not_claim_unimplemented_features(self):
        data = Client().get("/api/v1/capabilities").json()["data"]
        self.assertEqual(data["auth_modes"], ["cookie", "legacy_bearer"])
        self.assertFalse(data["features"]["incremental_sync"])
        self.assertFalse(data["features"]["native_clients"])
        self.assertFalse(data["features"]["durable_generations"])
        self.assertIsNone(data["limits"]["max_upload_bytes"])
        self.assertNotIn("api_key", json.dumps(data))

    def test_corrupt_identity_fails_without_regeneration(self):
        original = service_id()
        file = Path(self.directory.name) / ".settings" / "service-id"
        file.write_text("corrupt", encoding="utf8")
        response = Client().get("/api/v1/capabilities")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(file.read_text(), "corrupt")
        self.assertNotIn(original, response.content.decode())

    def test_write_methods_are_rejected(self):
        self.assertEqual(Client().post("/api/v1/capabilities").status_code, 405)
