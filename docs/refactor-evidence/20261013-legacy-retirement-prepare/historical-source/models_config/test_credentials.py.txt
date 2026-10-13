"""Offline credential lifecycle, tenant boundary and encryption regression tests."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.test import TestCase, override_settings

from personal_knowledge_base.authentication import issue_tokens
from personal_knowledge_base.credential_fields import master_key, transform_credentials
from personal_knowledge_base.models import ModelConfig, Tenant, TenantMember, User, GenericResource, IntegrationConfig
from personal_knowledge_base.model_providers import env_models, role_completion, active_embedding_config


class CredentialTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(APP_DATA_DIR=Path(self.directory.name))
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.tenant = Tenant.objects.create(name="fixture", api_key="fixture-tenant-key")
        self.user = User.objects.create(username="owner", email="owner@example.test", tenant=self.tenant)
        TenantMember.objects.create(user=self.user, tenant=self.tenant, role="owner")
        token, _ = issue_tokens(self.user)
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        self.model = ModelConfig.objects.create(id="fixture-model", tenant=self.tenant, name="fixture",
            type="KnowledgeQA", source="openai", parameters={"base_url": "https://fixture.invalid/v1", "api_key": "fixture-secret"})
        self.url = f"/api/v1/models/{self.model.id}/credentials"

    def raw(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT parameters FROM models WHERE id = %s", [self.model.id])
            return cursor.fetchone()[0]

    def test_encrypted_storage_and_roundtrip(self):
        raw = self.raw()
        self.assertNotIn("fixture-secret", raw)
        self.assertIn("enc:v1:", raw)
        self.model.refresh_from_db()
        self.assertEqual(self.model.parameters["api_key"], "fixture-secret")
        self.assertEqual(self.model.parameters["base_url"], "https://fixture.invalid/v1")
        key = Path(self.directory.name) / ".secrets/credentials.key"
        self.assertEqual(len(key.read_bytes()), 32)
        if os.name != "nt":
            self.assertEqual(key.stat().st_mode & 0o777, 0o600)

    def test_list_has_no_secret_or_ciphertext(self):
        response = self.client.get("/api/v1/models", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("fixture-secret", response.content.decode())
        self.assertNotIn("enc:v1:", response.content.decode())
        model = response.json()["data"]["items"][0]
        self.assertNotIn("api_key", model["parameters"])
        self.assertTrue(model["credential_fields"]["api_key"]["configured"])
        self.assertTrue(all(not m["id"].startswith("env-") for m in response.json()["data"]["items"]))

    def test_save_blank_and_mask_keep_key(self):
        for value in ("", "******", None):
            response = self.client.put(self.url, json.dumps({"api_key": value}), content_type="application/json", **self.headers)
            self.assertEqual(response.status_code, 200)
            self.model.refresh_from_db()
            self.assertEqual(self.model.parameters["api_key"], "fixture-secret")

    def test_replace_and_clear(self):
        response = self.client.put(self.url, json.dumps({"api_key": "replacement-fixture"}), content_type="application/json", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("replacement-fixture", response.content.decode())
        self.assertNotIn("replacement-fixture", self.raw())
        self.model.refresh_from_db()
        self.assertEqual(self.model.parameters["api_key"], "replacement-fixture")
        self.assertEqual(self.client.delete(self.url + "/api_key", **self.headers).status_code, 200)
        self.model.refresh_from_db()
        self.assertNotIn("api_key", self.model.parameters)
        self.assertIn("base_url", self.model.parameters)

    def test_read_is_metadata_only_and_no_store(self):
        before = self.raw()
        response = self.client.get(self.url, **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertNotIn("fixture-secret", response.content.decode())
        self.assertEqual(self.raw(), before)

    def test_reject_unknown_fields_and_ciphertext(self):
        for data in ({"base_url": "https://bad.invalid"}, {"thinking": {}}, {"api_key": 12}, {"api_key": "enc:v1:fake"}):
            response = self.client.put(self.url, json.dumps(data), content_type="application/json", **self.headers)
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.delete(self.url + "/base_url", **self.headers).status_code, 400)
        self.assertEqual(self.client.post(self.url, "{}", content_type="application/json", **self.headers).status_code, 405)

    def test_unauthenticated_and_other_tenant(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)
        other = Tenant.objects.create(name="other", api_key="fixture-other")
        foreign = ModelConfig.objects.create(id="foreign", tenant=other, name="foreign")
        response = self.client.put(f"/api/v1/models/{foreign.id}/credentials", '{"api_key":"x"}', content_type="application/json", **self.headers)
        self.assertEqual(response.status_code, 404)

    def test_viewer_cannot_mutate(self):
        TenantMember.objects.filter(user=self.user).update(role="viewer")
        self.assertEqual(self.client.put(self.url, '{"api_key":"x"}', content_type="application/json", **self.headers).status_code, 403)

    def test_missing_master_key_is_not_regenerated_on_read(self):
        key = Path(self.directory.name) / ".secrets/credentials.key"
        key.unlink()
        with self.assertRaises(ImproperlyConfigured):
            self.model.refresh_from_db()
        self.assertFalse(key.exists())

    def test_tampered_ciphertext_fails_closed(self):
        sealed = transform_credentials({"api_key": "fixture"}, encrypt=True)
        sealed["api_key"] = sealed["api_key"][:-5] + "AAAAA"
        with self.assertRaises(ImproperlyConfigured):
            transform_credentials(sealed, encrypt=False)

    def test_general_edit_keeps_secret_and_sets_single_default(self):
        other = ModelConfig.objects.create(id="old-default", tenant=self.tenant, name="other", type="chat", is_default=True)
        response = self.client.put(f"/api/v1/models/{self.model.id}", json.dumps({"is_default": True, "parameters": {"api_key": ""}}),
                                   content_type="application/json", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.model.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.model.parameters["api_key"], "fixture-secret")
        self.assertFalse(other.is_default)

    def test_create_cannot_overwrite_other_tenant_id(self):
        response = self.client.post("/api/v1/models", json.dumps({"id": self.model.id, "name": "new", "parameters": {"api_key": "new-fixture"}}),
                                    content_type="application/json", **self.headers)
        self.assertEqual(response.status_code, 201)
        self.assertNotEqual(response.json()["data"]["id"], self.model.id)

    def test_test_failure_does_not_echo_provider_secret(self):
        with patch("models_config.views.testable_model_config", return_value=("Embedding", {})), patch(
            "models_config.views.test_embedding_config", side_effect=RuntimeError("fixture-secret")):
            response = self.client.post(f"/api/v1/models/{self.model.id}/test", **self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("fixture-secret", response.content.decode())

    def test_nested_resource_credentials_are_encrypted(self):
        resource = GenericResource.objects.create(tenant=self.tenant, resource_type="mcp",
            data={"auth": {"apiKey": "nested-fixture"}})
        with connection.cursor() as cursor:
            cursor.execute("SELECT data FROM generic_resources WHERE id = %s", [resource.id])
            self.assertNotIn("nested-fixture", cursor.fetchone()[0])
        resource.refresh_from_db()
        self.assertEqual(resource.data["auth"]["apiKey"], "nested-fixture")

    def test_auxiliary_tasks_use_workspace_default(self):
        with patch("personal_knowledge_base.model_providers._chat_completion_with_fallback",
                   return_value=({"choices": [{"message": {"content": "title"}}]}, self.model, None)) as call:
            self.assertEqual(role_completion("title", "fixture", tenant=self.tenant), "title")
            self.assertEqual(call.call_args.args[1].pk, self.model.pk)

    def test_embedding_resolves_ui_configuration(self):
        model = ModelConfig.objects.create(id="embedding", tenant=self.tenant, name="embedding", type="Embedding",
            parameters={"base_url": "https://fixture.invalid", "api_key": "embed-fixture", "dimension": 8})
        config = active_embedding_config(self.tenant)
        self.assertEqual(config["model_id"], model.id)
        self.assertEqual(config["api_key"], "embed-fixture")

    def test_langfuse_admin_and_no_echo(self):
        url = "/api/v1/integrations/langfuse/credentials"
        self.assertEqual(self.client.get(url, **self.headers).status_code, 403)
        self.user.is_system_admin = True
        self.user.save()
        response = self.client.put(url, json.dumps({"public_key": "public-fixture", "secret_key": "secret-fixture",
            "base_url": "http://localhost:3000", "enabled": True}), content_type="application/json", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("secret-fixture", response.content.decode())
        with connection.cursor() as cursor:
            cursor.execute("SELECT parameters FROM integration_configs WHERE name = %s", ["langfuse"])
            self.assertNotIn("secret-fixture", cursor.fetchone()[0])
        self.assertEqual(self.client.delete(url, **self.headers).status_code, 200)
        self.assertFalse(IntegrationConfig.objects.get(name="langfuse").parameters["enabled"])

    def test_no_env_models(self):
        self.assertEqual(env_models(self.tenant), [])

    def test_langfuse_runtime_uses_ui_keys_and_refreshes(self):
        from personal_knowledge_base import observability as obs
        config = {"enabled": True, "public_key": "public-fixture", "secret_key": "secret-fixture", "base_url": "http://fixture.invalid"}
        row = IntegrationConfig.objects.create(name="langfuse", parameters=config)
        with patch.object(obs, "LANGFUSE_AVAILABLE", True), patch.object(obs, "Langfuse") as sdk, patch.object(obs, "_client_ready", False), patch.object(obs, "_client_signature", None), patch.object(obs, "_client", None):
            obs.get_langfuse()
            self.assertEqual(sdk.call_args.kwargs["base_url"], config["base_url"])
            self.assertEqual(sdk.call_args.kwargs["secret_key"], "secret-fixture")
            obs.get_langfuse()
            self.assertEqual(sdk.call_count, 1)
            row.parameters["secret_key"] = "rotated-fixture"
            row.save()
            obs.get_langfuse()
            self.assertEqual(sdk.call_count, 2)
            row.parameters["enabled"] = False
            row.save()
            self.assertIsNone(obs.get_langfuse())
            self.assertEqual(sdk.call_count, 2)

    def test_langfuse_diagnostics_use_ui_configuration(self):
        from io import StringIO
        from personal_knowledge_base.management.commands.langfuse_check import Command
        IntegrationConfig.objects.create(name="langfuse", parameters={"enabled": True, "public_key": "public-fixture", "secret_key": "secret-fixture", "base_url": "http://fixture.invalid"})
        output = StringIO()
        command = Command(stdout=output)
        self.assertEqual(command._check_config(), "initialized")
        self.assertNotIn("public-fixture", output.getvalue())
        self.assertNotIn("secret-fixture", output.getvalue())
