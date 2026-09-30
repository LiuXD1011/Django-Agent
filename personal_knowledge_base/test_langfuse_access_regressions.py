"""Offline contracts for API/UI configuration and the local cookie bridge."""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings

from .langfuse_access import configuration, langfuse_access
from scripts.local_services import ensure_langfuse


class LangfuseConfigurationRegressions(SimpleTestCase):
    def config(self, env, server_project="fixture-init"):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".env.langfuse").write_text(f"LANGFUSE_INIT_PROJECT_ID={server_project}\n")
            with override_settings(BASE_DIR=Path(directory)), patch("scripts.local_services.local_env", return_value=env):
                return configuration()

    def test_api_base_precedes_host_and_defaults_to_localhost(self):
        self.assertEqual(self.config({"LANGFUSE_BASE_URL": "http://localhost:3100", "LANGFUSE_HOST": "http://127.0.0.1:3200"})["base"], "http://localhost:3100")
        self.assertEqual(self.config({"LANGFUSE_HOST": "http://localhost:3200"})["base"], "http://localhost:3200")
        self.assertEqual(self.config({})["base"], "http://localhost:3000")

    def test_ui_base_and_project_precedence(self):
        env = {"LANGFUSE_BASE_URL": "http://localhost:3100", "LANGFUSE_UI_BASE_URL": "https://traces.example.invalid/console/",
               "LANGFUSE_UI_PROJECT_ID": "fixture-ui", "LANGFUSE_PROJECT_ID": "fixture-legacy"}
        cfg = self.config(env)
        self.assertEqual(cfg["ui_base"], "https://traces.example.invalid/console")
        self.assertEqual(cfg["project"], "fixture-ui")
        self.assertEqual(self.config({"LANGFUSE_PROJECT_ID": "fixture-legacy"})["project"], "fixture-legacy")
        self.assertEqual(self.config({})["project"], "fixture-init")
        self.assertEqual(self.config({})["ui_base"], "http://localhost:3000")

    def test_startup_uses_api_base_for_selection_and_health(self):
        env = {"LANGFUSE_AUTOSTART": "true", "LANGFUSE_BASE_URL": "http://localhost:3100", "LANGFUSE_HOST": "https://remote.example.invalid",
               "LANGFUSE_UI_BASE_URL": "https://ui.example.invalid"}
        with tempfile.TemporaryDirectory() as directory, patch("scripts.local_services.local_env", return_value=env), \
             patch("scripts.local_services.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run, \
             patch("scripts.local_services.build_opener") as opener:
            Path(directory, ".env.langfuse").touch()
            opener.return_value.open.return_value.__enter__.return_value.status = 200
            self.assertEqual(ensure_langfuse(directory)["state"], "healthy")
            run.assert_called()
            self.assertEqual(opener.return_value.open.call_args.args[0], "http://localhost:3100/api/public/health")


@override_settings(ALLOWED_HOSTS=["localhost", "app.example.invalid"])
class LangfuseBridgeRegressions(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.user = SimpleNamespace(id="fixture-admin", is_active=True, is_system_admin=True)
        self.cfg = {"base": "http://localhost:3000", "ui_base": "http://localhost:3001", "project": "fixture/project",
                    "email": "fixture@example.invalid", "password": "fixture-password", "auto": True}

    def request(self, action="session", host="localhost:8000", remote="127.0.0.1", origin=None):
        method = self.factory.get if action == "status" else self.factory.post
        return method("/", HTTP_HOST=host, REMOTE_ADDR=remote, HTTP_ORIGIN=origin or f"http://{host}")

    def invoke(self, request, action="session", cfg=None, user=True):
        with patch("personal_knowledge_base.langfuse_access.configuration", return_value=cfg or self.cfg), \
             patch("personal_knowledge_base.langfuse_access.auth_context", return_value=(self.user if user else None, None)):
            return langfuse_access(request, action)

    def code(self, response):
        return json.loads(response.content)["error"]["code"]

    def test_auto_disabled_returns_manual_fallback_before_loopback_check(self):
        cfg = {**self.cfg, "base": "https://api.example.invalid", "ui_base": "https://ui.example.invalid", "auto": False}
        with patch("personal_knowledge_base.langfuse_access.httpx.Client") as client:
            response = self.invoke(self.request(host="app.example.invalid", remote="192.0.2.1"), cfg=cfg)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.code(response), "auto_login_disabled")
        client.assert_not_called()

    def test_manual_fallback_still_requires_real_authorized_user_and_origin(self):
        cfg = {**self.cfg, "auto": False}
        for user, origin, expected in [(False, None, "local_account_required"), (True, "https://wrong.example.invalid", "origin_mismatch")]:
            with self.subTest(expected=expected):
                self.assertEqual(self.code(self.invoke(self.request(origin=origin), cfg=cfg, user=user)), expected)
        self.user.is_active = False
        self.assertEqual(self.code(self.invoke(self.request(), cfg=cfg)), "local_account_required")

    def test_remote_status_uses_api_health_and_configured_manual_ui(self):
        cfg = {**self.cfg, "base": "https://api.example.invalid", "ui_base": "https://ui.example.invalid/console", "auto": False}
        with patch("personal_knowledge_base.langfuse_access.httpx.Client") as factory:
            client = factory.return_value.__enter__.return_value
            client.get.return_value.status_code = 200
            response = self.invoke(self.request("status", host="app.example.invalid", remote="192.0.2.1"), "status", cfg)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["open_url"], "https://ui.example.invalid/console/project/fixture%2Fproject/traces")
        client.get.assert_called_once_with("https://api.example.invalid/api/public/health")

    def test_status_rejects_unsafe_ui_url_without_network(self):
        for target in ["javascript:alert(1)", "https://user:password@ui.example.invalid", "https://ui.example.invalid?redirect=other",
                       "https://ui.example.invalid/#fragment", "https://ui.example.invalid:bad", "https://ui.example.invalid\\@evil.invalid", "https://ui.example.invalid/\n"]:
            with self.subTest(target=target), patch("personal_knowledge_base.langfuse_access.httpx.Client") as client:
                response = self.invoke(self.request("status"), "status", {**self.cfg, "ui_base": target})
                self.assertEqual(response.status_code, 400)
                client.assert_not_called()

    def test_remote_login_and_different_ui_host_never_transfer_credentials(self):
        for cfg, request in [({**self.cfg, "ui_base": "http://127.0.0.1:3001"}, self.request()),
                             ({**self.cfg, "base": "https://api.example.invalid", "ui_base": "https://ui.example.invalid"}, self.request()),
                             (self.cfg, self.request(remote="192.0.2.1"))]:
            with self.subTest(cfg=cfg), patch("personal_knowledge_base.langfuse_access.httpx.Client") as client:
                self.assertEqual(self.code(self.invoke(request, cfg=cfg)), "local_host_required")
                client.assert_not_called()

    def test_local_login_calls_api_but_returns_same_host_ui_url(self):
        client = MagicMock()
        session = {"user": {"email": self.cfg["email"], "organizations": [{"projects": [{"id": self.cfg["project"]}]}]}}
        client.get.side_effect = [SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"csrfToken": "fixture-csrf"}), SimpleNamespace(json=lambda: session)]
        client.cookies.jar = [SimpleNamespace(name="next-auth.session-token", value="fixture-session")]
        with patch("personal_knowledge_base.langfuse_access.httpx.Client") as factory:
            factory.return_value.__enter__.return_value = client
            response = self.invoke(self.request())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["open_url"], "http://localhost:3001/project/fixture%2Fproject/traces")
        self.assertEqual(client.post.call_args.args[0], "http://localhost:3000/api/auth/callback/credentials")
        self.assertEqual(list(response.cookies), ["next-auth.session-token"])

    def test_clear_retains_local_cookie_guard(self):
        request = self.request(host="app.example.invalid", remote="192.0.2.1")
        request.COOKIES = {"next-auth.session-token": "fixture"}
        response = self.invoke(request, "clear", {**self.cfg, "auto": False}, user=False)
        self.assertEqual(self.code(response), "local_host_required")
        self.assertFalse(response.cookies)
