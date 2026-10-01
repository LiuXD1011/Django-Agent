"""MARLIN-D2 desktop runtime regression tests.

Scope: the minimal desktop entry (``scripts/start_desktop.py``) and the
desktop WSGI boundary (``config/desktop_wsgi.py``). The suite stays
``SimpleTestCase`` (no Django test database): every database-backed flow
runs against REAL subprocesses and a REAL temporary SQLite file, and every
HTTP assertion is made over a real socket (Waitress child, decoy HTTP
servers) or a real in-process WSGI call.

Isolation contract (mirrors ``accounts/test_auto_setup_processes.py``):

- Child environments are rebuilt from a whitelist; real working data,
  credentials and external services are never read or written.
- Desktop data directories, secrets and databases live in OS temp dirs
  (names deliberately avoid the substring "test": ``settings.APP_TASKS_SYNC``
  is keyed on ``"test" in sys.argv`` and the CLI passes ``--data-dir``
  through argv).
- The source repository is only ever READ: assets are served from the
  source-root dist and the E2E run asserts the tree is unchanged.
- Subprocesses are spawned inside try/finally cleanup guards and are always
  terminate→wait→killed within bounded grace before temp dirs are removed.
"""

import json
import os
import queue
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import closing, redirect_stdout, redirect_stderr
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import StringIO
from pathlib import Path
from unittest import skipUnless
from unittest import mock
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
import wsgiref.util

from django.conf import settings
from django.test import SimpleTestCase

REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    import waitress  # noqa: F401
    import whitenoise  # noqa: F401

    DESKTOP_DEPS_INSTALLED = True
except ImportError:
    DESKTOP_DEPS_INSTALLED = False

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
    "NEO4J_ENABLE": "false",
    "LANGFUSE_ENABLED": "false",
    "LANGFUSE_AUTOSTART": "false",
    "DJANGO_ALLOWED_HOSTS": "127.0.0.1,localhost",
}

_MIGRATE_TIMEOUT_SECONDS = 600
_GRACE_SECONDS = 10


def _isolated_env(**overrides):
    env = {key: os.environ[key] for key in _BASE_ENV_KEYS if key in os.environ}
    env.update(_ISOLATED_SETTINGS_ENV)
    env.update(overrides)
    return env


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _http(method, url, *, headers=None, timeout=10):
    """Real HTTP with system proxies disabled; error statuses are returned
    (not raised) so rejection assertions can inspect them."""
    opener = build_opener(ProxyHandler({}))
    request = Request(url, method=method, headers=headers or {}, data=b"{}" if method == "POST" else None)
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read()
    except HTTPError as error:
        with error:
            return error.code, dict(error.headers), error.read()


def _port_refuses(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _port_eventually_refuses(port, timeout=3.0, interval=0.1):
    """Bounded conditional poll for port release. Windows makes a closed
    listening port's refusal observable only after a short delay (measured:
    still connectable immediately after exit, refused ~100ms later), so a
    single instant check would be a false negative — never a fixed sleep
    pretending success: the final refusal is still asserted by the caller."""
    deadline = time.monotonic() + timeout
    while True:
        if _port_refuses(port):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(interval, remaining))


def _readline_bounded(stream, timeout, what):
    """First line from ``stream`` with a REAL timeout: a plain
    ``stream.readline()`` blocks forever when the child never speaks."""
    lines = queue.Queue()

    def pump():
        lines.put(stream.readline())

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        return lines.get(timeout=timeout)
    except queue.Empty:
        raise AssertionError("child printed no %r line within %.0fs" % (what, timeout))


def _drain_lines(lines, sink):
    while True:
        try:
            item = lines.get_nowait()
        except queue.Empty:
            return
        if item is not None:
            sink.append(item)


class _DecoyServer:
    """Real localhost HTTP server that answers 200 with chosen headers."""

    def __init__(self, headers=None):
        outer = self
        self.headers = headers or {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                for key, value in outer.headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", "5")
                self.end_headers()
                self.wfile.write(b"decoy")

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()


def _make_fake_dist(root: Path) -> Path:
    """A minimal built-frontend tree under ``root`` (never the repository)."""
    dist = root / "frontend" / "dist"
    (dist / "assets").mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text(
        '<!doctype html><html><head>'
        '<script type="module" src="/assets/app.fake.js"></script>'
        '<link rel="stylesheet" href="/assets/app.fake.css">'
        '</head><body><div id="app"></div></body></html>',
        encoding="utf-8",
    )
    (dist / "assets" / "app.fake.js").write_text("console.log('fake');", encoding="utf-8")
    (dist / "assets" / "app.fake.css").write_text("body{color:red}", encoding="utf-8")
    return dist


def _call_wsgi(app, method, path, *, host="127.0.0.1:8899", origin=None):
    environ = {}
    wsgiref.util.setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = method
    environ["PATH_INFO"] = path
    environ["HTTP_HOST"] = host
    if origin is not None:
        environ["HTTP_ORIGIN"] = origin
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = {key.lower(): value for key, value in headers}

    body = b"".join(app(environ, start_response))
    return captured["status"], captured["headers"], body


@skipUnless(DESKTOP_DEPS_INSTALLED, "waitress/whitenoise are not installed")
class DesktopWsgiBoundaryTests(SimpleTestCase):
    """In-process real WSGI calls against the desktop stack (no DB touched:
    every asserted path here either never reaches Django or hits views that
    are DB-free by design)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory(prefix="desktop-d2-wsgi-")
        cls.fake_dist = _make_fake_dist(Path(cls._tmp.name))
        from config import desktop_wsgi

        cls.desktop_wsgi = desktop_wsgi
        cls.app = desktop_wsgi.build_application(
            instance_id="boundary-fixed-instance", source_root=Path(cls._tmp.name)
        )
        cls._env_patch = mock.patch.dict(os.environ, {"MARLIN_DESKTOP_PORT": "8899"})
        cls._env_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls._env_patch.stop()
        cls._tmp.cleanup()
        super().tearDownClass()

    def test_assets_served_with_correct_mime_and_instance_header(self):
        for asset, expected_type in (
            ("/assets/app.fake.js", "text/javascript"),
            ("/assets/app.fake.css", "text/css"),
        ):
            status, headers, body = _call_wsgi(self.app, "GET", asset)
            self.assertEqual(status, "200 OK", asset)
            self.assertTrue(headers["content-type"].startswith(expected_type), headers)
            self.assertEqual(
                headers["x-marlin-desktop-instance"], "boundary-fixed-instance"
            )
            self.assertTrue(body)

    def test_asset_traversal_is_not_served(self):
        status, _headers, body = _call_wsgi(self.app, "GET", "/assets/../secret.key")
        self.assertNotEqual(status, "200 OK")
        self.assertNotIn(b"fake", body)

    def test_root_and_deep_links_serve_index_html(self):
        dirs = [Path(d) for d in settings.TEMPLATES[0]["DIRS"]]
        if not any((d / "index.html").is_file() for d in dirs):
            self.skipTest("no built index.html available for the SPA template")
        for path in ("/", "/deep/link/path"):
            status, headers, body = _call_wsgi(self.app, "GET", path)
            self.assertEqual(status, "200 OK", path)
            self.assertTrue(headers["content-type"].startswith("text/html"), headers)
            self.assertIn(b'id="app"', body)

    def test_health_carries_instance_header(self):
        status, headers, body = _call_wsgi(self.app, "GET", "/health")
        self.assertEqual(status, "200 OK")
        self.assertEqual(headers["x-marlin-desktop-instance"], "boundary-fixed-instance")
        self.assertIn(b'"status": "ok"', body)

    def test_auto_setup_rejects_non_post(self):
        for method in ("GET", "HEAD", "PUT", "DELETE"):
            status, headers, body = _call_wsgi(
                self.app, method, "/api/v1/auth/auto-setup", origin="http://127.0.0.1:8899"
            )
            self.assertEqual(status, "405 Method Not Allowed", method)
            payload = json.loads(body)
            self.assertFalse(payload["success"])
            self.assertEqual(payload["error"]["code"], "method_not_allowed")
            self.assertEqual(headers.get("cache-control"), "no-store")

    def test_cross_origin_and_null_origin_writes_rejected(self):
        for origin in ("https://evil.example", "null", "http://127.0.0.1:9999", "ftp://127.0.0.1:8899"):
            status, _headers, body = _call_wsgi(
                self.app, "POST", "/api/v1/auth/auto-setup", origin=origin
            )
            self.assertEqual(status, "403 Forbidden", origin)
            payload = json.loads(body)
            self.assertEqual(payload["error"]["code"], "cross_origin_write_rejected")

    def test_same_origin_write_passes_boundary_into_django(self):
        # auth_logout is csrf_exempt and DB-free without a Bearer header, so a
        # 200 proves the wrapper let a legal same-origin write through.
        status, _headers, body = _call_wsgi(
            self.app, "POST", "/api/v1/auth/logout", origin="http://127.0.0.1:8899"
        )
        self.assertEqual(status, "200 OK")
        self.assertTrue(json.loads(body)["success"])

    def test_cli_write_without_origin_allowed(self):
        status, _headers, body = _call_wsgi(self.app, "POST", "/api/v1/auth/logout")
        self.assertEqual(status, "200 OK")
        self.assertTrue(json.loads(body)["success"])

    def test_auth_responses_are_no_store(self):
        status, headers, _body = _call_wsgi(self.app, "GET", "/api/v1/auth/config")
        self.assertEqual(status, "200 OK")
        self.assertEqual(headers.get("cache-control"), "no-store")
        _status, health_headers, _b = _call_wsgi(self.app, "GET", "/health")
        self.assertNotEqual(health_headers.get("cache-control"), "no-store")

    def test_same_origin_http_port_normalization(self):
        # http's implicit :80 and an explicit :80 are the same effective port
        # — but only when the bound desktop port really is 80. Implicit-80
        # origins against any other bound port stay rejected.
        with mock.patch.dict(os.environ, {"MARLIN_DESKTOP_PORT": "80"}):
            host = {"HTTP_HOST": "127.0.0.1"}
            self.assertTrue(self.desktop_wsgi._same_origin(host, "http://127.0.0.1"))
            self.assertTrue(self.desktop_wsgi._same_origin(host, "http://127.0.0.1:80"))
            self.assertFalse(self.desktop_wsgi._same_origin(host, "http://127.0.0.1:8899"))
        with mock.patch.dict(os.environ, {"MARLIN_DESKTOP_PORT": "8899"}):
            bound = {"HTTP_HOST": "127.0.0.1:8899"}
            self.assertTrue(self.desktop_wsgi._same_origin(bound, "http://127.0.0.1:8899"))
            self.assertFalse(
                self.desktop_wsgi._same_origin(bound, "http://127.0.0.1"),
                "implicit :80 must not match a bound 8899",
            )
            self.assertFalse(
                self.desktop_wsgi._same_origin(bound, "http://evil@127.0.0.1:8899"),
                "userinfo tricks must stay rejected",
            )
            self.assertFalse(
                self.desktop_wsgi._same_origin(bound, "http://127.0.0.1:notaport"),
                "malformed ports must stay rejected",
            )

    def test_loopback_aliases_are_distinct_origins(self):
        # Sharing the loopback range is NOT enough: the origin hostname must
        # EQUAL the Host hostname (case-normalized), so one loopback alias can
        # never impersonate another in either direction.
        with mock.patch.dict(os.environ, {"MARLIN_DESKTOP_PORT": "8899"}):
            self.assertFalse(
                self.desktop_wsgi._same_origin(
                    {"HTTP_HOST": "127.0.0.1:8899"}, "http://localhost:8899"
                ),
                "localhost must not impersonate the 127.0.0.1 Host",
            )
            self.assertFalse(
                self.desktop_wsgi._same_origin(
                    {"HTTP_HOST": "localhost:8899"}, "http://127.0.0.1:8899"
                ),
                "127.0.0.1 must not impersonate the localhost Host",
            )
            self.assertTrue(
                self.desktop_wsgi._same_origin(
                    {"HTTP_HOST": "LOCALHOST:8899"}, "http://localhost:8899"
                ),
                "hostname comparison must be case-normalized",
            )

    def test_host_outside_allowlist_rejected(self):
        status, _headers, _body = _call_wsgi(
            self.app, "GET", "/health", host="evil.example"
        )
        self.assertEqual(status, "400 Bad Request")

    def test_module_import_does_not_require_built_dist(self):
        # The lazy module-level application must only build on access.
        with tempfile.TemporaryDirectory(prefix="desktop-d2-empty-") as empty:
            with self.assertRaises(RuntimeError) as ctx:
                self.desktop_wsgi.build_application(source_root=Path(empty))
            self.assertIn("npm run build", str(ctx.exception))


class DesktopEntryUnitTests(SimpleTestCase):
    """Pure helpers of the desktop entry plus secret/lock file semantics."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from scripts import start_desktop

        cls.entry = start_desktop

    def test_default_data_dir_windows_uses_localappdata(self):
        result = self.entry.default_data_dir(
            "win32", {"LOCALAPPDATA": os.path.join("C:", "Users", "u", "AppData", "Local")}
        )
        self.assertEqual(result, Path("C:") / "Users" / "u" / "AppData" / "Local" / "Marlin")
        with self.assertRaises(self.entry.DesktopError) as ctx:
            self.entry.default_data_dir("win32", {})
        self.assertEqual(ctx.exception.exit_code, self.entry.EXIT_USAGE)

    def test_default_data_dir_linux_uses_xdg_or_home(self):
        self.assertEqual(
            self.entry.default_data_dir("linux", {"XDG_DATA_HOME": "/custom/data"}),
            Path("/custom/data") / "marlin",
        )
        expected = Path.home() / ".local" / "share" / "marlin"
        self.assertEqual(self.entry.default_data_dir("linux", {}), expected)

    def test_port_validation_range(self):
        self.assertEqual(self.entry.validate_port("8899"), 8899)
        self.assertEqual(self.entry.validate_port(1), 1)
        self.assertEqual(self.entry.validate_port(65535), 65535)
        for bad in ("0", "65536", "-1", "abc", None):
            with self.assertRaises(self.entry.DesktopError) as ctx:
                self.entry.validate_port(bad)
            self.assertEqual(ctx.exception.exit_code, self.entry.EXIT_USAGE)

    def test_missing_dist_fails_before_any_side_effect(self):
        with tempfile.TemporaryDirectory(prefix="desktop-d2-src-") as src, \
                tempfile.TemporaryDirectory(prefix="desktop-d2-data-") as data:
            output = StringIO()
            with redirect_stdout(output), redirect_stderr(output):
                code = self.entry.run_desktop(
                    data_dir=data, port=_free_port(), source_root=Path(src), open_browser=False
                )
            self.assertEqual(code, self.entry.EXIT_USAGE)
            self.assertIn("npm run build", output.getvalue())
            self.assertFalse((Path(data) / "secret.key").exists())
            self.assertFalse((Path(data) / "instance.lock").exists())

    def test_secret_persists_across_restart_and_is_never_printed(self):
        with tempfile.TemporaryDirectory(prefix="desktop-d2 secret dir") as data:
            output = StringIO()
            with redirect_stdout(output), redirect_stderr(output):
                first = self.entry.ensure_secret(Path(data))
                second = self.entry.ensure_secret(Path(data))
            self.assertTrue(first)
            self.assertEqual(first, second, "secret must survive a restart")
            path = Path(data) / "secret.key"
            self.assertEqual(path.read_text(encoding="utf-8"), first)
            self.assertEqual(output.getvalue(), "", "secret value must not be printed")
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_existing_empty_secret_refused_not_replaced(self):
        with tempfile.TemporaryDirectory(prefix="desktop-d2-data-") as data:
            path = Path(data) / "secret.key"
            path.write_text("", encoding="utf-8")
            with self.assertRaises(self.entry.DesktopError) as ctx:
                self.entry.ensure_secret(Path(data))
            self.assertEqual(ctx.exception.exit_code, self.entry.EXIT_SECRET)
            self.assertEqual(path.read_text(encoding="utf-8"), "")

    def test_double_instance_rejected_across_processes(self):
        with tempfile.TemporaryDirectory(prefix="desktop-d2-data-") as data, \
                tempfile.TemporaryDirectory(prefix="desktop-d2-holder-") as holder:
            lock_path = Path(data) / "instance.lock"
            holder_proc = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    # The FileLock MUST stay bound: an unreferenced temporary
                    # is garbage-collected and its lock silently released.
                    "from filelock import FileLock\n"
                    "import os, time\n"
                    "lock = FileLock(os.environ['HOLDER_LOCK'], mode=0o600)\n"
                    "lock.acquire(timeout=5)\n"
                    "print('held', flush=True)\n"
                    "time.sleep(30)",
                ],
                env=_isolated_env(HOLDER_LOCK=str(lock_path)),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            try:
                self.assertEqual(
                    _readline_bounded(holder_proc.stdout, 60, "held").strip(), "held"
                )
                output = StringIO()
                with redirect_stdout(output), redirect_stderr(output):
                    code = self.entry.run_desktop(
                        data_dir=data, port=_free_port(), open_browser=False, startup_timeout=5
                    )
                self.assertEqual(code, self.entry.EXIT_INSTANCE_BUSY)
                self.assertIn("another desktop instance", output.getvalue())
                self.assertFalse((Path(data) / "secret.key").exists())
            finally:
                holder_proc.terminate()
                try:
                    holder_proc.wait(timeout=_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    holder_proc.kill()
                    holder_proc.wait(timeout=_GRACE_SECONDS)


    def test_desktop_child_env_contract(self):
        # Compare via str(Path(...)) so the assertion holds on both POSIX and
        # Windows separators while still pinning the REAL values carried into
        # the child environment (never a loosened assertion).
        data_dir = Path("/data dir")
        env = self.entry.build_desktop_env(
            data_dir,
            data_dir / "db.sqlite3",
            "unit-secret-value",
            8899,
            "instance-1",
            base_env={
                "NEO4J_ENABLE": "true",  # explicit user opt-in is preserved
                "LANGFUSE_ENABLED": "true",  # explicit user opt-in is preserved
                "PATH": "/usr/bin",
            },
        )
        self.assertEqual(env["DJANGO_DEBUG"], "false")
        self.assertEqual(env["DJANGO_ALLOWED_HOSTS"], "127.0.0.1,localhost")
        self.assertEqual(env["DJANGO_SECRET_KEY"], "unit-secret-value")
        self.assertEqual(env["APP_DATA_DIR"], str(data_dir))
        self.assertEqual(env["DJANGO_DB_PATH"], str(data_dir / "db.sqlite3"))
        self.assertEqual(env["LANGFUSE_AUTOSTART"], "false")
        self.assertEqual(env["ALLOW_AUTO_SETUP"], "true")
        self.assertEqual(env["NEO4J_ENABLE"], "true")
        self.assertEqual(env["LANGFUSE_ENABLED"], "true")
        self.assertEqual(env["MARLIN_DESKTOP_PORT"], "8899")
        self.assertEqual(env["MARLIN_DESKTOP_INSTANCE"], "instance-1")

        defaults = self.entry.build_desktop_env(
            Path("/d"), Path("/d/db.sqlite3"), "s", 1, "i", base_env={}
        )
        # Without an explicit opt-in the integrations stay disabled, and the
        # keys are ALWAYS present so repo .env cannot re-enable them
        # (settings' load_dotenv only fills absent keys).
        self.assertEqual(defaults["NEO4J_ENABLE"], "false")
        self.assertEqual(defaults["LANGFUSE_ENABLED"], "false")
        self.assertEqual(defaults["LANGFUSE_AUTOSTART"], "false")


class DesktopOrchestrationTests(SimpleTestCase):
    """Real subprocess orchestration: failures must abort the whole group,
    reclaim children and release the instance lock."""

    _STUB_OK = [sys.executable, "-c", "import sys; sys.exit(0)"]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from scripts import start_desktop as entry_module

        cls.entry = entry_module

    def _run_group(self, data_dir, port, **overrides):
        """run_desktop with console output captured and a whitelist base env."""
        output = StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            code = self.entry.run_desktop(
                data_dir=data_dir,
                port=port,
                open_browser=False,
                base_env=_isolated_env(),
                child_stdout=subprocess.DEVNULL,
                child_stderr=subprocess.DEVNULL,
                **overrides,
            )
        return code, output.getvalue()

    def _lock_is_free(self, data_dir):
        lock = self.entry.InstanceLock(Path(data_dir))
        lock.acquire()
        lock.release()

    def _migrate_child(self, data_dir, env, db_path=None):
        argv = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "start_desktop.py"),
            "_migrate",
            "--data-dir",
            str(data_dir),
        ]
        child_env = self.entry.build_desktop_env(
            Path(data_dir), Path(data_dir) / "db.sqlite3", "unit-secret", 1, "unit", env
        )
        if db_path is not None:
            child_env["DJANGO_DB_PATH"] = str(db_path)
        return subprocess.run(
            argv,
            cwd=str(REPO_ROOT),
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_MIGRATE_TIMEOUT_SECONDS,
        )

    def test_real_migrate_child_success_and_backup_once(self):
        with tempfile.TemporaryDirectory(prefix="desktop-d2-data-") as raw:
            data_dir = Path(raw) / "data dir"
            data_dir.mkdir(parents=True)  # the real entry creates it via the lock
            env = _isolated_env()

            # Phase 1: fresh database — no backup, migrations applied.
            result = self._migrate_child(data_dir, env)
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            backups = data_dir / "backups"
            self.assertEqual(list(backups.glob("*.sqlite3")) if backups.exists() else [], [])

            # Phase 2: REALLY roll one migration back (backward SQL drops the
            # objects — deleting the django_migrations row alone would make
            # the re-apply crash on still-existing tables), so the desktop
            # migrate child sees a genuine existing-db-with-pending state.
            # closing() actually closes the connection (plain `with` only
            # manages transactions) — an open handle makes the Windows
            # TemporaryDirectory cleanup fail with WinError 32.
            with closing(sqlite3.connect(str(data_dir / "db.sqlite3"))) as connection:
                marker_row = connection.execute(
                    "SELECT app, name FROM django_migrations WHERE app='sessions'"
                ).fetchone()
            self.assertEqual(marker_row, ("sessions", "0001_initial"))
            child_env = self.entry.build_desktop_env(
                data_dir, data_dir / "db.sqlite3", "unit-secret", 1, "unit", env
            )
            rollback = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "manage.py"),
                    "migrate",
                    "sessions",
                    "zero",
                ],
                cwd=str(REPO_ROOT),
                env=child_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=_MIGRATE_TIMEOUT_SECONDS,
            )
            self.assertEqual(rollback.returncode, 0, rollback.stderr[-2000:])
            result = self._migrate_child(data_dir, env)
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            self.assertIn('"backup"', result.stdout)
            backup_files = list((data_dir / "backups").glob("*.sqlite3"))
            self.assertEqual(len(backup_files), 1, backup_files)
            with closing(sqlite3.connect(str(backup_files[0]))) as connection:
                applied = connection.execute(
                    "SELECT COUNT(*) FROM django_migrations"
                ).fetchone()[0]
                # The snapshot must be the PRE-migration state, i.e. a real
                # restore point: the rolled-back session migration row is
                # absent from the backup but present in the live database.
                backup_has_marker = connection.execute(
                    "SELECT COUNT(*) FROM django_migrations WHERE app=? AND name=?",
                    marker_row,
                ).fetchone()[0]
            self.assertGreater(applied, 0, "backup must be a valid pre-migration snapshot")
            self.assertEqual(
                backup_has_marker, 0, "backup must hold the rolled-back pre-migrate state"
            )
            with closing(sqlite3.connect(str(data_dir / "db.sqlite3"))) as connection:
                live_has_marker = connection.execute(
                    "SELECT COUNT(*) FROM django_migrations WHERE app=? AND name=?",
                    marker_row,
                ).fetchone()[0]
            self.assertEqual(live_has_marker, 1, "re-applied on the live db, original untouched")
            self.assertTrue((data_dir / "db.sqlite3").exists(), "original db must not be moved")

            # Phase 3: nothing pending — no additional backup.
            result = self._migrate_child(data_dir, env)
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            self.assertEqual(len(list((data_dir / "backups").glob("*.sqlite3"))), 1)

    def test_garbage_db_migrate_fails_and_aborts_group(self):
        with tempfile.TemporaryDirectory(prefix="desktop-d2-data-") as data:
            # The garbage bytes go to the REAL desktop database the entry
            # computes itself (data_dir/db.sqlite3). Smuggling a junk path
            # through the child env would be overwritten by
            # build_desktop_env — the run would then start normally and hang.
            (Path(data) / "db.sqlite3").write_bytes(
                b"this is not a sqlite database at all"
            )
            result = self._migrate_child(data, _isolated_env())
            self.assertNotEqual(result.returncode, 0)

            port = _free_port()
            code, output = self._run_group(data, port, startup_timeout=10)
            self.assertEqual(code, self.entry.EXIT_MIGRATE)
            self.assertIn("migration failed", output)
            self.assertTrue(_port_refuses(port), "web must never start after migrate failure")
            self._lock_is_free(data)

    def test_port_occupied_aborts_group_and_reclaims_children(self):
        with tempfile.TemporaryDirectory(prefix="desktop-d2-data-") as data:
            port = _free_port()
            blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            blocker.bind(("127.0.0.1", port))
            blocker.listen(1)
            try:
                started = time.monotonic()
                code, output = self._run_group(
                    data, port, startup_timeout=60, migrate_argv=self._STUB_OK
                )
                elapsed = time.monotonic() - started
                self.assertEqual(code, self.entry.EXIT_STARTUP)
                # The web child cannot bind, so the group must fail through the
                # early-exit detection (not the overall startup timeout).
                self.assertIn("exited early", output, output)
                self.assertLess(elapsed, 60)
                self._lock_is_free(data)
            finally:
                blocker.close()

    def test_decoy_health_without_instance_header_never_passes(self):
        with _DecoyServer() as decoy, tempfile.TemporaryDirectory(prefix="desktop-d2-data-") as data:
            deadline = time.monotonic() + 2
            self.assertFalse(
                self.entry.probe_health(decoy.port, "our-instance", deadline)
            )
            with _DecoyServer(headers={"X-Marlin-Desktop-Instance": "our-instance"}) as twin:
                deadline = time.monotonic() + 2
                self.assertTrue(self.entry.probe_health(twin.port, "our-instance", deadline))

            with _DecoyServer() as occupant:
                code, output = self._run_group(
                    data,
                    occupant.port,
                    startup_timeout=3,
                    migrate_argv=self._STUB_OK,
                    web_argv=[sys.executable, "-c", "import time; time.sleep(60)"],
                    worker_argv=[sys.executable, "-c", "import time; time.sleep(60)"],
                )
            self.assertEqual(code, self.entry.EXIT_STARTUP)
            self.assertIn("startup timeout", output)
            self._lock_is_free(data)

    def test_worker_early_exit_fails_whole_group(self):
        with tempfile.TemporaryDirectory(prefix="desktop-d2-data-") as data:
            port = _free_port()
            started = time.monotonic()
            code, output = self._run_group(
                data,
                port,
                startup_timeout=45,
                migrate_argv=self._STUB_OK,
                worker_argv=[
                    sys.executable,
                    "-c",
                    "import time; time.sleep(0.5); import sys; sys.exit(3)",
                ],
            )
            elapsed = time.monotonic() - started
            self.assertEqual(code, self.entry.EXIT_STARTUP)
            self.assertLess(elapsed, 30)
            # Depending on whether the web child became healthy before the
            # worker died, the failure is reported either as an early exit
            # during startup or by the running loop — both must be present.
            self.assertRegex(output, r"worker exited (early|unexpectedly)")
            # Windows makes a closed listener's refusal observable only after
            # a short delay (independent probe: connectable immediately after
            # exit, refused ~100ms later; CIM confirmed no leaked processes).
            # Poll within a hard deadline — the refusal itself is still the
            # asserted outcome, and run_desktop's EXIT_STARTUP plus the exit
            # message above are the returncode/wait evidence for the group.
            self.assertTrue(
                _port_eventually_refuses(port, 3.0),
                "web must be reclaimed when the worker exits early",
            )
            self._lock_is_free(data)

    def test_startup_timeout_stops_sleeper_children(self):
        with tempfile.TemporaryDirectory(prefix="desktop-d2-data-") as data:
            port = _free_port()
            sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
            started = time.monotonic()
            code, output = self._run_group(
                data,
                port,
                startup_timeout=3,
                migrate_argv=self._STUB_OK,
                web_argv=list(sleeper),
                worker_argv=list(sleeper),
            )
            elapsed = time.monotonic() - started
            self.assertEqual(code, self.entry.EXIT_STARTUP)
            self.assertLess(elapsed, 15, "startup timeout must stay bounded")
            self.assertIn("startup timeout", output)
            self._lock_is_free(data)


@skipUnless(DESKTOP_DEPS_INSTALLED, "waitress/whitenoise are not installed")
class DesktopEndToEndTests(SimpleTestCase):
    """One full CLI run: real migrations, real Waitress web, real worker,
    real HTTP over the socket, then a graceful stdin-EOF shutdown."""

    maxDiff = None

    @staticmethod
    def _pump_output(process, sink):
        """Sole consumer of the child's stdout pipe: a direct readline() in
        the test thread would block forever past any deadline."""
        try:
            for line in process.stdout:
                sink.put(line)
        finally:
            sink.put(None)

    def _wait_for_ready(self, lines, deadline_seconds=240):
        deadline = time.monotonic() + deadline_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                line = self._line_queue.get(timeout=min(1.0, remaining))
            except queue.Empty:
                continue
            lines.append(line)
            if "ready on" in line:
                return
        raise AssertionError(
            "desktop run never became ready; output:\n%s" % "".join(lines[-40:])
        )

    def test_full_desktop_cli_run_http_boundary_and_clean_shutdown(self):
        from scripts import start_desktop as entry

        with tempfile.TemporaryDirectory(prefix="desktop-d2-e2e-") as raw:
            data_dir = Path(raw) / "d2 run dir"
            port = _free_port()
            repo_snapshot = sorted(os.listdir(REPO_ROOT))
            dist_snapshot = sorted(os.listdir(REPO_ROOT / "frontend" / "dist"))

            process = subprocess.Popen(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "start_desktop.py"),
                    "--data-dir",
                    str(data_dir),
                    "--port",
                    str(port),
                    "--no-browser",
                ],
                cwd=str(REPO_ROOT),
                env=_isolated_env(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self._line_queue = queue.Queue()
            reader = threading.Thread(
                target=self._pump_output, args=(process, self._line_queue), daemon=True
            )
            reader.start()
            base = "http://127.0.0.1:%d" % port
            lines: list[str] = []
            temp_password = None
            exit_code = None
            try:
                self._wait_for_ready(lines)

                status, headers, body = _http("GET", base + "/health")
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["status"], "ok")
                instance_header = headers.get("X-Marlin-Desktop-Instance")
                self.assertTrue(instance_header)

                status, headers, body = _http("GET", base + "/")
                self.assertEqual(status, 200)
                self.assertTrue(headers["Content-Type"].startswith("text/html"))
                self.assertIn(b'id="app"', body)
                index_html = body.decode("utf-8", "replace")

                deep_status, deep_headers, deep_body = _http("GET", base + "/workspace/deep")
                self.assertEqual(deep_status, 200)
                self.assertEqual(deep_body, body, "deep links must serve the SPA index")

                asset = re.search(r'src="(/assets/[^"]+\.js)"', index_html).group(1)
                status, headers, asset_body = _http("GET", base + asset)
                self.assertEqual(status, 200)
                self.assertTrue(headers["Content-Type"].startswith("text/javascript"), headers)

                status, headers, _body = _http("GET", base + "/api/v1/auth/config")
                self.assertEqual(status, 200)
                self.assertEqual(headers.get("Cache-Control"), "no-store")

                status, _headers, _body = _http("GET", base + "/files?path=escape")
                self.assertEqual(status, 401, "media must stay authenticated")

                status, _headers, body = _http(
                    "POST",
                    base + "/api/v1/auth/auto-setup",
                    headers={"Origin": "https://evil.example", "Content-Type": "application/json"},
                )
                self.assertEqual(status, 403)

                status, headers, body = _http(
                    "GET", base + "/api/v1/auth/auto-setup", headers={"Origin": "null"}
                )
                self.assertEqual(status, 405)
                with closing(sqlite3.connect(str(data_dir / "db.sqlite3"))) as connection:
                    users = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                self.assertEqual(users, 0, "rejected auto-setup must leave zero residue")

                status, headers, body = _http(
                    "POST",
                    base + "/api/v1/auth/auto-setup",
                    headers={
                        "Origin": "http://127.0.0.1:%d" % port,
                        "Content-Type": "application/json",
                    },
                )
                self.assertEqual(status, 201, body)
                payload = json.loads(body)
                self.assertTrue(payload["success"])
                temp_password = payload["data"]["temp_password"]
                self.assertTrue(temp_password)
                self.assertEqual(headers.get("Cache-Control"), "no-store")
                with closing(sqlite3.connect(str(data_dir / "db.sqlite3"))) as connection:
                    users = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                self.assertEqual(users, 1)

                status, _headers, _body = _http(
                    "POST",
                    base + "/api/v1/auth/login",
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(status, 401, "CLI writes without Origin must reach the API")

                opener = build_opener(ProxyHandler({}))
                request = Request(
                    base + "/api/v1/auth/login",
                    data=json.dumps({"username": "admin", "password": temp_password}).encode(),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with opener.open(request, timeout=10) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers.get("Cache-Control"), "no-store")
                    self.assertTrue(json.loads(response.read())["data"]["token"])

                process.stdin.close()
                exit_code = process.wait(timeout=45)
            finally:
                # Graceful first: closing stdin lets the launcher run its own
                # finally block (stopping ITS children, releasing the lock).
                # Only if that does not finish inside the bound do we fall
                # back to terminate→kill. Nothing is ever killed by port or
                # process name, and the reader thread is always joined so no
                # pipe is left half-consumed.
                if process.poll() is None:
                    try:
                        process.stdin.close()
                    except (OSError, ValueError):
                        pass
                    try:
                        process.wait(timeout=_GRACE_SECONDS)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        try:
                            process.wait(timeout=_GRACE_SECONDS)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=_GRACE_SECONDS)
                reader.join(timeout=_GRACE_SECONDS)
                _drain_lines(self._line_queue, lines)
                if process.stdout is not None:
                    process.stdout.close()

            self.assertEqual(
                exit_code,
                0,
                "graceful stdin-EOF shutdown must exit 0",
            )
            output = "".join(lines)
            self.assertIn("stdin closed", output)
            self.assertIn("[desktop] stopping", output)
            self.assertTrue(temp_password)
            self.assertNotIn(temp_password, output, "password must not be logged")
            secret = (data_dir / "secret.key").read_text(encoding="utf-8")
            self.assertTrue(secret)
            self.assertNotIn(secret, output, "secret must not be logged")

            self.assertTrue(_port_refuses(port), "children must be gone after shutdown")
            lock = entry.InstanceLock(data_dir)
            lock.acquire()
            lock.release()

            self.assertEqual(sorted(os.listdir(REPO_ROOT)), repo_snapshot)
            self.assertEqual(
                sorted(os.listdir(REPO_ROOT / "frontend" / "dist")), dist_snapshot
            )


class DesktopSettingsContractTests(SimpleTestCase):
    """The desktop secret is only produced by the desktop entry: generic
    production settings must keep failing without an explicit env secret."""

    def test_production_without_secret_fails_even_if_desktop_secret_exists(self):
        with tempfile.TemporaryDirectory(prefix="desktop-d2-data-") as data:
            (Path(data) / "secret.key").write_text("desktop-only-secret", encoding="utf-8")
            probe = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import django; django.setup();"
                    "from django.conf import settings; print(settings.SECRET_KEY)",
                ],
                env=_isolated_env(DJANGO_DEBUG="false"),
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
            )
            self.assertNotEqual(probe.returncode, 0)
            self.assertIn("DJANGO_SECRET_KEY", probe.stderr)
            self.assertNotIn("desktop-only-secret", probe.stdout + probe.stderr)

    def test_defaults_stay_off_without_desktop_entry(self):
        # Probe env deliberately omits the LANGFUSE/NEO4J keys (a developer's
        # repo .env may legitimately opt in); the default-off contract under
        # the desktop child env is asserted purely in test_desktop_env_contract.
        env = {key: os.environ[key] for key in _BASE_ENV_KEYS if key in os.environ}
        env.update(
            {
                "PYTHONDONTWRITEBYTECODE": "1",
                "DJANGO_SETTINGS_MODULE": "config.settings",
                "DJANGO_DEBUG": "true",
                "DJANGO_ALLOWED_HOSTS": "127.0.0.1,localhost",
            }
        )
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json, django; django.setup();"
                "from django.conf import settings;"
                "print(json.dumps({'debug': settings.DEBUG,"
                "'auto_setup': settings.ALLOW_AUTO_SETUP}))",
            ],
            env=env,
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr[-2000:])
        values = json.loads(probe.stdout.strip().splitlines()[-1])
        self.assertEqual(values, {"debug": True, "auto_setup": False})
