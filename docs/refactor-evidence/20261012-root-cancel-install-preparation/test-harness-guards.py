"""Only exercise non-executing flags; never request an executable phase."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

SCRIPT = Path(r"\\wsl.localhost\Ubuntu-20.04\tmp\marlin-agent-cancel-install-20261012.py") if os.name == "nt" else Path("/tmp/marlin-agent-cancel-install-20261012.py")


class ReviewOnlyGuards(unittest.TestCase):
    def invoke(self, *arguments):
        allowed = {"systemroot", "windir", "systemdrive", "comspec", "userprofile", "appdata", "localappdata", "temp", "tmp", "pathext"}
        environment = {key: value for key, value in os.environ.items() if key.casefold() in allowed}
        return subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), *arguments], env=environment, capture_output=True, text=True, encoding="utf-8", timeout=15, check=False)

    def test_default_only_reviews(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["state"], "review_only")
        self.assertEqual(value["script_sha256"], hashlib.sha256(SCRIPT.read_bytes()).hexdigest())
        self.assertEqual(value["windows_child_processes_started"], 0)
        for name in ("application_started", "installer_executed", "registry_writes", "data_changes", "automatic_retry_or_resume"):
            self.assertIs(value[name], False)

    def test_hash_without_execution_refused(self):
        result = self.invoke("--reviewed-script-sha256", "0" * 64)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error_code"], "hash_arguments_require_explicit_execution")

    def test_survey_hash_without_execution_refused(self):
        result = self.invoke("--readonly-survey-sha256", "0" * 64)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error_code"], "hash_arguments_require_explicit_execution")

    def test_duplicate_readonly_flag_refused_before_survey(self):
        result = self.invoke("--survey-readonly", "--survey-readonly")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error_code"], "duplicate_or_equals_flags_refused")

    def test_equals_flag_form_refused(self):
        result = self.invoke("--reviewed-script-sha256=" + "0" * 64)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error_code"], "duplicate_or_equals_flags_refused")

    def test_arbitrary_installation_path_not_accepted(self):
        result = self.invoke("--installation-dir", "UNAUTHORIZED")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
