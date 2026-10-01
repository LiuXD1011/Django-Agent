"""Runtime data-root resolution shared by Django settings and plain scripts.

``APP_DATA_DIR`` lets a deployment whose installation directory is read-only
(Windows Program Files) redirect every runtime write — database, media,
staticfiles and the ``.cache`` families — to a separate user data root, while
source resources (templates, frontend dist, dataset manifests, .env /
docker-compose) keep being read from the source ``BASE_DIR``.

The module itself is pure standard library so non-Django callers
(``scripts.local_services``) can import it without pulling in Django; the
settings-aware helpers import ``django.conf`` lazily inside the function body
and re-read settings on every call.  That laziness is the contract:
``override_settings(BASE_DIR=...)`` isolation tests keep redirecting runtime
writes, so no path is frozen at import time.  Nothing here creates
directories, migrates old data or touches the working directory.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["resolve_data_directory", "app_data_root", "runtime_cache_dir"]


def resolve_data_directory(base, value=None) -> Path:
    """Resolve the writable data root for ``base`` plus an optional override.

    ``value`` comes from an env/.env layer and may be ``None``, empty or
    whitespace — all mean "unspecified" and fall back to ``base`` (the
    historical behavior).  An explicit value is expanded (``~``) and resolved
    to an absolute path; relative values resolve against the current working
    directory, which is never changed here.
    """
    base_path = Path(base)
    if value is None:
        return base_path
    text = str(value).strip()
    if not text:
        return base_path
    return Path(text).expanduser().resolve()


def app_data_root() -> Path:
    """Current writable data root of the running Django process.

    ``settings.APP_DATA_DIR`` is ``None`` when the env was unspecified, so
    the root falls back to the *current* ``settings.BASE_DIR`` — an override
    applied after settings load keeps steering runtime writes.
    """
    from django.conf import settings

    return resolve_data_directory(
        settings.BASE_DIR,
        getattr(settings, "APP_DATA_DIR", None),
    )


def runtime_cache_dir(*parts: str) -> Path:
    """Directory for runtime artifacts under the data root's ``.cache``."""
    return app_data_root().joinpath(".cache", *parts)
