#!/usr/bin/env python
import os
import sys
from pathlib import Path


def main():
    # Only the outer development process owns dependency startup. Never kill
    # arbitrary listeners: Django reports port conflicts without affecting them.
    if len(sys.argv) > 1 and sys.argv[1] == "runserver" and os.environ.get("RUN_MAIN") != "true":
        from scripts.local_services import ensure_langfuse
        try:
            ensure_langfuse(Path(__file__).resolve().parent)
        except Exception:
            print("[Langfuse] startup_failed; application continues", flush=True)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
