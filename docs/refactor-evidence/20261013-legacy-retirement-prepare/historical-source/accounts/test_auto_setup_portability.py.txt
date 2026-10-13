"""Portability contract of the first-run auto-setup gate.

Covers two independent requirements:

1. Import surface: the auth module chain must import on platforms without
   ``fcntl`` (Windows). The probe runs accounts.views and the project URL
   configuration inside a fresh Python subprocess where ``fcntl`` is blocked
   at the import-system level, mirroring the native Windows behaviour.
2. Locking contract: the SQLite gate uses a cross-platform native file lock
   with a bounded wait; equivalent database paths map to one lock file,
   distinct databases never block each other, timeout maps to HTTP 503
   ``setup_busy``, and lock errors never fall back to a lockless setup.

The lock-semantics tests exercise ``filelock`` directly and therefore run
unchanged on Windows, Linux and macOS.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from django.db import connections
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from personal_knowledge_base.models import AuthToken, Tenant, User

REPO_ROOT = Path(__file__).resolve().parents[1]

_BASE_ENV_KEYS = (
    "APPDATA",
    "COMSPEC",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LOCALAPPDATA",
    "PATH",
    "PATHEXT",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USERPROFILE",
)

_ISOLATED_SETTINGS_ENV = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "DJANGO_SETTINGS_MODULE": "config.settings",
    "DJANGO_DEBUG": "true",
    "ALLOW_AUTO_SETUP": "true",
    "NEO4J_ENABLE": "false",
    "LANGFUSE_ENABLED": "false",
    "LANGFUSE_AUTOSTART": "false",
    "DJANGO_ALLOWED_HOSTS": "testserver,localhost",
}


def _isolated_env(**overrides):
    env = {key: os.environ[key] for key in _BASE_ENV_KEYS if key in os.environ}
    env.update(_ISOLATED_SETTINGS_ENV)
    env.update(overrides)
    return env


_FCNTL_BLOCKED_IMPORT_PROBE = r"""
import sys
from importlib.abc import MetaPathFinder


class FcntlUnavailable(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "fcntl":
            raise ModuleNotFoundError("No module named 'fcntl'", name="fcntl")
        return None


sys.meta_path.insert(0, FcntlUnavailable())

try:
    import fcntl  # noqa: F401
except ModuleNotFoundError:
    pass
else:
    raise SystemExit("probe broken: fcntl import was not blocked")

import django

django.setup()

import accounts.views  # noqa: F401
import config.urls  # noqa: F401

assert hasattr(accounts.views, "auth_auto_setup")
assert config.urls.urlpatterns
print("IMPORT_OK")
"""


class NoFcntlImportContractTests(SimpleTestCase):
    def test_accounts_views_and_url_config_import_without_fcntl(self):
        """A1: auth module chain imports on a platform without fcntl."""
        with tempfile.TemporaryDirectory() as tmp:
            env = _isolated_env(DJANGO_DB_PATH=os.path.join(tmp, "import-probe.sqlite3"))
            completed = subprocess.run(
                [sys.executable, "-c", _FCNTL_BLOCKED_IMPORT_PROBE],
                cwd=str(REPO_ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
            )

        self.assertEqual(
            completed.returncode,
            0,
            "import probe failed\n--- stdout ---\n%s\n--- stderr tail ---\n%s"
            % (completed.stdout, "\n".join(completed.stderr.splitlines()[-15:])),
        )
        self.assertIn("IMPORT_OK", completed.stdout)


class SqliteAutoSetupLockPathTests(SimpleTestCase):
    def test_symlinked_database_paths_share_one_lock_file(self):
        from accounts import views as accounts_views

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "db.sqlite3")
            Path(db_path).write_bytes(b"")
            alias_path = os.path.join(tmp, "alias.sqlite3")
            try:
                os.symlink(db_path, alias_path)
            except (NotImplementedError, OSError):
                self.skipTest("symlinks are not available on this platform/account")

            self.assertEqual(
                accounts_views._sqlite_auto_setup_lock_path(alias_path),
                accounts_views._sqlite_auto_setup_lock_path(db_path),
            )

    def test_redundant_dot_segments_share_one_lock_file(self):
        """Dot-path normalization needs no symlink support; runs on every platform."""
        from accounts import views as accounts_views

        with tempfile.TemporaryDirectory() as tmp:
            base = str(Path(tmp).resolve())

        self.assertEqual(
            accounts_views._sqlite_auto_setup_lock_path(os.path.join(base, ".", "db.sqlite3")),
            accounts_views._sqlite_auto_setup_lock_path(os.path.join(base, "db.sqlite3")),
        )

    def test_distinct_databases_use_distinct_lock_files(self):
        from accounts import views as accounts_views

        with tempfile.TemporaryDirectory() as tmp:
            path_a = accounts_views._sqlite_auto_setup_lock_path(os.path.join(tmp, "a.sqlite3"))
            path_b = accounts_views._sqlite_auto_setup_lock_path(os.path.join(tmp, "b.sqlite3"))

        self.assertNotEqual(path_a, path_b)


class CrossPlatformLockSemanticsTests(SimpleTestCase):
    """filelock-backed semantics that run unchanged on Windows/Linux/macOS."""

    def test_gate_lock_path_is_exclusive_with_bounded_wait(self):
        from accounts import views as accounts_views
        from filelock import FileLock, Timeout

        with tempfile.TemporaryDirectory() as tmp:
            lock_path = accounts_views._sqlite_auto_setup_lock_path(os.path.join(tmp, "db.sqlite3"))
            holder = FileLock(lock_path)
            contender = FileLock(lock_path)

            holder.acquire(timeout=5)
            try:
                self.assertTrue(holder.is_locked)
                with self.assertRaises(Timeout):
                    contender.acquire(timeout=0.2)
                self.assertFalse(contender.is_locked)
            finally:
                holder.release()

            self.assertFalse(holder.is_locked)
            contender.acquire(timeout=5)
            try:
                self.assertTrue(contender.is_locked)
            finally:
                contender.release()
            self.assertFalse(contender.is_locked)

    def test_distinct_databases_do_not_block_each_other(self):
        from accounts import views as accounts_views
        from filelock import FileLock

        with tempfile.TemporaryDirectory() as tmp:
            lock_a = FileLock(accounts_views._sqlite_auto_setup_lock_path(os.path.join(tmp, "a.sqlite3")))
            lock_b = FileLock(accounts_views._sqlite_auto_setup_lock_path(os.path.join(tmp, "b.sqlite3")))

            lock_a.acquire(timeout=2)
            try:
                lock_b.acquire(timeout=2)
                try:
                    self.assertTrue(lock_a.is_locked)
                    self.assertTrue(lock_b.is_locked)
                finally:
                    lock_b.release()
            finally:
                lock_a.release()

            self.assertFalse(lock_a.is_locked)
            self.assertFalse(lock_b.is_locked)


class AutoSetupDisabledTests(TestCase):
    @override_settings(ALLOW_AUTO_SETUP=False)
    def test_disabled_setup_rejects_without_attempting_the_lock(self):
        from accounts import views as accounts_views

        with mock.patch("filelock.FileLock.acquire", side_effect=AssertionError("lock attempted")):
            response = accounts_views.auth_auto_setup(
                RequestFactory().post("/api/v1/auth/auto-setup", content_type="application/json")
            )

        self.assertEqual(response.status_code, 401)
        payload = json.loads(response.content)
        self.assertEqual(payload["error"]["code"], "auto_setup_disabled")
        self.assertEqual(User.objects.count(), 0)


class AutoSetupLockTimeoutTests(TestCase):
    @override_settings(ALLOW_AUTO_SETUP=True)
    def test_lock_timeout_returns_503_setup_busy_without_creating_accounts(self):
        from accounts import views as accounts_views

        lock_path = accounts_views._sqlite_auto_setup_lock_path(connections["default"].settings_dict["NAME"])
        holder = accounts_views.FileLock(lock_path)
        holder.acquire(timeout=5)
        try:
            request = RequestFactory().post("/api/v1/auth/auto-setup", content_type="application/json")
            with mock.patch.object(accounts_views, "AUTO_SETUP_LOCK_TIMEOUT", 0.2):
                response = accounts_views.auth_auto_setup(request)
        finally:
            holder.release()

        self.assertEqual(response.status_code, 503)
        payload = json.loads(response.content)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"]["code"], "setup_busy")
        body = response.content.decode()
        self.assertNotIn(lock_path, body)
        self.assertNotIn(tempfile.gettempdir(), body)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(AuthToken.objects.count(), 0)

        # The lock must stay usable for the successor once the holder releases:
        # a timed-out attempt must not wedge the gate.
        followup = accounts_views.auth_auto_setup(
            RequestFactory().post("/api/v1/auth/auto-setup", content_type="application/json")
        )
        self.assertEqual(followup.status_code, 201)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(AuthToken.objects.count(), 2)

    def test_default_lock_wait_is_bounded(self):
        from accounts import views as accounts_views

        self.assertIsInstance(accounts_views.AUTO_SETUP_LOCK_TIMEOUT, (int, float))
        self.assertEqual(accounts_views.AUTO_SETUP_LOCK_TIMEOUT, 10)


class AutoSetupLockFailureTests(TestCase):
    @override_settings(ALLOW_AUTO_SETUP=True)
    def test_lock_error_does_not_fall_back_to_lockless_setup(self):
        from accounts import views as accounts_views

        with mock.patch("filelock.FileLock.acquire", side_effect=OSError("lock backend unavailable")):
            with self.assertRaises(OSError):
                accounts_views.auth_auto_setup(
                    RequestFactory().post("/api/v1/auth/auto-setup", content_type="application/json")
                )

        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(AuthToken.objects.count(), 0)


class AutoSetupCriticalSectionTests(TestCase):
    @override_settings(ALLOW_AUTO_SETUP=True)
    def test_exception_inside_critical_section_rolls_back_and_releases_lock(self):
        from accounts import views as accounts_views

        request = RequestFactory().post("/api/v1/auth/auto-setup", content_type="application/json")
        with mock.patch.object(accounts_views, "issue_tokens", side_effect=RuntimeError("injected failure")):
            with self.assertRaises(RuntimeError):
                accounts_views.auth_auto_setup(request)

        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Tenant.objects.count(), 0)
        self.assertEqual(AuthToken.objects.count(), 0)

        response = accounts_views.auth_auto_setup(
            RequestFactory().post("/api/v1/auth/auto-setup", content_type="application/json")
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Tenant.objects.count(), 1)
        self.assertEqual(AuthToken.objects.count(), 2)
