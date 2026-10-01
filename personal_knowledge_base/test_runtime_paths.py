"""MARLIN-D1 user-data-root separation contract.

``APP_DATA_DIR`` (optional, empty/whitespace = unspecified) redirects every
runtime write — SQLite database, media, staticfiles, the five ``.cache``
families (model-rate-limits, eval-datasets, eval-reports, open-rag-runs,
Langfuse startup state) — to an independent user data root, while source
resources (templates, frontend dist, dataset manifests) stay anchored at the
source ``BASE_DIR``.  Unspecified, the behavior is byte-for-byte the
historical one: everything lands under ``BASE_DIR``.

The settings-aware helpers in ``config.runtime_paths`` re-read settings on
every call, so ``override_settings(BASE_DIR=...)`` isolation keeps working
and no path is frozen at import time.  ``resolve_data_directory`` and the
``scripts.local_services`` import chain stay Django-free.

Discipline mirrors test_runtime_lock_portability: in-process tests exercise
the real helpers with real temporary writes and assert nothing is created in
the repository; subprocess probes rebuild ``os.environ`` from a whitelist
(never inheriting credentials), avoid ``django.setup()`` entirely (settings
values only, so no recovery timers and no database access), and never touch
the network.
"""

import os
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TransactionTestCase, override_settings

from config.runtime_paths import app_data_root, resolve_data_directory, runtime_cache_dir

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

_SETTINGS_ENV = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "DJANGO_SETTINGS_MODULE": "config.settings",
    "DJANGO_DEBUG": "true",
    "NEO4J_ENABLE": "false",
    "LANGFUSE_ENABLED": "false",
    "LANGFUSE_AUTOSTART": "false",
    "DJANGO_ALLOWED_HOSTS": "testserver,localhost",
}

_SETTINGS_PROBE_PREFIX = r"""
import sys

import django
from django.conf import settings

settings._setup()  # settings values only: no app loading, no recovery timers, no DB
"""


def _probe_env(**overrides):
    """Whitelist-rebuilt environment for probes (no credential inheritance)."""
    env = {key: os.environ[key] for key in _BASE_ENV_KEYS if key in os.environ}
    env.update(_SETTINGS_ENV)
    env.update(overrides)
    return env


def _run_settings_probe(body, scratch=None, **env_overrides):
    # argv: [repo_root, scratch] — repo for repo-relative asserts, scratch for
    # probe-specific temporary paths.
    argv = [str(REPO_ROOT)]
    if scratch is not None:
        argv.append(str(scratch))
    return subprocess.run(
        [sys.executable, "-c", body, *argv],
        cwd=str(REPO_ROOT),
        env=_probe_env(**env_overrides),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _assert_probe_ok(test, completed, marker):
    test.assertEqual(
        completed.returncode,
        0,
        "probe failed\n--- stdout ---\n%s\n--- stderr tail ---\n%s"
        % (completed.stdout, "\n".join(completed.stderr.splitlines()[-15:])),
    )
    test.assertIn(marker, completed.stdout)


class FileLockProbe:
    """Thin real-FileLock wrapper for bounded contention assertions."""

    def __init__(self, path):
        from filelock import FileLock

        self._lock = FileLock(path, mode=0o600)

    def acquire(self, timeout=None):
        self._lock.acquire(timeout=timeout)

    def release(self):
        self._lock.release()


class ResolveDataDirectoryTests(SimpleTestCase):
    """Pure-stdlib resolution: unspecified falls back, explicit is absolute."""

    def test_none_empty_and_whitespace_fall_back_to_base(self):
        base = Path("/data/base")
        for value in (None, "", "   ", "\t\n"):
            self.assertEqual(resolve_data_directory(base, value), base)

    def test_explicit_value_is_expanded_and_resolved_absolute(self):
        resolved = resolve_data_directory(Path("/data/base"), "~/marlin data")
        expected = Path("~/marlin data").expanduser().resolve()
        self.assertEqual(resolved, expected)
        self.assertTrue(resolved.is_absolute())
        self.assertIn("marlin data", str(resolved))

    def test_relative_value_resolves_absolute_without_changing_cwd(self):
        before = Path.cwd()
        resolved = resolve_data_directory(Path("/data/base"), "relative/user-root")
        self.assertTrue(resolved.is_absolute())
        self.assertEqual(Path.cwd(), before)

    def test_path_input_and_spaces_are_preserved(self):
        value = Path("/data") / "root with spaces"
        self.assertEqual(resolve_data_directory("/data/base", value), value.resolve())


class ModulePurityTests(SimpleTestCase):
    """resolve_data_directory and local_services must stay off the Django chain."""

    def test_runtime_paths_imports_without_django(self):
        completed = subprocess.run(
            [sys.executable, "-c", "import sys; import config.runtime_paths; "
             "print('PURE_OK' if 'django' not in sys.modules else 'IMPURE')"],
            cwd=str(REPO_ROOT),
            env=_probe_env(),
            capture_output=True,
            text=True,
            timeout=60,
        )
        _assert_probe_ok(self, completed, "PURE_OK")

    def test_local_services_imports_without_django(self):
        completed = subprocess.run(
            [sys.executable, "-c", "import sys; import scripts.local_services; "
             "print('PURE_OK' if 'django' not in sys.modules else 'IMPURE')"],
            cwd=str(REPO_ROOT),
            env=_probe_env(),
            capture_output=True,
            text=True,
            timeout=60,
        )
        _assert_probe_ok(self, completed, "PURE_OK")


class RuntimeHelpersFollowOverridesTests(SimpleTestCase):
    """Helpers resolve at call time: override_settings keeps steering writes."""

    def test_unspecified_app_data_dir_falls_back_to_current_base_dir(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(
            BASE_DIR=Path(tmp), APP_DATA_DIR=None
        ):
            self.assertEqual(app_data_root(), Path(tmp))
            self.assertEqual(
                runtime_cache_dir("model-rate-limits"),
                Path(tmp) / ".cache" / "model-rate-limits",
            )
            # No repository pollution from resolving paths.
            self.assertFalse((REPO_ROOT / ".cache" / "model-rate-limits").exists())

    def test_app_data_dir_wins_over_base_dir(self):
        with tempfile.TemporaryDirectory() as source_root, \
                tempfile.TemporaryDirectory() as user_root, \
                override_settings(BASE_DIR=Path(source_root), APP_DATA_DIR=Path(user_root)):
            self.assertEqual(app_data_root(), Path(user_root).resolve())
            self.assertEqual(
                runtime_cache_dir("eval-reports", "tenant"),
                Path(user_root).resolve() / ".cache" / "eval-reports" / "tenant",
            )
            self.assertFalse((Path(source_root) / ".cache").exists())

    def test_whitespace_app_data_dir_behaves_as_unspecified(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(
            BASE_DIR=Path(tmp), APP_DATA_DIR="   "
        ):
            self.assertEqual(app_data_root(), Path(tmp).resolve())


class UserRootRealWriteTests(SimpleTestCase):
    """Real helpers, real writes: every runtime artifact lands in the user root."""

    def test_model_rate_limit_lock_lands_in_user_root(self):
        from filelock import Timeout

        from .model_rate_limit import _bucket_lock

        key = f"d1-probe-{uuid.uuid4().hex}"
        with tempfile.TemporaryDirectory() as user_root, \
                override_settings(APP_DATA_DIR=Path(user_root)):
            with _bucket_lock(key):
                lock_path = Path(user_root) / ".cache" / "model-rate-limits" / f"{key}.lock"
                self.assertTrue(lock_path.is_file())
                if os.name == "posix":
                    self.assertEqual(stat.S_IMODE(lock_path.stat().st_mode) & 0o077, 0)
                # Real kernel-level lock at the user-root location.
                probe = FileLockProbe(lock_path)
                with self.assertRaises(Timeout):
                    probe.acquire(timeout=0)
                probe.release()
            self.assertFalse((REPO_ROOT / ".cache" / "model-rate-limits" / f"{key}.lock").exists())

    def test_eval_report_directory_lands_in_user_root(self):
        from .eval_reports import _open_report_directory, _open_report_path

        tenant = SimpleNamespace(id="tenant with space")
        report_id = f"d1-report-{uuid.uuid4().hex[:8]}"
        with tempfile.TemporaryDirectory() as user_root, \
                override_settings(APP_DATA_DIR=Path(user_root)):
            directory = _open_report_directory(tenant)
            self.assertEqual(
                directory, Path(user_root).resolve() / ".cache" / "eval-reports" / "tenant with space"
            )
            target = _open_report_path(tenant, report_id)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('{"report_id": "%s"}' % report_id, encoding="utf-8")
            self.assertTrue(target.is_file())
        self.assertFalse((REPO_ROOT / ".cache" / "eval-reports").exists())

    def test_dataset_cache_follows_user_root_but_manifests_stay_in_source(self):
        from .eval_dataset_registry import get_dataset_spec

        with tempfile.TemporaryDirectory() as user_root, \
                override_settings(APP_DATA_DIR=Path(user_root)):
            spec = get_dataset_spec("open_rag_benchmark", "arxiv-v1")
            self.assertTrue(spec.cache_path.is_relative_to(Path(user_root).resolve()))
            self.assertTrue(
                spec.manifest_path.is_relative_to(REPO_ROOT / "personal_knowledge_base" / "eval_datasets")
            )
            self.assertTrue(spec.manifest_path.is_file())


class OpenRagCheckpointCleanupUserRootTests(TransactionTestCase):
    """R2A 后 cleanup 带 DB 终态守卫：本用例需要真实隔离 DB（原为
    SimpleTestCase 夹具，Codex 批准的最小契约适配）。全部 D1 路径断言保留：
    只扫用户根、源目录过期副本不删、fresh 文件保留。"""

    def test_open_rag_checkpoint_write_read_cleanup_stay_in_user_root(self):
        from .models import TaskRecord
        from .tasks import _cleanup_open_rag_checkpoints, _open_rag_checkpoint_path, \
            _read_open_rag_checkpoint, _write_open_rag_checkpoint

        tenant_id = f"d1-tenant-{uuid.uuid4().hex[:8]}"
        task_id = f"d1-task-{uuid.uuid4().hex[:8]}"
        with tempfile.TemporaryDirectory() as source_root, \
                tempfile.TemporaryDirectory() as user_root, \
                override_settings(BASE_DIR=Path(source_root), APP_DATA_DIR=Path(user_root)):
            _write_open_rag_checkpoint(tenant_id, task_id, {"stage": "judge", "done": 7})
            expected = Path(user_root) / ".cache" / "open-rag-runs" / tenant_id / f"{task_id}.json"
            self.assertEqual(_open_rag_checkpoint_path(tenant_id, task_id), expected)
            self.assertTrue(expected.is_file())
            self.assertEqual(_read_open_rag_checkpoint(tenant_id, task_id), {"stage": "judge", "done": 7})
            self.assertFalse((Path(source_root) / ".cache").exists())

            # Cleanup scans only the user root: the expired copy planted under
            # the (read-only) source root must survive, the fresh one too.
            # R2A 保守守卫：过期且待删除的文件必须有已终结的 TaskRecord。
            terminated = TaskRecord.objects.create(
                id="stale",
                task_type="open_rag_evaluation",
                status="completed",
                payload={"tenant_id": tenant_id},
            )
            stale = expected.parent / "stale.json"
            stale.write_text("{}", encoding="utf-8")
            os.utime(stale, (time.time() - 8 * 24 * 3600, time.time() - 8 * 24 * 3600))
            source_stale = Path(source_root) / ".cache" / "open-rag-runs" / tenant_id / "stale.json"
            source_stale.parent.mkdir(parents=True, exist_ok=True)
            source_stale.write_text("{}", encoding="utf-8")
            os.utime(source_stale, (time.time() - 8 * 24 * 3600, time.time() - 8 * 24 * 3600))
            _cleanup_open_rag_checkpoints()
            self.assertFalse(stale.exists())
            self.assertTrue(expected.is_file())
            self.assertTrue(source_stale.exists())
            self.assertTrue(TaskRecord.objects.filter(id=terminated.id, status="completed").exists())


class SourceResourcesStayAnchoredTests(SimpleTestCase):
    """Source-side resources never move to the user data root."""

    def test_templates_and_frontend_dist_remain_source_anchored(self):
        from django.conf import settings

        dirs = settings.TEMPLATES[0]["DIRS"]
        self.assertEqual(Path(dirs[0]), REPO_ROOT / "templates")
        self.assertEqual(Path(dirs[1]), REPO_ROOT / "frontend" / "dist")
        if settings.STATICFILES_DIRS:
            self.assertEqual(
                Path(settings.STATICFILES_DIRS[0]), REPO_ROOT / "frontend" / "dist" / "assets"
            )


class LangfuseDataRootTests(SimpleTestCase):
    """ensure_langfuse takes APP_DATA_DIR from the resolved local env."""

    _HEALTHY_ENV = {
        "LANGFUSE_AUTOSTART": "true",
        "LANGFUSE_STARTUP_TIMEOUT_SECONDS": "10",
        "LANGFUSE_BASE_URL": "http://localhost:3000",
    }

    def _healthy_state(self, source_root):
        with mock.patch("scripts.local_services.subprocess.run",
                        return_value=SimpleNamespace(returncode=0)), \
                mock.patch("scripts.local_services.build_opener") as opener:
            opener.return_value.open.return_value.__enter__.return_value.status = 200
            from scripts.local_services import ensure_langfuse

            return ensure_langfuse(source_root)

    def test_app_data_dir_redirects_startup_state(self):
        with tempfile.TemporaryDirectory() as source_root, \
                tempfile.TemporaryDirectory() as user_root, \
                mock.patch.dict(os.environ, {**self._HEALTHY_ENV, "APP_DATA_DIR": str(user_root)}):
            Path(source_root, ".env.langfuse").touch()
            state = self._healthy_state(source_root)
            self.assertEqual(state["state"], "healthy")
            self.assertTrue(Path(user_root, ".cache", "langfuse", "startup.json").is_file())
            self.assertFalse(Path(source_root, ".cache").exists())

    def test_unset_and_empty_app_data_dir_keep_source_root_behavior(self):
        for app_data_dir in (None, ""):
            with self.subTest(app_data_dir=app_data_dir), \
                    tempfile.TemporaryDirectory() as source_root, \
                    tempfile.TemporaryDirectory() as user_root, \
                    mock.patch.dict(os.environ, self._HEALTHY_ENV):
                if app_data_dir is None:
                    os.environ.pop("APP_DATA_DIR", None)
                else:
                    os.environ["APP_DATA_DIR"] = app_data_dir
                Path(source_root, ".env.langfuse").touch()
                state = self._healthy_state(source_root)
                self.assertEqual(state["state"], "healthy")
                self.assertTrue(Path(source_root, ".cache", "langfuse", "startup.json").is_file())
                self.assertFalse(Path(user_root, ".cache").exists())


class SettingsDataRootTests(SimpleTestCase):
    """Settings-level routing, verified in isolated subprocesses."""

    def test_explicit_django_db_path_wins_over_app_data_dir(self):
        with tempfile.TemporaryDirectory() as scratch:
            db_path = Path(scratch) / "explicit.sqlite3"
            app_data_dir = Path(scratch) / "user data root"
            completed = _run_settings_probe(
                _SETTINGS_PROBE_PREFIX + r"""
from pathlib import Path
scratch = Path(sys.argv[2])
name = settings.DATABASES["default"]["NAME"]
assert str(name) == str(scratch / "explicit.sqlite3"), name
print("PROBE_OK")
""",
                scratch=scratch,
                DJANGO_DB_PATH=str(db_path),
                APP_DATA_DIR=str(app_data_dir),
            )
            _assert_probe_ok(self, completed, "PROBE_OK")

    def test_app_data_dir_routes_db_media_and_static(self):
        with tempfile.TemporaryDirectory() as scratch:
            app_data_dir = Path(scratch) / "user data root"
            completed = _run_settings_probe(
                _SETTINGS_PROBE_PREFIX + r"""
from pathlib import Path
scratch = Path(sys.argv[2])
expected_root = Path(scratch / "user data root").expanduser().resolve()
assert settings.APP_DATA_DIR == expected_root, settings.APP_DATA_DIR
assert settings.APP_DATA_DIR.is_absolute()
assert str(settings.DATABASES["default"]["NAME"]) == str(expected_root / "db.sqlite3")
assert Path(settings.MEDIA_ROOT) == expected_root / "media"
assert Path(settings.STATIC_ROOT) == expected_root / "staticfiles"
print("PROBE_OK")
""",
                scratch=scratch,
                APP_DATA_DIR=str(app_data_dir),
            )
            _assert_probe_ok(self, completed, "PROBE_OK")

    def test_unset_app_data_dir_keeps_historical_defaults(self):
        completed = _run_settings_probe(
            _SETTINGS_PROBE_PREFIX + r"""
from pathlib import Path
repo = Path(sys.argv[1])
assert settings.APP_DATA_DIR is None
assert str(settings.DATABASES["default"]["NAME"]) == str(repo / "db.sqlite3")
assert Path(settings.MEDIA_ROOT) == repo / "media"
assert Path(settings.STATIC_ROOT) == repo / "staticfiles"
print("PROBE_OK")
""",
        )
        _assert_probe_ok(self, completed, "PROBE_OK")

    def test_whitespace_app_data_dir_is_unspecified(self):
        completed = _run_settings_probe(
            _SETTINGS_PROBE_PREFIX + r"""
from pathlib import Path
repo = Path(sys.argv[1])
assert settings.APP_DATA_DIR is None, settings.APP_DATA_DIR
assert str(settings.DATABASES["default"]["NAME"]) == str(repo / "db.sqlite3")
print("PROBE_OK")
""",
            APP_DATA_DIR="   ",
        )
        _assert_probe_ok(self, completed, "PROBE_OK")


class ProductionFailclosedTests(SimpleTestCase):
    """DEBUG=false with no secret must still refuse to configure settings."""

    def test_missing_secret_in_production_is_rejected_with_contract_message(self):
        # DJANGO_SECRET_KEY is set but empty: "no secret" that a repo .env
        # cannot override (load_dotenv skips existing keys), keeping the
        # probe deterministic on every acceptance machine.
        completed = _run_settings_probe(
            r"""
import sys

import django
from django.conf import settings

try:
    settings._setup()
except ValueError as error:
    print("FAILCLOSED_OK:", error)
    raise SystemExit(0)
raise SystemExit("settings configured without a secret in production mode")
""",
            DJANGO_DEBUG="false",
            DJANGO_SECRET_KEY="",
        )
        _assert_probe_ok(self, completed, "FAILCLOSED_OK")

    def test_allow_auto_setup_defaults_to_false(self):
        env = _probe_env()
        env.pop("ALLOW_AUTO_SETUP", None)
        completed = subprocess.run(
            [sys.executable, "-c", _SETTINGS_PROBE_PREFIX + r"""
assert settings.ALLOW_AUTO_SETUP is False, settings.ALLOW_AUTO_SETUP
print("PROBE_OK")
""", str(REPO_ROOT)],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        _assert_probe_ok(self, completed, "PROBE_OK")
