"""Runtime lock portability contract for the three non-Django file locks.

``model_rate_limit._bucket_lock``, ``open_rag_benchmark.open_rag_prepare_lock``
and ``scripts.local_services.ensure_langfuse`` must keep their kernel
file-lock semantics without ``fcntl`` (absent on Windows), using the already
declared ``filelock`` dependency.  The probes run real independent
subprocesses in which ``fcntl`` is blocked at the import-system level.  The
filelock backend itself is loaded before the blocker is installed and the
cached module is evicted, so kernel locking still works while the blocker
proves the audited modules never import ``fcntl`` themselves — this mirrors
the native Windows import surface without downgrading to SoftFileLock.
Cross-process tests drive the real business lock functions against
temporary BASE_DIR / cache directories and never touch repository state.

Cross-process discipline: the holder only releases after the contender has
registered an ``attempting`` barrier, and release notes are written BEFORE
unlock so the contender observes them as soon as it acquires — no holder
sleeps that guess when the contender starts.  Deliberate child finishes are
communicated and validated (real exit code, empty stderr); kill is reserved
for abnormal termination.
"""

import hashlib
import os
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock, skipIf

from django.test import SimpleTestCase, override_settings

from .eval_dataset_registry import get_dataset_spec
from .model_rate_limit import _bucket_lock
from .open_rag_benchmark import open_rag_prepare_lock

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
    "ALLOW_AUTO_SETUP": "false",
    "NEO4J_ENABLE": "false",
    "LANGFUSE_ENABLED": "false",
    "LANGFUSE_AUTOSTART": "false",
    "DJANGO_ALLOWED_HOSTS": "testserver,localhost",
}


def _base_env(scratch, **overrides):
    env = {key: os.environ[key] for key in _BASE_ENV_KEYS if key in os.environ}
    env.update(_ISOLATED_SETTINGS_ENV)
    env["DJANGO_DB_PATH"] = str(Path(scratch) / "probe.sqlite3")
    env.update(overrides)
    return env


def _child_bootstrap():
    return r"""
import importlib.abc
import sys

import filelock  # bind the POSIX backend before fcntl becomes unavailable

sys.modules.pop("fcntl", None)

# Flag the probe process as a test runner so app-ready startup-recovery
# timers are skipped (should_schedule_recovery), keeping probes side-effect free.
sys.argv.append("unittest")


class _FcntlUnavailable(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "fcntl":
            raise ModuleNotFoundError("No module named 'fcntl'", name="fcntl")
        return None


sys.meta_path.insert(0, _FcntlUnavailable())

try:
    import fcntl
except ModuleNotFoundError:
    pass
else:
    raise SystemExit("probe broken: fcntl import was not blocked")

import django

django.setup()
"""


def _run_blocked_probe(scenario_code, timeout=180, env_overrides=None):
    with tempfile.TemporaryDirectory() as scratch:
        return subprocess.run(
            [sys.executable, "-c", _child_bootstrap() + scenario_code, scratch],
            cwd=str(REPO_ROOT),
            env=_base_env(scratch, **(env_overrides or {})),
            capture_output=True,
            text=True,
            timeout=timeout,
        )


def _assert_probe_ok(test, completed):
    test.assertEqual(
        completed.returncode,
        0,
        "blocked-fcntl probe failed\n--- stdout ---\n%s\n--- stderr tail ---\n%s"
        % (completed.stdout, "\n".join(completed.stderr.splitlines()[-15:])),
    )
    test.assertIn("PORTABILITY_OK", completed.stdout)
    test.assertEqual(completed.stderr, "", "blocked-fcntl probe wrote to stderr")


def _spawn_child(code, scratch, env_overrides=None):
    env = _base_env(scratch, **(env_overrides or {}))
    # Unique per-child SQLite path: siblings running django.setup() must not
    # race their WAL pragma on one freshly created database file.
    if "DJANGO_DB_PATH" not in (env_overrides or {}):
        env["DJANGO_DB_PATH"] = str(Path(scratch) / f"child-{os.getpid()}-{time.monotonic_ns()}.sqlite3")
    return subprocess.Popen(
        [sys.executable, "-c", code, str(scratch)],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def _reap(process, timeout=15):
    """Boundedly terminate and reap a child; idempotent, never leaks pipes.

    Kill is reserved for abnormal termination: deliberate finishes go
    through :func:`_wait_child`, which validates exit code and stderr.
    """
    if getattr(process, "_p02a_reaped", False):
        return
    try:
        if process.poll() is None:
            process.kill()
        try:
            process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=timeout)
    finally:
        process._p02a_reaped = True
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                try:
                    stream.close()
                except OSError:
                    pass


def _wait_child(process, expected_code=0, timeout=120):
    """Communicate a child that should finish deliberately and validate it."""
    try:
        _stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _reap(process)
        raise AssertionError("child process did not finish in time")
    process._p02a_reaped = True
    stderr = stderr or ""
    if process.returncode != expected_code:
        raise AssertionError(
            "child exited with code %s (expected %s)\n--- stderr tail ---\n%s"
            % (process.returncode, expected_code, "\n".join(stderr.splitlines()[-10:]))
        )
    if stderr:
        raise AssertionError("child exited cleanly but wrote stderr:\n%s" % stderr)


def _wait_marker(scratch, name, processes=(), timeout=30):
    """Wait for a barrier marker, watching children for early exits.

    Returns True once ``scratch/name`` exists.  A watched child that
    terminates before the marker appears fails immediately with its real
    exit code and stderr tail instead of stalling out the whole timeout.
    """
    marker = Path(scratch) / name
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if marker.exists():
            return True
        for process in processes:
            if process.poll() is not None:
                if marker.exists():
                    return True
                try:
                    _stdout, stderr = process.communicate(timeout=5)
                except (subprocess.TimeoutExpired, ValueError, OSError):
                    stderr = ""
                process._p02a_reaped = True
                raise AssertionError(
                    "watched child exited with code %s before marker %r appeared\n--- stderr tail ---\n%s"
                    % (process.returncode, name, "\n".join((stderr or "").splitlines()[-10:]))
                )
        time.sleep(0.02)
    return False


_DJANGO_CHILD_PREFIX = r"""
import os
import sys
import time
from pathlib import Path

# Flag the child as a test runner so app-ready startup-recovery timers are
# skipped (should_schedule_recovery); scratch stays at sys.argv[1].
sys.argv.append("unittest")

import django

django.setup()

scratch = Path(sys.argv[1])
"""

_MODEL_CHILD_PREFIX = _DJANGO_CHILD_PREFIX + r"""
from django.conf import settings

from personal_knowledge_base.model_rate_limit import _bucket_lock

settings.BASE_DIR = scratch
"""

_PREPARE_CHILD_PREFIX = _DJANGO_CHILD_PREFIX + r"""
from dataclasses import replace

from personal_knowledge_base.eval_dataset_registry import get_dataset_spec
from personal_knowledge_base.open_rag_benchmark import open_rag_prepare_lock

spec = replace(get_dataset_spec("open_rag_benchmark", "arxiv-v1"), cache_path=scratch)
"""

_LANGFUSE_HOLDER_CHILD = r"""
import os
import sys
import time
from pathlib import Path

from filelock import FileLock

scratch = Path(sys.argv[1])
hold_seconds = float(os.environ["P02A_HOLD_SECONDS"])
lock = FileLock(scratch / "startup.lock")
lock.acquire()
(scratch / "L_holder_acquired").write_text("1")
time.sleep(hold_seconds)
lock.release()
"""

_LANGFUSE_BARRIER_HOLDER_CHILD = r"""
import sys
import time
from pathlib import Path

from filelock import FileLock

scratch = Path(sys.argv[1])
give_up_at = time.monotonic() + 20
lock = FileLock(scratch / "startup.lock")
lock.acquire()
(scratch / "L_holder_acquired").write_text("1")
while not (scratch / "L_release").exists():
    if time.monotonic() > give_up_at:
        raise SystemExit("barrier L_release never appeared")
    time.sleep(0.02)
lock.release()
"""


class _ScriptedClock:
    """Deterministic ``time`` stand-in injected into scripts.local_services."""

    def __init__(self, now=1000.0):
        self.now = now

    def monotonic(self):
        return self.now

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(0.0, seconds)


class BlockedFcntlImportContractTests(SimpleTestCase):
    """A1: each module imports on a no-fcntl platform and reaches its lock path."""

    def test_model_rate_limit_lock_works_without_fcntl(self):
        completed = _run_blocked_probe(_MODEL_CHILD_PREFIX + r"""
with _bucket_lock("portability-probe"):
    (scratch / "model_entered").write_text("1")
print("PORTABILITY_OK")
""")
        _assert_probe_ok(self, completed)

    def test_open_rag_prepare_lock_works_without_fcntl(self):
        completed = _run_blocked_probe(_PREPARE_CHILD_PREFIX + r"""
with open_rag_prepare_lock(spec, blocking=False) as acquired:
    if not acquired:
        raise SystemExit("free prepare lock was not acquired")
    (scratch / "prepare_entered").write_text("1")
print("PORTABILITY_OK")
""")
        _assert_probe_ok(self, completed)

    def test_langfuse_startup_lock_works_without_fcntl(self):
        completed = _run_blocked_probe(r"""
import sys
from pathlib import Path

from scripts.local_services import ensure_langfuse

scratch = Path(sys.argv[1])
state = ensure_langfuse(scratch)
if state["state"] != "missing_server_configuration":
    raise SystemExit("unexpected startup state: %s" % state["state"])
print("PORTABILITY_OK")
""", env_overrides={"LANGFUSE_AUTOSTART": "true"})
        _assert_probe_ok(self, completed)


class ModelBucketLockSemanticsTests(SimpleTestCase):
    """A2: permission intent, failure isolation, and preserved blocking semantics."""

    def test_lock_error_blocks_critical_section(self):
        entered = []
        with tempfile.TemporaryDirectory() as tmp, override_settings(BASE_DIR=Path(tmp)), mock.patch(
            "filelock.FileLock.acquire",
            side_effect=OSError("lock backend unavailable"),
        ):
            with self.assertRaises(OSError):
                with _bucket_lock("key"):
                    entered.append(1)
        self.assertEqual(entered, [])

    def test_critical_section_exception_releases_lock(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(BASE_DIR=Path(tmp)):
            with self.assertRaises(RuntimeError):
                with _bucket_lock("key"):
                    raise RuntimeError("injected")
            with _bucket_lock("key"):
                pass

    @skipIf(os.name == "nt", "POSIX permission bits")
    def test_lock_file_enforces_0600(self):
        key = hashlib.sha256(b"openai:model").hexdigest()
        with tempfile.TemporaryDirectory() as tmp, override_settings(BASE_DIR=Path(tmp)):
            with _bucket_lock(key):
                locks = list((Path(tmp) / ".cache" / "model-rate-limits").glob("*.lock"))
                # Asserted while held: the filelock backend may delete its lock
                # file on release (Windows backend does), so stat before exit.
                self.assertEqual(len(locks), 1)
                self.assertEqual(stat.S_IMODE(locks[0].stat().st_mode) & 0o077, 0)


class ModelBucketLockCrossProcessTests(SimpleTestCase):
    """A2/A5: real independent subprocesses; bounded create/fail/timeout reaping."""

    def test_same_key_is_cross_process_mutex(self):
        holder = _MODEL_CHILD_PREFIX + r"""
with _bucket_lock("same-key"):
    (scratch / "A_held").write_text("1")
    give_up_at = time.monotonic() + 20
    while not (scratch / "B_blocked").exists():
        if time.monotonic() > give_up_at:
            raise SystemExit("barrier B_blocked never appeared")
        time.sleep(0.02)
    # Release note written BEFORE unlock: the successor must observe it as
    # soon as it acquires, with no post-unlock write racing its check.
    (scratch / "A_releasing").write_text("1")
"""
        successor = _MODEL_CHILD_PREFIX + r"""
from filelock import FileLock, Timeout

(scratch / "B_attempting").write_text("1")
# One real bounded acquire attempt on the same lock path must fail while the
# holder runs: genuine kernel-level contention, not just start ordering.
probe = FileLock(scratch / ".cache" / "model-rate-limits" / "same-key.lock", mode=0o600)
try:
    probe.acquire(timeout=0)
except Timeout:
    if probe.is_locked:
        raise SystemExit("probe holds the lock it failed to take")
else:
    probe.release()
    raise SystemExit("same-key lock was free: no real contention probed")
(scratch / "B_blocked").write_text("1")
with _bucket_lock("same-key"):
    saw_release_note = (scratch / "A_releasing").exists()
    (scratch / "B_entered").write_text(str(saw_release_note))
"""
        with tempfile.TemporaryDirectory() as scratch:
            holder_process = None
            successor_process = None
            try:
                holder_process = _spawn_child(holder, scratch)
                self.assertTrue(_wait_marker(scratch, "A_held", (holder_process,), 15))
                successor_process = _spawn_child(successor, scratch)
                self.assertTrue(_wait_marker(scratch, "B_attempting", (holder_process, successor_process), 15))
                self.assertTrue(_wait_marker(scratch, "B_blocked", (holder_process, successor_process), 15))
                self.assertTrue(_wait_marker(scratch, "B_entered", (successor_process,), 30))
                # B_entered can only read True when the successor entered after
                # the holder's pre-unlock release note: no overlap with the
                # held span, however slow either child was to start.
                self.assertEqual((Path(scratch) / "B_entered").read_text(), "True")
                _wait_child(successor_process)
                _wait_child(holder_process)
            finally:
                if holder_process is not None:
                    _reap(holder_process)
                if successor_process is not None:
                    _reap(successor_process)

    def test_different_keys_run_in_parallel(self):
        child = _MODEL_CHILD_PREFIX + r"""
key = os.environ["P02A_KEY"]
mine, peer = os.environ["P02A_MINE"], os.environ["P02A_PEER"]
with _bucket_lock(key):
    (scratch / mine).write_text("1")
    deadline = time.monotonic() + 10
    while not (scratch / peer).exists():
        if time.monotonic() > deadline:
            (scratch / (mine + "_timeout")).write_text("1")
            break
        time.sleep(0.02)
"""
        with tempfile.TemporaryDirectory() as scratch:
            one = two = None
            try:
                one = _spawn_child(child, scratch, env_overrides={
                    "P02A_KEY": "parallel-one", "P02A_MINE": "PAR_A", "P02A_PEER": "PAR_B",
                    "DJANGO_DB_PATH": str(Path(scratch) / "one.sqlite3"),
                })
                two = _spawn_child(child, scratch, env_overrides={
                    "P02A_KEY": "parallel-two", "P02A_MINE": "PAR_B", "P02A_PEER": "PAR_A",
                    "DJANGO_DB_PATH": str(Path(scratch) / "two.sqlite3"),
                })
                self.assertTrue(_wait_marker(scratch, "PAR_A", (one, two), 15))
                self.assertTrue(_wait_marker(scratch, "PAR_B", (one, two), 15))
                _wait_child(one)
                _wait_child(two)
            finally:
                if one is not None:
                    _reap(one)
                if two is not None:
                    _reap(two)
            self.assertFalse((Path(scratch) / "PAR_A_timeout").exists())
            self.assertFalse((Path(scratch) / "PAR_B_timeout").exists())

    def test_successor_acquires_after_holder_process_exit(self):
        holder = _MODEL_CHILD_PREFIX + r"""
with _bucket_lock("crash-key"):
    (scratch / "H_entered").write_text("1")
    sys.stdout.flush()
    os._exit(2)
"""
        successor = _MODEL_CHILD_PREFIX + r"""
with _bucket_lock("crash-key"):
    (scratch / "NEXT_acquired").write_text("1")
"""
        with tempfile.TemporaryDirectory() as scratch:
            crashed = None
            successor_process = None
            try:
                crashed = _spawn_child(holder, scratch)
                self.assertTrue(_wait_marker(scratch, "H_entered", (crashed,), 15))
                # The kernel drops a flock when the holder dies; validate the
                # real abnormal exit code before letting the successor run.
                _wait_child(crashed, expected_code=2)
                successor_process = _spawn_child(successor, scratch)
                self.assertTrue(_wait_marker(scratch, "NEXT_acquired", (successor_process,), 15))
                _wait_child(successor_process)
            finally:
                if crashed is not None:
                    _reap(crashed)
                if successor_process is not None:
                    _reap(successor_process)


class OpenRagPrepareLockCrossProcessTests(SimpleTestCase):
    """A3: skip-while-held and wait-then-enter inside the real business context."""

    def test_nonblocking_yields_false_promptly_while_holder_runs(self):
        holder = _PREPARE_CHILD_PREFIX + r"""
with open_rag_prepare_lock(spec, blocking=True):
    (scratch / "P_held").write_text("1")
    give_up_at = time.monotonic() + 20
    while not (scratch / "C_done").exists():
        if time.monotonic() > give_up_at:
            raise SystemExit("barrier C_done never appeared")
        time.sleep(0.02)
(scratch / "P_released").write_text("1")
"""
        contender = _PREPARE_CHILD_PREFIX + r"""
(scratch / "C_attempting").write_text("1")
started = time.monotonic()
with open_rag_prepare_lock(spec, blocking=False) as acquired:
    elapsed = time.monotonic() - started
    # Written while the holder is still stalled on C_done, i.e. while the
    # lock is provably held, so "skipped" cannot come from a free lock.
    (scratch / "C_done").write_text("skipped" if not acquired else "acquired")
    if acquired:
        raise SystemExit("contended prepare lock must not be acquired non-blocking")
(scratch / "C_elapsed").write_text("%.3f" % elapsed)
"""
        with tempfile.TemporaryDirectory() as scratch:
            held = None
            skipping = None
            try:
                held = _spawn_child(holder, scratch)
                self.assertTrue(_wait_marker(scratch, "P_held", (held,), 15))
                skipping = _spawn_child(contender, scratch)
                self.assertTrue(_wait_marker(scratch, "C_attempting", (held, skipping), 15))
                self.assertTrue(_wait_marker(scratch, "C_done", (skipping,), 30))
                self.assertEqual((Path(scratch) / "C_done").read_text(), "skipped")
                self.assertTrue(_wait_marker(scratch, "P_released", (held,), 15))
                _wait_child(skipping)
                _wait_child(held)
                self.assertLess(float((Path(scratch) / "C_elapsed").read_text()), 0.8)
            finally:
                if held is not None:
                    _reap(held)
                if skipping is not None:
                    _reap(skipping)

    def test_blocking_waits_for_release_then_acquires(self):
        holder = _PREPARE_CHILD_PREFIX + r"""
with open_rag_prepare_lock(spec, blocking=True):
    (scratch / "P_held").write_text("1")
    give_up_at = time.monotonic() + 20
    while not (scratch / "C_blocked").exists():
        if time.monotonic() > give_up_at:
            raise SystemExit("barrier C_blocked never appeared")
        time.sleep(0.02)
    # Release flag written BEFORE unlock, so the contender sees it the
    # moment it acquires; a post-unlock write would race its check.
    (scratch / "P_released").write_text("1")
"""
        contender = _PREPARE_CHILD_PREFIX + r"""
from filelock import FileLock, Timeout

(scratch / "C_attempting").write_text("1")
# One real bounded acquire attempt must fail while the holder runs, proving
# the later blocking acquisition genuinely waited on kernel contention.
probe = FileLock(scratch / ".prepare.lock")
try:
    probe.acquire(timeout=0)
except Timeout:
    if probe.is_locked:
        raise SystemExit("probe holds the lock it failed to take")
else:
    probe.release()
    raise SystemExit("prepare lock was free: no real contention probed")
(scratch / "C_blocked").write_text("1")
with open_rag_prepare_lock(spec, blocking=True) as acquired:
    if not acquired or not (scratch / "P_released").exists():
        raise SystemExit("blocking prepare lock must enter after the holder released")
    (scratch / "P_acquired_after_release").write_text("1")
"""
        with tempfile.TemporaryDirectory() as scratch:
            held = None
            waiting = None
            try:
                held = _spawn_child(holder, scratch)
                self.assertTrue(_wait_marker(scratch, "P_held", (held,), 15))
                waiting = _spawn_child(contender, scratch)
                self.assertTrue(_wait_marker(scratch, "C_attempting", (held, waiting), 15))
                self.assertTrue(_wait_marker(scratch, "C_blocked", (held, waiting), 15))
                self.assertTrue(_wait_marker(scratch, "P_acquired_after_release", (waiting,), 30))
                _wait_child(waiting)
                _wait_child(held)
            finally:
                if held is not None:
                    _reap(held)
                if waiting is not None:
                    _reap(waiting)

    def test_critical_section_exception_releases_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = replace(get_dataset_spec("open_rag_benchmark", "arxiv-v1"), cache_path=Path(tmp))
            with self.assertRaises(RuntimeError):
                with open_rag_prepare_lock(spec, blocking=True):
                    raise RuntimeError("injected")
            with open_rag_prepare_lock(spec, blocking=True) as acquired:
                self.assertTrue(acquired)


class LangfuseStartupLockTests(SimpleTestCase):
    """A4: contention shares the monotonic budget; error mapping is preserved."""

    def test_disabled_and_external_early_exits_preserved(self):
        from scripts.local_services import ensure_langfuse

        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.dict(os.environ, {"LANGFUSE_AUTOSTART": "false"}):
            self.assertEqual(ensure_langfuse(directory)["state"], "disabled")
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ,
            {"LANGFUSE_AUTOSTART": "true", "LANGFUSE_BASE_URL": "https://langfuse.example"},
        ):
            self.assertEqual(ensure_langfuse(directory)["state"], "external")

    def test_docker_unavailable_and_compose_failed_preserved(self):
        from scripts.local_services import ensure_langfuse

        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.dict(os.environ, {"LANGFUSE_AUTOSTART": "true"}), \
                mock.patch("scripts.local_services.subprocess.run", side_effect=FileNotFoundError):
            Path(directory, ".env.langfuse").touch()
            self.assertEqual(ensure_langfuse(directory)["state"], "docker_unavailable")
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.dict(os.environ, {"LANGFUSE_AUTOSTART": "true"}), \
                mock.patch("scripts.local_services.subprocess.run", return_value=SimpleNamespace(returncode=1)):
            Path(directory, ".env.langfuse").touch()
            self.assertEqual(ensure_langfuse(directory)["state"], "compose_failed")

    def _held_langfuse_dir(self, tmp):
        directory = Path(tmp) / ".cache" / "langfuse"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def test_contention_exhausts_budget_without_calling_docker(self):
        from scripts.local_services import ensure_langfuse

        with tempfile.TemporaryDirectory() as tmp:
            directory = self._held_langfuse_dir(tmp)
            holder = None
            try:
                holder = _spawn_child(_LANGFUSE_BARRIER_HOLDER_CHILD, directory, env_overrides={
                    "LANGFUSE_AUTOSTART": "true",
                })
                self.assertTrue(_wait_marker(directory, "L_holder_acquired", (holder,), 15))
                with mock.patch.dict(os.environ, {
                    "LANGFUSE_AUTOSTART": "true",
                    "LANGFUSE_STARTUP_TIMEOUT_SECONDS": "1",
                }), mock.patch("scripts.local_services.subprocess.run") as run, \
                        mock.patch("scripts.local_services.build_opener") as opener:
                    state = ensure_langfuse(tmp)
                self.assertEqual(state["state"], "startup_timeout")
                run.assert_not_called()
                opener.assert_not_called()
                (directory / "L_release").write_text("1")
                _wait_child(holder)
            finally:
                if holder is not None:
                    try:
                        (directory / "L_release").write_text("1")
                    except OSError:
                        pass
                    _reap(holder)

    def test_startup_continues_after_holder_releases(self):
        from scripts.local_services import ensure_langfuse

        with tempfile.TemporaryDirectory() as tmp:
            directory = self._held_langfuse_dir(tmp)
            holder = None
            try:
                holder = _spawn_child(_LANGFUSE_HOLDER_CHILD, directory, env_overrides={
                    "P02A_HOLD_SECONDS": "0.5",
                    "LANGFUSE_AUTOSTART": "true",
                })
                self.assertTrue(_wait_marker(directory, "L_holder_acquired", (holder,), 15))
                Path(tmp, ".env.langfuse").touch()
                with mock.patch.dict(os.environ, {
                    "LANGFUSE_AUTOSTART": "true",
                    "LANGFUSE_STARTUP_TIMEOUT_SECONDS": "10",
                }), mock.patch(
                    "scripts.local_services.subprocess.run",
                    return_value=SimpleNamespace(returncode=0),
                ) as run, mock.patch("scripts.local_services.build_opener") as opener:
                    opener.return_value.open.return_value.__enter__.return_value.status = 200
                    state = ensure_langfuse(tmp)
                self.assertEqual(state["state"], "healthy")
                self.assertEqual(run.call_count, 2)
                _wait_child(holder)
            finally:
                if holder is not None:
                    _reap(holder)

    def test_budget_is_not_reset_after_acquiring_the_lock(self):
        from scripts.local_services import ensure_langfuse

        with tempfile.TemporaryDirectory() as tmp:
            directory = self._held_langfuse_dir(tmp)
            holder = None
            try:
                holder = _spawn_child(_LANGFUSE_HOLDER_CHILD, directory, env_overrides={
                    "P02A_HOLD_SECONDS": "0.8",
                    "LANGFUSE_AUTOSTART": "true",
                })
                self.assertTrue(_wait_marker(directory, "L_holder_acquired", (holder,), 15))
                Path(tmp, ".env.langfuse").touch()
                with mock.patch.dict(os.environ, {
                    "LANGFUSE_AUTOSTART": "true",
                    "LANGFUSE_STARTUP_TIMEOUT_SECONDS": "1",
                }), mock.patch(
                    "scripts.local_services.subprocess.run",
                    return_value=SimpleNamespace(returncode=0),
                ), mock.patch("scripts.local_services.build_opener") as opener:
                    opener.return_value.open.side_effect = OSError("health endpoint never ready")
                    started = time.monotonic()
                    state = ensure_langfuse(tmp)
                    duration = time.monotonic() - started
                self.assertEqual(state["state"], "startup_timeout")
                # 1s budget minus ~0.8s of lock waiting leaves well under 1.6s;
                # a reset post-acquisition budget would push past 1.8s.
                self.assertLess(duration, 1.6)
                _wait_child(holder)
            finally:
                if holder is not None:
                    _reap(holder)

    def test_deadline_spent_on_lock_grant_stops_before_docker(self):
        """Round-1 Codex finding, deterministic: the real FileLock acquires
        first, then the monotonic clock is already past the deadline —
        ensure_langfuse must report startup_timeout without any docker call
        (the round-1 code still ran both compose commands via max(.1, ...))."""
        from filelock import FileLock as RealFileLock

        from scripts import local_services

        clock = _ScriptedClock()
        deadline = clock.now + 10.0  # LANGFUSE_STARTUP_TIMEOUT_SECONDS below

        class BudgetSpentOnGrant:
            def __init__(self, path):
                self._real = RealFileLock(path)

            def acquire(self, timeout=None):
                self._real.acquire(timeout=timeout)
                clock.now = deadline + 1.0

            def release(self):
                self._real.release()

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, ".env.langfuse").touch()
            with mock.patch.dict(os.environ, {
                "LANGFUSE_AUTOSTART": "true",
                "LANGFUSE_STARTUP_TIMEOUT_SECONDS": "10",
            }), mock.patch("scripts.local_services.time", clock), \
                    mock.patch("scripts.local_services.FileLock", BudgetSpentOnGrant), \
                    mock.patch("scripts.local_services.subprocess.run") as run, \
                    mock.patch("scripts.local_services.build_opener") as opener:
                os.environ.pop("LANGFUSE_BASE_URL", None)
                os.environ.pop("LANGFUSE_HOST", None)
                state = local_services.ensure_langfuse(tmp)
            self.assertEqual(state["state"], "startup_timeout")
            run.assert_not_called()
            opener.assert_not_called()

    def test_first_compose_consuming_budget_skips_second_command(self):
        from scripts import local_services

        clock = _ScriptedClock()

        def first_command_burns_budget(args, **kwargs):
            clock.now += 11.0  # leaves the 10s startup deadline behind
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, ".env.langfuse").touch()
            with mock.patch.dict(os.environ, {
                "LANGFUSE_AUTOSTART": "true",
                "LANGFUSE_STARTUP_TIMEOUT_SECONDS": "10",
            }), mock.patch("scripts.local_services.time", clock), \
                    mock.patch("scripts.local_services.subprocess.run",
                               side_effect=first_command_burns_budget) as run, \
                    mock.patch("scripts.local_services.build_opener") as opener:
                os.environ.pop("LANGFUSE_BASE_URL", None)
                os.environ.pop("LANGFUSE_HOST", None)
                state = local_services.ensure_langfuse(tmp)
            self.assertEqual(state["state"], "startup_timeout")
            self.assertEqual(run.call_count, 1)
            self.assertIn("config", run.call_args.args[0])
            opener.assert_not_called()

    def test_health_probe_timeout_uses_remaining_budget_only(self):
        from scripts import local_services

        clock = _ScriptedClock()
        probe_timeouts = []

        def second_command_leaves_a_sliver(args, **kwargs):
            if run.call_count == 2:
                clock.now = 1009.95  # ~0.05s of the 10s budget left
            return SimpleNamespace(returncode=0)

        def probe_dead_endpoint(url, timeout=None):
            probe_timeouts.append(timeout)
            clock.now = 1011.0  # the failed probe attempt burns the rest
            raise OSError("health endpoint never ready")

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, ".env.langfuse").touch()
            with mock.patch.dict(os.environ, {
                "LANGFUSE_AUTOSTART": "true",
                "LANGFUSE_STARTUP_TIMEOUT_SECONDS": "10",
            }), mock.patch("scripts.local_services.time", clock), \
                    mock.patch("scripts.local_services.subprocess.run",
                               side_effect=second_command_leaves_a_sliver) as run, \
                    mock.patch("scripts.local_services.build_opener") as build_opener:
                os.environ.pop("LANGFUSE_BASE_URL", None)
                os.environ.pop("LANGFUSE_HOST", None)
                build_opener.return_value.open.side_effect = probe_dead_endpoint
                state = local_services.ensure_langfuse(tmp)
            self.assertEqual(state["state"], "startup_timeout")
            self.assertEqual(run.call_count, 2)
            self.assertEqual(len(probe_timeouts), 1)
            # Strict remainder only: the round-1 max(.1, ...) extension would
            # have handed the probe 0.1s; the raw remainder here is ~0.05s.
            self.assertGreater(probe_timeouts[0], 0.0)
            self.assertLess(probe_timeouts[0], 0.1)
