"""MARLIN-D2 minimal local desktop runtime entry.

This script is the ONLY place that runs the application in explicit desktop
mode: it owns a dedicated user data directory, a persistent application
secret, the SQLite migration/backup lifecycle, and a strictly local web +
evaluation-worker process group. It is not a dev entry (``manage.py
runserver`` / ``npm run dev`` keep their own workflows) and not a packaging
or installer story.

Design boundaries (do not grow this into a framework):

- Listen address is always the explicit loopback ``127.0.0.1``.
- Runtime writes go to the chosen data directory (``APP_DATA_DIR`` /
  ``DJANGO_DB_PATH``); source resources (frontend dist, templates) are only
  ever read from the source root.
- Children are direct ``sys.executable`` ``Popen`` calls with list argv
  (never a shell), so paths with spaces are safe everywhere.
- Shutdown only ever terminates processes this entry actually spawned —
  never by port or generic process name — and always releases the instance
  lock in ``finally``.

Internal helper mode (used by this script itself, not by users)::

    python scripts/start_desktop.py _migrate --data-dir <dir>

runs Django migrations for the desktop database after taking an optional
pre-migration backup via the SQLite backup API. It prints a single
``DESKTOP_MIGRATE {...}`` JSON line on success.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

REPO_ROOT = Path(__file__).resolve().parents[1]

# Distinct exit codes so acceptance scripts can tell failure modes apart.
EXIT_OK = 0
EXIT_USAGE = 2  # bad --port / --data-dir / missing frontend dist
EXIT_INSTANCE_BUSY = 3  # another desktop instance holds the data-dir lock
EXIT_SECRET = 4  # secret file unreadable / empty-refuse / unwritable
EXIT_MIGRATE = 5  # migration (or pre-migration backup) failed
EXIT_STARTUP = 6  # web/worker early exit, health mismatch or startup timeout

DEFAULT_PORT = 8899
DEFAULT_STARTUP_TIMEOUT = 60.0
# Bounded terminate→wait→kill grace for processes this entry owns.
STOP_GRACE_SECONDS = 10.0
MIGRATE_TIMEOUT_SECONDS = 600.0
LISTEN_HOST = "127.0.0.1"
INSTANCE_LOCK_NAME = "instance.lock"
SECRET_FILE_NAME = "secret.key"
BACKUP_DIR_NAME = "backups"
DB_FILE_NAME = "db.sqlite3"
# Marker printed by the internal migrate child; parent parses this line.
MIGRATE_MARKER = "DESKTOP_MIGRATE "


class DesktopError(Exception):
    """Fatal, user-facing desktop startup failure (maps to an exit code)."""

    def __init__(self, message: str, exit_code: int):
        super().__init__(message)
        self.exit_code = exit_code


# ---------------------------------------------------------------------------
# Pure resolution helpers (unit-tested without spawning anything)
# ---------------------------------------------------------------------------

def default_data_dir(platform: str = sys.platform, env: dict | None = None) -> Path:
    """Platform default for the desktop user data directory.

    Windows: ``%LOCALAPPDATA%\\Marlin`` (missing LOCALAPPDATA is a hard
    error — never guess another location). Other platforms: ``$XDG_DATA_HOME``
    or ``~/.local/share``, then ``/marlin``.
    """
    env = os.environ if env is None else env
    if platform == "win32":
        local_app_data = (env.get("LOCALAPPDATA") or "").strip()
        if not local_app_data:
            raise DesktopError(
                "LOCALAPPDATA is not set; pass --data-dir explicitly", EXIT_USAGE
            )
        return Path(local_app_data) / "Marlin"
    xdg = (env.get("XDG_DATA_HOME") or "").strip()
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "marlin"


def validate_port(value: str | int | None) -> int:
    """Parse and range-check --port (1..65535)."""
    try:
        port = int(str(value))
    except (TypeError, ValueError):
        raise DesktopError("invalid --port %r: must be an integer" % (value,), EXIT_USAGE)
    if not 1 <= port <= 65535:
        raise DesktopError("invalid --port %d: must be within 1..65535" % port, EXIT_USAGE)
    return port


def dist_assets_dir(source_root: Path) -> Path:
    """Locate the built frontend under the SOURCE root (never the data dir)."""
    dist = Path(source_root) / "frontend" / "dist"
    index = dist / "index.html"
    assets = dist / "assets"
    if not (index.is_file() and assets.is_dir()):
        raise DesktopError(
            "frontend build output not found under %s (need frontend/dist/index.html"
            " and frontend/dist/assets/). Build it first with `npm run build` in"
            " frontend/; this desktop entry never runs npm install/build itself."
            % Path(source_root),
            EXIT_USAGE,
        )
    return assets


def web_command(source_root: Path, port: int) -> list[str]:
    """Waitress argv for the desktop web child (explicit loopback listen)."""
    return [
        sys.executable,
        "-m",
        "waitress",
        "--listen=%s:%d" % (LISTEN_HOST, port),
        "--threads=4",
        "--ident=marlin-desktop",
        "config.desktop_wsgi:application",
    ]


def worker_command(source_root: Path) -> list[str]:
    """Task worker argv. Evaluation queue only: document tasks are executed
    by the web process's existing in-process queue mechanism."""
    return [
        sys.executable,
        str(Path(source_root) / "manage.py"),
        "run_task_worker",
        "--queue",
        "evaluation",
    ]


def migrate_command(source_root: Path, data_dir: Path) -> list[str]:
    return [
        sys.executable,
        str(Path(source_root) / "scripts" / "start_desktop.py"),
        "_migrate",
        "--data-dir",
        str(data_dir),
    ]


def build_desktop_env(
    data_dir: Path,
    db_path: Path,
    secret: str,
    port: int,
    instance_id: str,
    base_env: dict | None = None,
) -> dict:
    """Environment forced onto every desktop child process.

    - ``DJANGO_DEBUG=false`` and the loopback host list are always forced.
    - ``LANGFUSE_AUTOSTART`` is always false (repo .env cannot re-enable it;
      settings' load_dotenv only fills keys absent from the environment).
    - ``NEO4J_ENABLE`` / ``LANGFUSE_ENABLED`` default to false but keep an
      explicit opt-in from the launching user's process environment.
    - ``ALLOW_AUTO_SETUP`` is enabled here and ONLY here; global .env /
      generic deployments keep the default-off behavior.
    """
    base_env = os.environ if base_env is None else base_env
    env = dict(base_env)
    pythonpath = str(REPO_ROOT)
    existing = env.get("PYTHONPATH")
    if existing:
        pythonpath = pythonpath + os.pathsep + existing
    env.update(
        {
            "PYTHONPATH": pythonpath,
            "PYTHONDONTWRITEBYTECODE": "1",
            "DJANGO_SETTINGS_MODULE": "config.settings",
            "DJANGO_DEBUG": "false",
            "DJANGO_ALLOWED_HOSTS": "127.0.0.1,localhost",
            "DJANGO_SECRET_KEY": secret,
            "APP_DATA_DIR": str(data_dir),
            "DJANGO_DB_PATH": str(db_path),
            "LANGFUSE_AUTOSTART": "false",
            "NEO4J_ENABLE": env.get("NEO4J_ENABLE", "false"),
            "LANGFUSE_ENABLED": env.get("LANGFUSE_ENABLED", "false"),
            "ALLOW_AUTO_SETUP": "true",
            "MARLIN_DESKTOP_INSTANCE": instance_id,
            "MARLIN_DESKTOP_PORT": str(port),
        }
    )
    return env


# ---------------------------------------------------------------------------
# Secret handling (created/read only by this desktop entry)
# ---------------------------------------------------------------------------

def ensure_secret(data_dir: Path) -> str:
    """Return the persistent application secret for ``data_dir``.

    - Missing file: generate and write atomically (tmp + ``os.replace``).
      The tmp file is created private (0600) from the very first byte via
      ``os.open`` — never written 0644 and chmod'ed afterwards. POSIX only:
      on Windows the mode is best effort and is NOT an ACL guarantee.
    - Existing non-empty file: reuse; never regenerate over it, never log it.
    - Existing empty file: hard error — refuse to replace silently.

    Any failure raises ``DesktopError``; the on-disk secret is never printed.
    """
    path = Path(data_dir) / SECRET_FILE_NAME
    try:
        if path.exists():
            current = path.read_text(encoding="utf-8").strip()
            if not current:
                raise DesktopError(
                    "secret file %s exists but is empty; refusing to replace it"
                    " silently — delete it deliberately if you accept invalidating"
                    " existing sessions" % path,
                    EXIT_SECRET,
                )
            return current
        generated = secrets.token_urlsafe(64)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + (".tmp-%d" % os.getpid()))
        try:
            descriptor = os.open(
                str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(generated)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()
        return generated
    except DesktopError:
        raise
    except OSError as exc:
        raise DesktopError("cannot read/write secret file %s: %s" % (path, exc), EXIT_SECRET)


# ---------------------------------------------------------------------------
# Instance lock (one desktop instance per data directory)
# ---------------------------------------------------------------------------

class InstanceLock:
    """Non-blocking dedicated user-dir lock; never deletes data or lock files."""

    def __init__(self, data_dir: Path):
        from filelock import FileLock

        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = Path(data_dir) / INSTANCE_LOCK_NAME
        self._lock = FileLock(str(self.path), mode=0o600)
        self.acquired = False

    def acquire(self) -> None:
        from filelock import Timeout

        try:
            self._lock.acquire(timeout=0)
        except Timeout as exc:
            raise DesktopError(
                "another desktop instance appears to be running for data"
                " directory %s (lock: %s). Close it first; this entry never"
                " deletes data or lock files to bypass the conflict." % (self.path.parent, self.path),
                EXIT_INSTANCE_BUSY,
            ) from exc
        except OSError as exc:
            raise DesktopError(
                "cannot create instance lock %s: %s" % (self.path, exc), EXIT_USAGE
            ) from exc
        self.acquired = True

    def release(self) -> None:
        if self.acquired:
            try:
                self._lock.release()
            finally:
                self.acquired = False


# ---------------------------------------------------------------------------
# Child process lifecycle (only processes this entry actually spawned)
# ---------------------------------------------------------------------------

def _stop_process(process: subprocess.Popen, grace: float = STOP_GRACE_SECONDS) -> None:
    """terminate → bounded wait → kill for ONE process we own, then reap."""
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    process.kill()
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        print("[desktop] warning: child pid %s ignored kill" % process.pid, flush=True)


def stop_group(children: dict[str, subprocess.Popen]) -> None:
    """Stop EVERY child even when one cleanup raises, then re-raise the first
    error so callers still learn about the incomplete shutdown."""
    first_error: BaseException | None = None
    for process in list(children.values()):
        try:
            _stop_process(process)
        except Exception as exc:
            print("[desktop] warning: error while stopping a child: %r" % exc, flush=True)
            if first_error is None:
                first_error = exc
    children.clear()
    if first_error is not None:
        raise first_error


def _spawn(label: str, argv: list[str], env: dict, cwd: Path,
           stdout, stderr) -> subprocess.Popen:
    print("[desktop] starting %s: %s" % (label, " ".join(argv[:4]) + " …"), flush=True)
    return subprocess.Popen(
        argv,
        cwd=str(cwd),
        env=env,
        stdout=stdout,
        stderr=stderr,
        stdin=subprocess.DEVNULL,
    )


def probe_health(port: int, instance_id: str, deadline: float) -> bool:
    """True only when OUR web answered: HTTP 200 from /health AND the random
    per-launch instance header matches. System proxies are disabled so the
    probe can never be answered (or swallowed) by an external proxy. The HTTP
    timeout is the REAL remaining budget — never a floor that would outlive
    the deadline."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return False
    opener = build_opener(ProxyHandler({}))  # never use system proxies
    try:
        with opener.open(
            "http://%s:%d/health" % (LISTEN_HOST, port), timeout=min(2.0, remaining)
        ) as response:
            if response.status != 200:
                return False
            return response.headers.get("X-Marlin-Desktop-Instance") == instance_id
    except OSError:
        return False
    except Exception:
        return False


def wait_healthy(children: dict[str, subprocess.Popen], port: int,
                 instance_id: str, startup_timeout: float) -> bool:
    """Poll until OUR web is healthy. A child that already exited fails the
    group immediately instead of waiting out the deadline; the HTTP probe and
    the sleep both stay inside the real remaining budget."""
    deadline = time.monotonic() + startup_timeout
    while True:
        for label, process in children.items():
            if process.poll() is not None:
                print("[desktop] %s exited early (code %s) during startup"
                      % (label, process.returncode), flush=True)
                return False
        if probe_health(port, instance_id, deadline):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print("[desktop] startup timeout: our web instance was not healthy on"
                  " %s:%d within %.0fs (port occupied by something else, or"
                  " startup too slow)" % (LISTEN_HOST, port, startup_timeout), flush=True)
            return False
        time.sleep(min(0.25, remaining))


# ---------------------------------------------------------------------------
# Migration child (internal mode) + parent-side runner
# ---------------------------------------------------------------------------

def _run_migrate_mode(data_dir: Path) -> int:
    """Internal ``_migrate`` mode: plan check → SQLite-backup if needed → migrate."""
    data_dir = Path(os.path.abspath(data_dir.expanduser()))
    # App configs read sys.argv while django.setup() imports them (the task
    # recovery timers key on "test" being present); announce a plain manage.py
    # migrate BEFORE any Django import so no timer starts into the migration.
    sys.argv = ["manage.py", "migrate"]
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.core.management import call_command
    from django.db import connections
    from django.db.migrations.executor import MigrationExecutor

    db_path = Path(connections["default"].settings_dict["NAME"])
    # Record existence BEFORE creating the executor: migration planning opens
    # the database and materialises an empty SQLite file on a fresh install,
    # which must never be mistaken for "existing database to back up".
    db_existed = db_path.exists()
    backups_dir = data_dir / BACKUP_DIR_NAME
    connection = connections["default"]
    executor = MigrationExecutor(connection)
    targets = executor.loader.graph.leaf_nodes()
    pending = bool(executor.migration_plan(targets))

    backup_path = None
    if pending and db_existed:
        backups_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backups_dir / (
            "pre-migrate-%s-%d.sqlite3" % (time.strftime("%Y%m%d-%H%M%S"), os.getpid())
        )
        source = sqlite3.connect(str(db_path))
        try:
            target = sqlite3.connect(str(backup_path))
            try:
                with target:
                    source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
        if not backup_path.is_file() or backup_path.stat().st_size == 0:
            print("[desktop] pre-migration backup failed for %s" % db_path, file=sys.stderr)
            return EXIT_MIGRATE
        print("[desktop] pre-migration backup: %s" % backup_path, flush=True)

    call_command("migrate", "--noinput", verbosity=1)
    print(MIGRATE_MARKER + json.dumps({"backup": backup_path and str(backup_path)}), flush=True)
    return EXIT_OK


def run_migrations(source_root: Path, data_dir: Path, env: dict,
                   timeout: float = MIGRATE_TIMEOUT_SECONDS,
                   migrate_argv: list[str] | None = None) -> None:
    """Run the migrate child; raise DesktopError(EXIT_MIGRATE) on any failure.
    Migrations must succeed before web/worker are spawned."""
    argv = migrate_argv or migrate_command(source_root, data_dir)
    print("[desktop] starting migrations: %s …" % " ".join(str(p) for p in argv[:4]), flush=True)
    try:
        process = subprocess.Popen(
            argv,
            cwd=str(source_root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            stdin=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise DesktopError("cannot start migration process: %s" % exc, EXIT_MIGRATE)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _stop_process(process)
        raise DesktopError(
            "migrations did not finish within %.0fs; web and worker were not started"
            % timeout,
            EXIT_MIGRATE,
        )
    except BaseException:
        # KeyboardInterrupt/SystemExit while the migrate child runs: reap the
        # child this entry owns before the interrupt propagates.
        _stop_process(process)
        raise
    if process.returncode != 0:
        tail = "\n".join((stderr or stdout or "").splitlines()[-15:])
        raise DesktopError(
            "migration failed (exit %s); web and worker were not started.\n%s"
            % (process.returncode, tail),
            EXIT_MIGRATE,
        )
    print("[desktop] migrations applied", flush=True)


# ---------------------------------------------------------------------------
# stdin watcher: shut down gracefully when our launching console/pipe goes away
# ---------------------------------------------------------------------------

def _stdin_watchable(stream) -> bool:
    """Watch stdin EOF only for pipes/regular files. A tty (interactive use)
    or character device like /dev/null (common for unattended launches) must
    not trigger an instant shutdown."""
    try:
        mode = os.fstat(stream.fileno()).st_mode
    except (OSError, ValueError, AttributeError):
        return False
    return stat.S_ISFIFO(mode) or stat.S_ISREG(mode)


def _watch_stdin(shutdown_requested: threading.Event) -> None:
    try:
        while not shutdown_requested.is_set():
            chunk = sys.stdin.read(1)
            if chunk:
                continue
            print("[desktop] stdin closed; shutting down", flush=True)
            shutdown_requested.set()
            return
    except (OSError, ValueError):
        return


# ---------------------------------------------------------------------------
# Main desktop orchestration
# ---------------------------------------------------------------------------

def run_desktop(
    *,
    data_dir: Path | str | None = None,
    port: int | str | None = None,
    open_browser: bool = True,
    base_env: dict | None = None,
    source_root: Path | str = REPO_ROOT,
    startup_timeout: float = DEFAULT_STARTUP_TIMEOUT,
    migrate_argv: list[str] | None = None,
    web_argv: list[str] | None = None,
    worker_argv: list[str] | None = None,
    child_stdout=None,
    child_stderr=None,
) -> int:
    """Run the desktop process group to completion; returns the exit code.

    The keyword parameters past ``open_browser`` are internal seams for the
    runtime tests (real subprocesses are still used); normal users only need
    ``data_dir`` / ``port`` / ``open_browser``.
    """
    source_root = Path(source_root)
    try:
        port = validate_port(port if port is not None else DEFAULT_PORT)
        dist_assets_dir(source_root)  # fail before spawning anything
        data_dir = Path(data_dir) if data_dir is not None else default_data_dir(env=base_env)
        # Absolute BEFORE anything consumes it: children run with cwd=source
        # root, so a relative --data-dir must be pinned to this launcher's
        # working directory once and shared by env/lock/secret/DB alike.
        data_dir = Path(os.path.abspath(data_dir.expanduser()))
        if data_dir.exists() and not data_dir.is_dir():
            raise DesktopError("--data-dir %s exists and is not a directory" % data_dir, EXIT_USAGE)
    except DesktopError as exc:
        print("[desktop] error: %s" % exc, flush=True)
        return exc.exit_code

    lock = InstanceLock(data_dir)
    children: dict[str, subprocess.Popen] = {}
    shutdown_requested = threading.Event()
    instance_id = secrets.token_hex(8)
    try:
        try:
            lock.acquire()
        except DesktopError as exc:
            print("[desktop] error: %s" % exc, flush=True)
            return exc.exit_code
        print("[desktop] instance %s | data dir: %s | http://%s:%d"
              % (instance_id, data_dir, LISTEN_HOST, port), flush=True)

        try:
            # The persistent secret is created/read only while this instance
            # holds the data-dir lock.
            secret = ensure_secret(data_dir)
            env = build_desktop_env(
                data_dir, data_dir / DB_FILE_NAME, secret, port, instance_id, base_env
            )
            run_migrations(source_root, data_dir, env, migrate_argv=migrate_argv)
            children["web"] = _spawn(
                "web (waitress)", web_argv or web_command(source_root, port),
                env, source_root, child_stdout, child_stderr,
            )
            try:
                children["worker"] = _spawn(
                    "worker (evaluation queue)",
                    worker_argv or worker_command(source_root),
                    env, source_root, child_stdout, child_stderr,
                )
            except OSError:
                stop_group(children)
                raise
        except DesktopError as exc:
            print("[desktop] error: %s" % exc, flush=True)
            return exc.exit_code

        if not wait_healthy(children, port, instance_id, startup_timeout):
            return EXIT_STARTUP

        print("[desktop] ready on http://%s:%d (Ctrl+C to stop)"
              % (LISTEN_HOST, port), flush=True)
        if open_browser:
            try:
                import webbrowser

                webbrowser.open("http://%s:%d" % (LISTEN_HOST, port))
            except Exception as exc:
                print("[desktop] browser open skipped: %s" % exc, flush=True)

        if _stdin_watchable(sys.stdin):
            threading.Thread(
                target=_watch_stdin, args=(shutdown_requested,), daemon=True
            ).start()

        try:
            while True:
                if shutdown_requested.is_set():
                    print("[desktop] stopping…", flush=True)
                    break
                for label, process in children.items():
                    if process.poll() is not None:
                        print("[desktop] %s exited unexpectedly (code %s); stopping"
                              " the remaining processes" % (label, process.returncode),
                              flush=True)
                        return EXIT_STARTUP
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("[desktop] stopping…", flush=True)
        return EXIT_OK
    finally:
        shutdown_requested.set()
        try:
            stop_group(children)
        except Exception as exc:
            # A cleanup error must never skip the lock release below.
            print("[desktop] warning: child cleanup incomplete: %r" % exc, flush=True)
        finally:
            lock.release()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "_migrate":
        parser = argparse.ArgumentParser(prog="start_desktop.py _migrate")
        parser.add_argument("--data-dir", required=True)
        args = parser.parse_args(argv[1:])
        return _run_migrate_mode(Path(args.data_dir).expanduser())

    parser = argparse.ArgumentParser(
        prog="python scripts/start_desktop.py",
        description=(
            "Local desktop runtime (explicit desktop mode only): serves the built"
            " frontend over Waitress on 127.0.0.1 plus the evaluation task worker,"
            " with all runtime data in a dedicated user directory."
        ),
    )
    parser.add_argument("--data-dir", default=None,
                        help="data directory (default: %%LOCALAPPDATA%%/Marlin on Windows,"
                             " $XDG_DATA_HOME or ~/.local/share/marlin elsewhere)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="TCP port, 1..65535 (default %d, always bound to 127.0.0.1)" % DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true",
                        help="do not open the system browser (for unattended runs)")
    args = parser.parse_args(argv)
    return run_desktop(
        data_dir=args.data_dir,
        port=args.port,
        open_browser=not args.no_browser,
    )


if __name__ == "__main__":
    # Graceful stop when a supervisor sends SIGTERM (POSIX); Ctrl+C arrives as
    # KeyboardInterrupt everywhere. Children/lock cleanup lives in run_desktop's
    # finally blocks and therefore runs for both paths.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    sys.exit(main())
