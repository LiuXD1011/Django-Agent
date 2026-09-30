"""Settings aliases resolve consistently in an isolated, offline interpreter."""
import json
import os
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase


class LangfuseSettingsDefaultsTests(SimpleTestCase):
    def resolve(self, values):
        code = '''
import json
import os
import runpy
from unittest.mock import patch
from scripts.local_services import langfuse_api_base
with patch("pathlib.Path.exists", return_value=False), patch("socket.socket", side_effect=AssertionError("network forbidden")):
    configured = runpy.run_path("config/settings.py")
    print(json.dumps({"base": configured["LANGFUSE_BASE_URL"], "host": configured["LANGFUSE_HOST"],
                      "ui": configured["LANGFUSE_UI_BASE_URL"], "helper": langfuse_api_base(os.environ)}))
'''
        env = {name: value for name, value in os.environ.items() if not name.startswith("LANGFUSE_")}
        env.update({"DJANGO_SECRET_KEY": "synthetic-settings-test", "LANGFUSE_AUTOSTART": "false", **values})
        completed = subprocess.run([sys.executable, "-c", code], cwd=settings.BASE_DIR, env=env,
                                   text=True, capture_output=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_absent_and_explicitly_empty_aliases_default_to_localhost(self):
        for values in ({}, {"LANGFUSE_BASE_URL": "", "LANGFUSE_HOST": "", "LANGFUSE_UI_BASE_URL": ""}):
            with self.subTest(values=values):
                self.assertEqual(self.resolve(values), {name: "http://localhost:3000" for name in ("base", "host", "ui", "helper")})

    def test_base_host_and_explicit_ui_precedence_is_retained(self):
        for values, base, ui in (
            ({"LANGFUSE_BASE_URL": "", "LANGFUSE_HOST": "http://localhost:3100"}, "http://localhost:3100", "http://localhost:3100"),
            ({"LANGFUSE_BASE_URL": "http://localhost:3200", "LANGFUSE_HOST": "http://localhost:3100"}, "http://localhost:3200", "http://localhost:3200"),
            ({"LANGFUSE_BASE_URL": "", "LANGFUSE_HOST": "", "LANGFUSE_UI_BASE_URL": "https://ui.fixture.invalid"}, "http://localhost:3000", "https://ui.fixture.invalid"),
        ):
            with self.subTest(values=values):
                self.assertEqual(self.resolve(values), {"base": base, "host": base, "ui": ui, "helper": base})
