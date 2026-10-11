"""W04 运行时分层回归：健康端点语义分离 + APP_MODE 后台组件门控。"""
from unittest.mock import patch

from django.test import Client, SimpleTestCase, TestCase, override_settings

from .authentication import issue_tokens
from .models import Tenant, TenantMember, User


class LivenessTests(SimpleTestCase):
    """livez 不允许任何数据库访问：依赖故障不能表现为活性丧失。"""

    def test_livez_is_dependency_free(self):
        with patch("django.db.backends.utils.CursorWrapper.execute",
                   side_effect=AssertionError("livez must not query the database")):
            response = Client().get("/livez")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "alive")


class ReadinessTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(name="runtime-health", api_key="runtime-health-key")
        user = User.objects.create(
            username="runtime-health-owner", email="runtime-health@fixture.invalid",
            password_hash="unused", tenant=tenant,
        )
        TenantMember.objects.create(user=user, tenant=tenant, role="owner")
        token, _ = issue_tokens(user)
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_readyz_reports_components(self):
        response = Client().get("/readyz")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["status"], "ready")
        self.assertTrue(body["components"]["database"]["ok"])
        self.assertTrue(body["components"]["migrations"]["ok"])
        self.assertIn("vector_index", body["components"])

    def test_components_view_never_fails_and_marks_degraded(self):
        with patch("personal_knowledge_base.runtime_health._health_snapshot",
                   return_value={"ready": False, "healthy": False, "components": {"database": {"ok": False, "error": "boom"}}}):
            response = Client().get("/health/components", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "degraded")
        self.assertFalse(response.json()["components"]["database"]["ok"])

    def test_readyz_fails_closed_when_database_unavailable(self):
        with patch("personal_knowledge_base.runtime_health._health_snapshot",
                   return_value={"ready": False, "healthy": False, "components": {"database": {"ok": False, "error": "boom"}}}):
            response = Client().get("/readyz")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "not_ready")


class AppModeGateTests(SimpleTestCase):
    def test_invalid_app_mode_fails_startup(self):
        import os
        import subprocess
        import sys

        from django.conf import settings

        env = {k: v for k, v in os.environ.items() if k != "APP_MODE"}
        env.update({
            "DJANGO_SETTINGS_MODULE": "config.settings",
            "APP_MODE": "bogus",
            "DJANGO_DEBUG": "true",
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        completed = subprocess.run(
            [sys.executable, "-c", "import django; django.setup()"],
            cwd=str(settings.BASE_DIR), env=env, capture_output=True, text=True, timeout=60,
        )
        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("APP_MODE", completed.stderr)

    def test_api_mode_does_not_start_background_components(self):
        from django.apps import apps

        config = apps.get_app_config("personal_knowledge_base")

        with override_settings(RUN_TASK_BACKGROUND=False), \
             patch("personal_knowledge_base.startup.check_sqlite_capabilities"), \
             patch("personal_knowledge_base.tasks.start_task_runner") as runner, \
             patch("personal_knowledge_base.tasks.schedule_startup_recovery") as recovery:
            config.ready()
        runner.assert_not_called()
        recovery.assert_not_called()

    def test_local_mode_keeps_background_components(self):
        from django.apps import apps

        config = apps.get_app_config("personal_knowledge_base")

        with override_settings(RUN_TASK_BACKGROUND=True), \
             patch("personal_knowledge_base.startup.check_sqlite_capabilities"), \
             patch("personal_knowledge_base.tasks.start_task_runner") as runner, \
             patch("personal_knowledge_base.tasks.schedule_startup_recovery") as recovery:
            config.ready()
        runner.assert_called_once()
        recovery.assert_called_once()
