"""Offline tests for UI configuration, bootstrapping and one-time import."""
import json
import os
import subprocess
import sys
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings

from config.bootstrap import DEFAULTS, effective_startup, persistent_secret, read_startup, update_startup
from personal_knowledge_base.authentication import issue_tokens
from personal_knowledge_base.integration_config import langfuse_configuration, neo4j_configuration
from personal_knowledge_base.models import IntegrationConfig, Tenant, User


class BootstrapTests(SimpleTestCase):
    def test_defaults_are_offline_and_production_oriented(self):
        with TemporaryDirectory() as directory:
            self.assertFalse(read_startup(directory)["debug"])
            self.assertEqual(read_startup(directory)["task_workers"], 4)
            self.assertFalse((Path(directory) / ".settings/startup.json").exists())

    def test_persistent_secret_is_stable_private_and_separate(self):
        with TemporaryDirectory() as directory:
            first = persistent_secret(directory)
            self.assertEqual(persistent_secret(directory), first)
            path = Path(directory) / ".secrets/django.key"
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse((path.parent / "credentials.key").exists())
            self.assertEqual(persistent_secret(directory, "external-secret"), "external-secret")
            self.assertEqual(path.read_text(), first)

    def test_corrupt_secret_is_not_silently_replaced(self):
        with TemporaryDirectory() as directory:
            persistent_secret(directory)
            path = Path(directory) / ".secrets/django.key"
            path.write_text("")
            with self.assertRaises(ValueError):
                persistent_secret(directory)
            self.assertEqual(path.read_text(), "")

    def test_startup_write_roundtrip_and_process_override(self):
        with TemporaryDirectory() as directory:
            update_startup(directory, {"task_workers": 6, "debug": True, "sqlite_timeout": 11})
            update_startup(directory, {"log_level": "WARNING"})
            self.assertEqual(read_startup(directory)["task_workers"], 6)
            effective = effective_startup(directory, {"DJANGO_DEBUG": "false", "APP_TASK_WORKERS": "8"})
            self.assertFalse(effective["debug"])
            self.assertEqual(effective["task_workers"], 8)
            self.assertEqual(effective["sqlite_timeout"], 11)
            self.assertEqual(read_startup(directory)["task_workers"], 6)

    def test_invalid_startup_never_replaces_saved_file(self):
        with TemporaryDirectory() as directory:
            update_startup(directory, {"task_workers": 6})
            before = (Path(directory) / ".settings/startup.json").read_bytes()
            for value in ({"task_workers": True}, {"task_workers": 1}, {"allowed_hosts": ["*"]},
                          {"proxy_url": "http://user:password@host"}, {"unknown": 1}):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    update_startup(directory, value)
            self.assertEqual((Path(directory) / ".settings/startup.json").read_bytes(), before)

    def test_no_app_environment_file_is_read_and_secret_survives_restart(self):
        with TemporaryDirectory() as directory:
            Path(directory, ".env").write_text("APP_NAME=ignored-fixture\nDJANGO_DEBUG=true\n")
            env = {k: v for k, v in os.environ.items()
                   if k not in {"DJANGO_SECRET_KEY", "DJANGO_DEBUG", "APP_NAME", "APP_TASK_WORKERS", "APP_DATA_DIR"}}
            env["APP_DATA_DIR"] = directory
            code = ("import json,runpy; s=runpy.run_path('config/settings.py'); "
                    "print(json.dumps({'debug':s['DEBUG'],'ignored':s['APP_NAME']=='ignored-fixture'}))")
            first = subprocess.run([sys.executable, "-c", code], env=env, cwd=settings.BASE_DIR,
                                   capture_output=True, text=True, timeout=10)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(json.loads(first.stdout), {"debug": False, "ignored": False})
            key = Path(directory, ".secrets/django.key").read_bytes()
            second = subprocess.run([sys.executable, "-c", code], env=env, cwd=settings.BASE_DIR,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(Path(directory, ".secrets/django.key").read_bytes(), key)


    def test_explicit_cli_import_preserves_legacy_signing_key_before_settings_load(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "legacy-config.txt"
            secret = "fixture-legacy-signing-key-" + "x" * 40
            legacy.write_text("DJANGO_SECRET_KEY=" + secret + "\n")
            env = {k: v for k, v in os.environ.items()
                   if k not in {"DJANGO_SECRET_KEY", "APP_DATA_DIR", "DJANGO_DB_PATH"}}
            env.update({"APP_DATA_DIR": directory, "DJANGO_DB_PATH": str(root / "db.sqlite3")})
            code = (
                "import os,runpy,sys; from unittest.mock import patch; "
                "sys.argv=['manage.py','import_legacy_config','--file',sys.argv[1]]; "
                "namespace=runpy.run_path('manage.py'); "
                "exec(\"with patch('django.core.management.execute_from_command_line'):\\n"
                " namespace['main']()\\n\"); "
                "print(os.environ['DJANGO_SECRET_KEY']=='fixture-legacy-signing-key-'+'x'*40)"
            )
            result = subprocess.run([sys.executable, "-c", code, str(legacy)], env=env,
                                    cwd=settings.BASE_DIR, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "True")
            self.assertFalse((root / ".secrets/django.key").exists())

class SystemConfigurationTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        override = override_settings(APP_DATA_DIR=self.root, NEO4J_ENABLE=False, NEO4J_PASSWORD="",
                                     LANGFUSE_ENABLED=False, STARTUP_CONFIG=dict(DEFAULTS),
                                     STARTUP_SAVED=dict(DEFAULTS), STARTUP_ENV_OVERRIDES=[])
        override.enable()
        self.addCleanup(override.disable)
        tenant = Tenant.objects.create(name="config-fixture", api_key="config-fixture-key")
        self.admin = User.objects.create(username="admin-fixture", email="admin@fixture.test",
                                         tenant=tenant, is_system_admin=True)
        self.normal = User.objects.create(username="normal-fixture", email="normal@fixture.test", tenant=tenant)
        token, _ = issue_tokens(self.admin)
        self.headers = {"HTTP_AUTHORIZATION": "Bearer " + token}
        token, _ = issue_tokens(self.normal)
        self.normal_headers = {"HTTP_AUTHORIZATION": "Bearer " + token}

    def put(self, section, values, headers=None):
        return self.client.put("/api/v1/system/config/" + section, json.dumps(values),
                               content_type="application/json", **(self.headers if headers is None else headers))

    def raw(self, name):
        with connection.cursor() as cursor:
            cursor.execute("SELECT parameters FROM integration_configs WHERE name = %s", [name])
            return cursor.fetchone()[0]

    def test_global_config_and_startup_are_system_admin_only(self):
        for section in ("application", "neo4j", "langfuse", "local_services", "startup"):
            url = "/api/v1/system/config/" + section
            self.assertEqual(self.client.get(url).status_code, 401)
            self.assertEqual(self.client.get(url, **self.normal_headers).status_code, 403)
            self.assertEqual(self.put(section, {}, self.normal_headers).status_code, 403)
        self.assertEqual(IntegrationConfig.objects.count(), 0)
        self.assertFalse((self.root / ".settings/startup.json").exists())

    def test_application_name_changes_public_info(self):
        self.assertEqual(self.put("application", {"name": "Changed fixture"}).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/system/info").json()["data"]["name"], "Changed fixture")

    def test_secrets_are_encrypted_never_returned_and_blank_is_preserved(self):
        for section, values in (
            ("neo4j", {"enabled": True, "uri": "bolt://localhost:7687", "username": "neo4j", "password": "fixture-password"}),
            ("local_services", {"auto_login": True, "login_email": "test@fixture.invalid", "password": "fixture-password"}),
            ("langfuse", {"enabled": True, "base_url": "http://localhost:3000", "public_key": "fixture-public", "secret_key": "fixture-password"}),
        ):
            response = self.put(section, values)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertNotIn("fixture-password", response.content.decode())
            self.assertNotIn("enc:v1:", response.content.decode())
            self.assertEqual(response["Cache-Control"], "no-store")
            self.assertIn("enc:v1:", self.raw(section))
            self.assertNotIn("fixture-password", self.raw(section))
            field = "secret_key" if section == "langfuse" else "password"
            self.assertEqual(self.put(section, {field: ""}).status_code, 200)
            self.assertEqual(IntegrationConfig.objects.get(name=section).parameters[field], "fixture-password")

    def test_delete_is_explicit_and_disables_service(self):
        self.put("neo4j", {"enabled": True, "password": "fixture-password"})
        url = "/api/v1/system/config/neo4j"
        self.assertEqual(self.client.delete(url, **self.headers).status_code, 400)
        response = self.client.delete(url, json.dumps({"field": "password"}), content_type="application/json", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(neo4j_configuration()["enabled"])
        self.assertEqual(neo4j_configuration()["password"], "")

    def test_validation_rejects_bad_types_bounds_urls_and_unknown_keys(self):
        for section, values in (
            ("neo4j", {"enabled": "true"}), ("neo4j", {"uri": "bolt://user:password@host"}),
            ("langfuse", {"sample_rate": 2}), ("langfuse", {"sample_rate": True}),
            ("langfuse", {"sample_rate": float("nan")}), ("langfuse", {"base_url": "https://host\\@evil"}),
            ("langfuse", {"secret_key": "enc:v1:fake"}), ("application", {"name": ""}),
            ("application", {"unexpected": "value"}), ("local_services", {"startup_timeout_seconds": 200}),
        ):
            with self.subTest(section=section, values=values):
                self.assertEqual(self.put(section, values).status_code, 400)

    def test_enabling_services_requires_credentials(self):
        for section, values in (("neo4j", {"enabled": True}), ("langfuse", {"enabled": True}),
                                ("local_services", {"auto_login": True})):
            self.assertEqual(self.put(section, values).status_code, 400)

    def test_startup_save_is_deferred_and_bad_updates_are_atomic(self):
        response = self.put("startup", {"task_workers": 8, "sqlite_timeout": 12})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["restart_required"])
        self.assertEqual(response.json()["data"]["active"]["task_workers"], 4)
        self.assertEqual(read_startup(self.root)["task_workers"], 8)
        self.assertEqual(self.put("startup", {"task_workers": 0}).status_code, 400)
        self.assertEqual(read_startup(self.root)["task_workers"], 8)

    def test_startup_get_does_not_expose_secrets(self):
        persistent_secret(self.root)
        response = self.client.get("/api/v1/system/config/startup", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(persistent_secret(self.root), response.content.decode())
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_neo4j_connection_recreated_after_configuration_change_and_closed_when_disabled(self):
        from personal_knowledge_base.graph_rag import Neo4jGraphRepository
        from personal_knowledge_base.memory import MemoryRepository
        self.put("neo4j", {"enabled": True, "password": "fixture-password"})
        for repository in (Neo4jGraphRepository(), MemoryRepository()):
            with self.subTest(repository=type(repository).__name__), patch("neo4j.GraphDatabase.driver") as factory:
                first = MagicMock()
                second = MagicMock()
                factory.side_effect = [first, second]
                self.assertIs(repository.driver, first)
                self.assertIs(repository.driver, first)
                self.put("neo4j", {"uri": "bolt://localhost:7766"})
                # Ensure each repository sees an actual change, even on the second iteration.
                row = IntegrationConfig.objects.get(name="neo4j")
                row.parameters["password"] = "rotated-fixture"
                row.save()
                self.assertIs(repository.driver, second)
                first.close.assert_called_once()
                self.put("neo4j", {"enabled": False})
                self.assertIsNone(repository.driver)
                second.close.assert_called_once()
            self.put("neo4j", {"enabled": True, "password": "fixture-password", "uri": "bolt://localhost:7687"})

    def test_langfuse_options_are_read_from_database(self):
        from personal_knowledge_base import observability
        self.put("langfuse", {"log_content": True, "sample_rate": 0, "orphan_mode": "standalone", "upload_eval_datasets": True})
        self.assertTrue(observability.langfuse_log_content())
        self.assertFalse(observability._root_sampled())
        self.assertEqual(langfuse_configuration()["orphan_mode"], "standalone")

    def test_local_login_reads_saved_values(self):
        from personal_knowledge_base.langfuse_access import configuration
        self.put("langfuse", {"base_url": "http://localhost:3210", "ui_base_url": "http://localhost:3211", "ui_project_id": "fixture-project"})
        self.put("local_services", {"auto_login": True, "login_email": "login@fixture.test", "password": "fixture-login", "local_login_user_id": "fixture-user"})
        cfg = configuration()
        self.assertEqual(cfg["base"], "http://localhost:3210")
        self.assertEqual(cfg["ui_base"], "http://localhost:3211")
        self.assertEqual(cfg["password"], "fixture-login")
        self.assertEqual(cfg["local_user_id"], "fixture-user")
        self.assertTrue(cfg["auto"])

    def test_connection_test_is_bounded_and_redacts_errors(self):
        self.put("neo4j", {"password": "fixture-password"})
        with patch("neo4j.GraphDatabase.driver", side_effect=RuntimeError("fixture-password")):
            response = self.client.post("/api/v1/system/config/neo4j/test", **self.headers)
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("fixture-password", response.content.decode())
        self.assertEqual(self.client.post("/api/v1/system/config/neo4j/test", **self.normal_headers).status_code, 403)

    def test_connection_success_and_langfuse_authentication(self):
        with patch("neo4j.GraphDatabase.driver") as driver:
            response = self.client.post("/api/v1/system/config/neo4j/test", **self.headers)
            self.assertEqual(response.status_code, 200)
            driver.return_value.__enter__.return_value.verify_connectivity.assert_called_once()
            self.assertEqual(driver.call_args.kwargs["connection_timeout"], 5)
        self.put("langfuse", {"public_key": "fixture-public", "secret_key": "fixture-secret"})
        with patch("httpx.Client") as factory:
            response = self.client.post("/api/v1/system/config/langfuse/test", **self.headers)
            self.assertEqual(response.status_code, 200)
            factory.assert_called_once_with(trust_env=False, timeout=5, follow_redirects=False)

    def test_import_is_idempotent_preserves_database_and_encrypts_passwords(self):
        legacy = self.root / "legacy-config.txt"
        legacy.write_text("APP_NAME=legacy-fixture\nNEO4J_ENABLE=true\nNEO4J_URI=bolt://localhost:7687\n"
                          "NEO4J_PASSWORD=legacy-password\nLANGFUSE_SAMPLE_RATE=0.5\nno_proxy=localhost\n")
        IntegrationConfig.objects.create(name="application", parameters={"name": "database-wins"})
        for _ in range(2):
            output = StringIO()
            call_command("import_legacy_config", file=str(legacy), stdout=output)
            self.assertNotIn("legacy-password", output.getvalue())
        self.assertEqual(IntegrationConfig.objects.get(name="application").parameters["name"], "database-wins")
        self.assertNotIn("legacy-password", self.raw("neo4j"))
        self.assertEqual(neo4j_configuration()["password"], "legacy-password")
        self.assertEqual(langfuse_configuration()["sample_rate"], 0.5)
        self.assertEqual(read_startup(self.root)["no_proxy"], "localhost")

    def test_import_retains_startup_file_and_reports_unmapped_fields(self):
        update_startup(self.root, {"task_workers": 6})
        legacy = self.root / "legacy-config.txt"
        legacy.write_text("APP_TASK_WORKERS=10\n")
        call_command("import_legacy_config", file=str(legacy), stdout=StringIO())
        self.assertEqual(read_startup(self.root)["task_workers"], 6)
        legacy.write_text("UNMAPPED_FIXTURE=value\n")
        with self.assertRaises(CommandError):
            call_command("import_legacy_config", file=str(legacy), stdout=StringIO())

    def test_import_server_defaults_into_encrypted_records(self):
        legacy = self.root / "legacy-config.txt"
        legacy.write_text("")
        server = self.root / "server-config.txt"
        server.write_text("LANGFUSE_INIT_PROJECT_ID=fixture-project\nLANGFUSE_INIT_USER_EMAIL=fixture@example.test\nLANGFUSE_INIT_USER_PASSWORD=fixture-login-secret\n")
        call_command("import_legacy_config", file=str(legacy), server_file=str(server), stdout=StringIO())
        self.assertEqual(langfuse_configuration()["ui_project_id"], "fixture-project")
        self.assertNotIn("fixture-login-secret", self.raw("local_services"))

    def test_import_retains_old_signing_key_and_rejects_replacing_existing_installation_key(self):
        legacy = self.root / "legacy-config.txt"
        secret = "fixture-signing-key-" + "x" * 40
        legacy.write_text("DJANGO_SECRET_KEY=" + secret + "\n")
        call_command("import_legacy_config", file=str(legacy), stdout=StringIO())
        self.assertEqual(persistent_secret(self.root), secret)
        legacy.write_text("DJANGO_SECRET_KEY=" + "y" * 64 + "\n")
        with self.assertRaises(CommandError):
            call_command("import_legacy_config", file=str(legacy), stdout=StringIO())
        self.assertEqual(persistent_secret(self.root), secret)

    def test_sqlite_connection_respects_configured_lock_timeout(self):
        from personal_knowledge_base.startup import _enable_wal_mode
        raw = MagicMock()
        fake = MagicMock(vendor="sqlite", connection=raw)
        fake.settings_dict = {"OPTIONS": {"timeout": 12}}
        _enable_wal_mode(fake)
        raw.execute.assert_any_call("PRAGMA busy_timeout=12000")

    def test_real_langfuse_sdk_rotates_same_public_key_endpoint_and_secret_offline(self):
        from personal_knowledge_base import observability as obs
        from langfuse._client.resource_manager import LangfuseResourceManager
        config = {"enabled": True, "public_key": "fixture-sdk-config-rotation",
                  "secret_key": "fixture-old-secret", "base_url": "https://old.fixture.invalid",
                  "tracing_environment": "fixture-old"}
        row = IntegrationConfig.objects.create(name="langfuse", parameters=config)
        with patch.object(obs, "_client", None), patch.object(obs, "_client_ready", False), \
             patch.object(obs, "_client_signature", None), \
             patch("socket.socket", side_effect=AssertionError("network forbidden")):
            first = obs.get_langfuse()
            self.assertIsNotNone(first)
            first_resources = first._resources
            self.assertEqual(first_resources.secret_key, "fixture-old-secret")
            row.parameters.update({"secret_key": "fixture-new-secret", "base_url": "https://new.fixture.invalid",
                                   "tracing_environment": "fixture-new"})
            row.save()
            second = None
            try:
                second = obs.get_langfuse()
                self.assertIsNotNone(second)
                self.assertIsNot(first_resources, second._resources)
                self.assertEqual(second._resources.secret_key, "fixture-new-secret")
                self.assertEqual(second._resources.base_url, "https://new.fixture.invalid")
                self.assertTrue(first_resources.httpx_client.is_closed)
                self.assertEqual(second._configuration_provider.resource.attributes["langfuse.environment"], "fixture-new")
                self.assertIs(LangfuseResourceManager._instances[config["public_key"]], second._resources)
            finally:
                obs._retire_langfuse_client(second or first)
