"""Cross-process contention tests for the first-run auto-setup gate.

Every scenario runs fresh Python subprocesses (spawn-compatible: no shared
interpreter state, each subprocess owns its database connection) against one
temporary SQLite database file under a new OS temporary directory. The parent
test process never touches the database through the ORM: it migrates the
database via a subprocess, orchestrates barriers through files in the
temporary directory, and inspects outcomes with the stdlib ``sqlite3`` module.

Subprocess lifecycle rules (all scenarios):

- The first ``Popen`` is already inside the ``try`` of its cleanup guard, so a
  later spawn failure cannot leak an earlier child.
- Normal completion drains stdout/stderr via ``communicate`` and verifies the
  return code; overrun, assertion failure and exceptions all funnel through
  ``_shutdown``, which terminates, kills (if needed) and reaps the child
  within a bounded grace period before any temporary directory is cleaned up.
- Subprocesses receive a sanitized environment (no provider/Neo4j/Langfuse
  credentials, external integrations disabled) and never touch real user data.
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

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

_WAIT_FOR_FILE_SECONDS = 60
_CHILD_TIMEOUT_SECONDS = 90
_MIGRATE_TIMEOUT_SECONDS = 240


def _isolated_env(**overrides):
    env = {key: os.environ[key] for key in _BASE_ENV_KEYS if key in os.environ}
    env.update(_ISOLATED_SETTINGS_ENV)
    env.update(overrides)
    return env


def _wait_for_file(path, deadline_seconds=_WAIT_FOR_FILE_SECONDS):
    deadline = time.monotonic() + deadline_seconds
    while not os.path.exists(path):
        if time.monotonic() > deadline:
            raise TimeoutError("timed out waiting for %s" % os.path.basename(path))
        time.sleep(0.02)


_WORKER_SCRIPT = r"""
import json
import os
import sys
import time

args = json.loads(sys.argv[1])
os.chdir(args["repo_root"])
sys.path.insert(0, args["repo_root"])
os.environ.clear()
os.environ.update(args["env"])

mode = args["mode"]

if mode == "migrate":
    import django

    django.setup()
    from django.core.management import call_command

    call_command("migrate", "--noinput", verbosity=0)
    print("MIGRATED")
    sys.exit(0)

import django

django.setup()

if mode == "hold":
    from filelock import FileLock

    lock = FileLock(args["lock_path"])
    lock.acquire(timeout=args.get("acquire_timeout", 5))
    with open(args["ready_path"], "w", encoding="utf-8") as handle:
        handle.write("held")
    if args.get("abrupt_exit"):
        os._exit(args.get("exit_code", 0))
    stop_path = args["stop_path"]
    deadline = time.monotonic() + args.get("hold_deadline", 30)
    while not os.path.exists(stop_path) and time.monotonic() < deadline:
        time.sleep(0.02)
    lock.release()
    with open(args["done_path"], "w", encoding="utf-8") as handle:
        handle.write("released")
    print("HOLD_DONE")
    sys.exit(0)

if mode == "acquire_only":
    from filelock import FileLock

    lock = FileLock(args["lock_path"])
    lock.acquire(timeout=args.get("acquire_timeout", 5))
    lock.release()
    with open(args["result_path"], "w", encoding="utf-8") as handle:
        json.dump({"acquired": True}, handle)
    print("ACQUIRED")
    sys.exit(0)

if mode in ("setup", "fail_then_retry"):
    import accounts.views as accounts_views
    from django.test import RequestFactory
    from personal_knowledge_base.models import Tenant, User

    if args.get("lock_timeout") is not None:
        accounts_views.AUTO_SETUP_LOCK_TIMEOUT = args["lock_timeout"]

    def post_auto_setup():
        request = RequestFactory().post("/api/v1/auth/auto-setup", content_type="application/json")
        try:
            response = accounts_views.auth_auto_setup(request)
            body = json.loads(response.content)
            return {
                "status": response.status_code,
                "success": body.get("success"),
                "code": (body.get("error") or {}).get("code"),
            }
        except Exception as exc:  # record the class only, never the message
            return {"exception": type(exc).__name__}

    ready_path = args.get("ready_path")
    if ready_path:
        with open(ready_path, "w", encoding="utf-8") as handle:
            handle.write("ready")
    start_path = args.get("start_path")
    if start_path:
        deadline = time.monotonic() + 60
        while not os.path.exists(start_path):
            if time.monotonic() > deadline:
                raise SystemExit("start barrier timeout")
            time.sleep(0.02)

    result = {}
    if mode == "setup":
        result = post_auto_setup()
    else:
        original_issue_tokens = accounts_views.issue_tokens

        def injected_failure(user):
            raise RuntimeError("injected failure")

        accounts_views.issue_tokens = injected_failure
        try:
            phase1 = post_auto_setup()
        finally:
            accounts_views.issue_tokens = original_issue_tokens
        phase1["users_after_rollback"] = User.objects.count()
        phase1["tenants_after_rollback"] = Tenant.objects.count()
        result = {"phase1": phase1, "phase2": post_auto_setup()}

    result["users_final"] = User.objects.count()
    with open(args["result_path"], "w", encoding="utf-8") as handle:
        json.dump(result, handle)
    print("SETUP_DONE")
    sys.exit(0)

raise SystemExit("unknown mode: %s" % mode)
"""


class AutoSetupProcessContentionTests(SimpleTestCase):
    maxDiff = None

    _GRACE_SECONDS = 10

    def _lock_path_for(self, db_path):
        from accounts import views as accounts_views

        return accounts_views._sqlite_auto_setup_lock_path(db_path)

    def _spawn(self, args):
        return subprocess.Popen(
            [sys.executable, "-c", _WORKER_SCRIPT, json.dumps(args)],
            cwd=str(REPO_ROOT),
            env=args["env"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def _collect(self, process, timeout):
        """Boundedly read the pipes and reap the child, killing it on overrun."""
        try:
            return process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                return process.communicate(timeout=self._GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                raise AssertionError(
                    "worker subprocess survived kill beyond %ss" % self._GRACE_SECONDS
                )

    def _shutdown(self, process):
        """Boundedly terminate, reap and drain a worker; safe to call twice."""
        if process.stdout is not None or process.stderr is not None:
            if process.poll() is None:
                process.terminate()
            self._collect(process, self._GRACE_SECONDS)
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=self._GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=self._GRACE_SECONDS)

    def _finish(self, process, timeout=_CHILD_TIMEOUT_SECONDS):
        """Wait for a clean exit: bounded collect plus return-code check."""
        stdout, stderr = self._collect(process, timeout)
        self.assertEqual(
            process.returncode,
            0,
            "worker subprocess failed (exit %s)\n--- stdout ---\n%s\n--- stderr tail ---\n%s"
            % (process.returncode, stdout, "\n".join((stderr or "").splitlines()[-15:])),
        )
        return stdout, stderr

    def _migrate(self, db_path):
        process = self._spawn(
            {
                "mode": "migrate",
                "repo_root": str(REPO_ROOT),
                "env": _isolated_env(DJANGO_DB_PATH=db_path),
            }
        )
        try:
            self._finish(process, timeout=_MIGRATE_TIMEOUT_SECONDS)
        finally:
            self._shutdown(process)

    def _row_counts(self, db_path):
        connection = sqlite3.connect(db_path, timeout=15)
        try:
            counts = {
                table: connection.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
                for table in ("users", "tenants", "tenant_members", "auth_tokens")
            }
            counts["tokens_for_user"] = connection.execute(
                "SELECT COUNT(*) FROM auth_tokens t JOIN users u ON t.user_id = u.id"
            ).fetchone()[0]
            counts["members_with_user_and_tenant"] = connection.execute(
                "SELECT COUNT(*) FROM tenant_members m JOIN users u ON m.user_id = u.id"
                " JOIN tenants t ON m.tenant_id = t.id"
            ).fetchone()[0]
            return counts
        finally:
            connection.close()

    def _spawn_holder(self, tmp, db_path, *, abrupt_exit=False, hold_deadline=60):
        return self._spawn(
            {
                "mode": "hold",
                "repo_root": str(REPO_ROOT),
                "env": _isolated_env(DJANGO_DB_PATH=db_path),
                "lock_path": self._lock_path_for(db_path),
                "ready_path": os.path.join(tmp, "holder-ready"),
                "stop_path": os.path.join(tmp, "holder-stop"),
                "done_path": os.path.join(tmp, "holder-done"),
                "abrupt_exit": abrupt_exit,
                "hold_deadline": hold_deadline,
            }
        )

    def test_two_processes_create_exactly_one_first_account(self):
        """A3: simultaneous entries from two processes yield one account set."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "shared.sqlite3")
            self._migrate(db_path)

            workers = []
            try:
                for index in range(2):
                    result_path = os.path.join(tmp, "result-%d.json" % index)
                    args = {
                        "mode": "setup",
                        "repo_root": str(REPO_ROOT),
                        "env": _isolated_env(DJANGO_DB_PATH=db_path),
                        "ready_path": os.path.join(tmp, "ready-%d" % index),
                        "start_path": os.path.join(tmp, "start"),
                        "result_path": result_path,
                    }
                    workers.append((args, self._spawn(args), result_path))

                for args, _process, _result_path in workers:
                    _wait_for_file(args["ready_path"])
                Path(os.path.join(tmp, "start")).write_text("go", encoding="utf-8")

                results = []
                for _args, process, result_path in workers:
                    _wait_for_file(result_path)
                    self._finish(process)
                    with open(result_path, encoding="utf-8") as handle:
                        results.append(json.load(handle))
            finally:
                for _args, process, _result_path in workers:
                    self._shutdown(process)

            statuses = sorted(result["status"] for result in results)
            self.assertEqual(statuses, [201, 401], "unexpected statuses: %r" % results)
            winner = next(result for result in results if result["status"] == 201)
            loser = next(result for result in results if result["status"] == 401)
            self.assertTrue(winner["success"])
            self.assertFalse(loser["success"])
            self.assertEqual(loser["code"], "setup_already_completed")

            counts = self._row_counts(db_path)
            self.assertEqual(counts["users"], 1)
            self.assertEqual(counts["tenants"], 1)
            self.assertEqual(counts["tenant_members"], 1)
            self.assertEqual(counts["auth_tokens"], 2)
            self.assertEqual(counts["tokens_for_user"], 2)
            self.assertEqual(counts["members_with_user_and_tenant"], 1)

    def test_exception_in_critical_section_rolls_back_and_releases_lock(self):
        """A4: injected failure rolls back, releases the lock, retry succeeds."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "rollback.sqlite3")
            self._migrate(db_path)

            result_path = os.path.join(tmp, "result.json")
            args = {
                "mode": "fail_then_retry",
                "repo_root": str(REPO_ROOT),
                "env": _isolated_env(DJANGO_DB_PATH=db_path),
                "result_path": result_path,
            }
            process = self._spawn(args)
            try:
                _wait_for_file(result_path)
                self._finish(process)
            finally:
                self._shutdown(process)

            with open(result_path, encoding="utf-8") as handle:
                result = json.load(handle)

            self.assertEqual(result["phase1"]["exception"], "RuntimeError")
            self.assertEqual(result["phase1"]["users_after_rollback"], 0)
            self.assertEqual(result["phase1"]["tenants_after_rollback"], 0)
            self.assertEqual(result["phase2"]["status"], 201)
            self.assertEqual(result["users_final"], 1)

            counts = self._row_counts(db_path)
            self.assertEqual(counts["users"], 1)
            self.assertEqual(counts["tenants"], 1)
            self.assertEqual(counts["tenant_members"], 1)
            self.assertEqual(counts["auth_tokens"], 2)

    def test_lock_held_by_exited_process_is_acquired_by_another(self):
        """A4: the lock is a real OS lock — a successor acquires it after the
        holder dies, and no user data is touched to free it."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "handoff.sqlite3")
            self._migrate(db_path)

            contender = None
            holder = self._spawn_holder(tmp, db_path, abrupt_exit=True)
            try:
                _wait_for_file(os.path.join(tmp, "holder-ready"))
                stdout, stderr = self._collect(holder, 15)
                self.assertEqual(
                    holder.returncode,
                    0,
                    "holder exit unexpected\n--- stdout ---\n%s\n--- stderr tail ---\n%s"
                    % (stdout, "\n".join((stderr or "").splitlines()[-15:])),
                )

                result_path = os.path.join(tmp, "contender-result.json")
                contender = self._spawn(
                    {
                        "mode": "acquire_only",
                        "repo_root": str(REPO_ROOT),
                        "env": _isolated_env(DJANGO_DB_PATH=db_path),
                        "lock_path": self._lock_path_for(db_path),
                        "result_path": result_path,
                        "acquire_timeout": 10,
                    }
                )
                try:
                    _wait_for_file(result_path)
                    self._finish(contender)
                finally:
                    self._shutdown(contender)

                with open(result_path, encoding="utf-8") as handle:
                    self.assertEqual(json.load(handle), {"acquired": True})
            finally:
                for process in (contender, holder):
                    if process is not None:
                        self._shutdown(process)

            counts = self._row_counts(db_path)
            self.assertEqual(counts["users"], 0, "no data was touched to free the lock")

    def test_lock_timeout_across_processes_returns_503_setup_busy(self):
        """A6: bounded wait across processes maps to 503/setup_busy, no residue."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "busy.sqlite3")
            self._migrate(db_path)

            loser = None
            winner = None
            holder = self._spawn_holder(tmp, db_path)
            try:
                _wait_for_file(os.path.join(tmp, "holder-ready"))

                loser_result = os.path.join(tmp, "loser-result.json")
                loser = self._spawn(
                    {
                        "mode": "setup",
                        "repo_root": str(REPO_ROOT),
                        "env": _isolated_env(DJANGO_DB_PATH=db_path),
                        "result_path": loser_result,
                        "lock_timeout": 0.3,
                    }
                )
                try:
                    _wait_for_file(loser_result)
                    self._finish(loser)
                finally:
                    self._shutdown(loser)

                with open(loser_result, encoding="utf-8") as handle:
                    loser_payload = json.load(handle)
                self.assertEqual(loser_payload["status"], 503)
                self.assertFalse(loser_payload["success"])
                self.assertEqual(loser_payload["code"], "setup_busy")

                counts = self._row_counts(db_path)
                self.assertEqual(counts["users"], 0)
                self.assertEqual(counts["auth_tokens"], 0)

                Path(os.path.join(tmp, "holder-stop")).write_text("stop", encoding="utf-8")
                _wait_for_file(os.path.join(tmp, "holder-done"))
                stdout, stderr = self._collect(holder, 15)
                self.assertEqual(
                    holder.returncode,
                    0,
                    "holder exit unexpected\n--- stdout ---\n%s\n--- stderr tail ---\n%s"
                    % (stdout, "\n".join((stderr or "").splitlines()[-15:])),
                )

                winner_result = os.path.join(tmp, "winner-result.json")
                winner = self._spawn(
                    {
                        "mode": "setup",
                        "repo_root": str(REPO_ROOT),
                        "env": _isolated_env(DJANGO_DB_PATH=db_path),
                        "result_path": winner_result,
                    }
                )
                try:
                    _wait_for_file(winner_result)
                    self._finish(winner)
                finally:
                    self._shutdown(winner)

                with open(winner_result, encoding="utf-8") as handle:
                    self.assertEqual(json.load(handle)["status"], 201)
            finally:
                for process in (winner, loser, holder):
                    if process is not None:
                        self._shutdown(process)

            counts = self._row_counts(db_path)
            self.assertEqual(counts["users"], 1)
            self.assertEqual(counts["auth_tokens"], 2)

    def test_shutdown_terminates_and_reaps_live_stuck_child(self):
        """R2 regression: the bounded cleanup path proactively terminates and
        reaps a still-alive stuck child, with pipes drained — observed via its
        real exit, not via call mocks. This test exercises the proactive
        cleanup branch of _shutdown, not the wait-overrun kill branch."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "reap.sqlite3")
            self._migrate(db_path)

            process = self._spawn_holder(tmp, db_path, hold_deadline=300)
            try:
                _wait_for_file(os.path.join(tmp, "holder-ready"))
                self.assertIsNone(process.poll(), "child should still be alive before cleanup")
            finally:
                self._shutdown(process)

            self.assertIsNotNone(
                process.returncode, "stuck child must be reaped by the bounded cleanup"
            )
            self.assertTrue(process.stdout is None or process.stdout.closed)
            counts = self._row_counts(db_path)
            self.assertEqual(counts["users"], 0)

    def test_midway_spawn_failure_reaps_already_created_child(self):
        """R2 regression: a failed later spawn must not leak earlier children."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "spawn-fail.sqlite3")
            self._migrate(db_path)

            first = None
            try:
                first = self._spawn_holder(tmp, db_path, hold_deadline=300)
                _wait_for_file(os.path.join(tmp, "holder-ready"))

                with mock.patch(
                    "accounts.test_auto_setup_processes.subprocess.Popen",
                    side_effect=OSError("simulated spawn failure"),
                ):
                    with self.assertRaises(OSError):
                        self._spawn_holder(tmp, db_path, hold_deadline=300)
            finally:
                if first is not None:
                    self._shutdown(first)

            self.assertIsNotNone(
                first.returncode, "the first child must be reaped when a later spawn fails"
            )
            counts = self._row_counts(db_path)
            self.assertEqual(counts["users"], 0)
