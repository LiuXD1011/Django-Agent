#!/usr/bin/env python
import argparse
import os
import sys
from pathlib import Path

from config.bootstrap import read_legacy_config


def main():
    # During an explicit first import, preserve the legacy signing key before
    # Django loads settings; ordinary application commands never read this file.
    if len(sys.argv) > 1 and sys.argv[1] == "import_legacy_config":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--file")
        args, _ = parser.parse_known_args(sys.argv[2:])
        if args.file:
            values = read_legacy_config(args.file)
            if values.get("DJANGO_SECRET_KEY"):
                os.environ.setdefault("DJANGO_SECRET_KEY", values["DJANGO_SECRET_KEY"])
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    # Only the outer development process owns dependency startup. Never kill
    # arbitrary listeners: Django reports port conflicts without affecting them.
    if len(sys.argv) > 1 and sys.argv[1] == "runserver" and os.environ.get("RUN_MAIN") != "true":
        from scripts.local_services import ensure_langfuse
        try:
            import django
            django.setup()
            ensure_langfuse(Path(__file__).resolve().parent)
        except Exception:
            print("[Langfuse] startup_failed; application continues", flush=True)
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
