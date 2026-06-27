#!/usr/bin/env python
import os
import signal
import subprocess
import sys
import time


def _runserver_port(argv):
    if len(argv) < 2 or argv[1] != "runserver":
        return None
    for arg in argv[2:]:
        if arg.startswith("-"):
            continue
        target = arg.rsplit(":", 1)[-1]
        if target.isdigit():
            return int(target)
    return 8000


def _pids_on_port(port):
    commands = (
        ["lsof", "-ti", f"TCP:{port}", "-sTCP:LISTEN"],
        ["fuser", f"{port}/tcp"],
    )
    pids = set()
    for command in commands:
        try:
            output = subprocess.check_output(command, stderr=subprocess.DEVNULL, text=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
        for token in output.replace(",", " ").split():
            if token.isdigit():
                pid = int(token)
                if pid != os.getpid():
                    pids.add(pid)
    return pids


def _close_port(port):
    pids = _pids_on_port(port)
    if not pids:
        return
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.time() + 2
    while time.time() < deadline and _pids_on_port(port):
        time.sleep(0.1)
    for pid in _pids_on_port(port):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main():
    port = _runserver_port(sys.argv)
    if port == 8000:
        _close_port(port)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from pathlib import Path
    from personal_knowledge_base.startup import mirror_legacy_migration_records

    mirror_legacy_migration_records(Path(__file__).resolve().parent / "db.sqlite3")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
