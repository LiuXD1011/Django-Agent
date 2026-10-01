"""MARLIN-D2 standalone desktop WSGI entry.

Serves the built frontend in a production-shaped way without touching the
generic deployment story (``config.wsgi`` / gunicorn / P01 stay unchanged):

- WhiteNoise serves ONLY ``frontend/dist/assets`` from the SOURCE root under
  ``/assets/`` with its own cross-platform MIME table (correct JS/CSS types
  even when the Windows registry guesses wrong). The Django development
  static view is never used.
- Django handles everything else: SPA deep links (``index.html`` template),
  ``/health``, JSON APIs, and authenticated ``/files`` media.
- A desktop-only boundary wrapper adds:
  * an ``X-Marlin-Desktop-Instance`` response header on every response so
    the launcher's health probe can tell its own web process apart from any
    other healthy service that might occupy the port;
  * ``Cache-Control: no-store`` on ``/api/v1/auth/*`` responses (token and
    initial-password payloads must not be cached);
  * a write boundary for browser-borne requests: non-GET/HEAD/OPTIONS
    ``/api/*`` requests that carry an ``Origin`` are accepted only for this
    machine's same origin (loopback host, same scheme ``http``, same port as
    the request's ``Host``); ``Origin: null`` and external sites are
    rejected. Requests without ``Origin`` (local CLI tools) keep working,
    and Django's ``ALLOWED_HOSTS`` continue to gate the ``Host`` header.
  * ``/api/v1/auth/auto-setup`` is restricted to POST — a GET must never be
    able to create the first account.

This wrapper exists only inside the desktop entry so the P01 global
security posture is not widened.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

AUTO_SETUP_PATH = "/api/v1/auth/auto-setup"
AUTH_PATH_PREFIX = "/api/v1/auth/"
API_PATH_PREFIX = "/api/"
LOOPBACK_NAMES = {"127.0.0.1", "localhost", "::1"}
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class DesktopBoundary:
    """WSGI wrapper implementing the desktop-specific request boundary."""

    def __init__(self, wrapped, instance_id: str | None = None):
        self.wrapped = wrapped
        self.instance_id = instance_id or os.environ.get("MARLIN_DESKTOP_INSTANCE") or secrets.token_hex(8)

    def __call__(self, environ, start_response):
        method = (environ.get("REQUEST_METHOD") or "GET").upper()
        path = environ.get("PATH_INFO") or "/"

        if path.rstrip("/") == AUTO_SETUP_PATH and method != "POST":
            return self._reject(
                start_response,
                405,
                "method_not_allowed",
                "auto setup accepts POST only",
            )

        if method in WRITE_METHODS and path.startswith(API_PATH_PREFIX):
            origin = environ.get("HTTP_ORIGIN")
            if origin is not None and not _same_origin(environ, origin):
                return self._reject(
                    start_response,
                    403,
                    "cross_origin_write_rejected",
                    "cross-origin writes are rejected in desktop mode",
                )

        def start_response_wrapper(status, headers, exc_info=None):
            headers = list(headers)
            headers.append(("X-Marlin-Desktop-Instance", self.instance_id))
            if path.startswith(AUTH_PATH_PREFIX):
                headers.append(("Cache-Control", "no-store"))
            return start_response(status, headers, exc_info)

        return self.wrapped(environ, start_response_wrapper)

    def _reject(self, start_response, status, code, message):
        reason = {403: "Forbidden", 405: "Method Not Allowed"}.get(status, "Error")
        body = json.dumps(
            {
                "success": False,
                "message": message,
                "error": {"code": code, "message": message, "details": {}},
            }
        ).encode("utf-8")
        start_response(
            "%d %s" % (status, reason),
            [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
                ("X-Marlin-Desktop-Instance", self.instance_id),
            ],
        )
        return [body]


def _effective_port(parts) -> int | None:
    """Explicit port, else the scheme default, so an implicit ``:80`` and an
    explicit ``:80`` compare equal while still meaning the same bound port."""
    if parts.port is not None:
        return parts.port
    return {"http": 80, "https": 443}.get(parts.scheme)


def _same_origin(environ, origin: str) -> bool:
    """True only for this machine's browser origin: http + the SAME loopback
    name as the request's ``Host`` (aliases count as distinct origins —
    ``localhost`` must not impersonate ``127.0.0.1`` or vice versa) + a port
    equivalent to the Host's (implicit 80 == explicit :80), which must also
    be the bound desktop port. ``Origin: null``, foreign sites, wrong ports
    and userinfo tricks are all rejected."""
    try:
        origin_parts = urlsplit(origin)
        host_parts = urlsplit("http://" + (environ.get("HTTP_HOST") or ""))
        if origin_parts.scheme != "http" or host_parts.scheme != "http":
            return False
        # Hostname comparison ignores userinfo, so reject it explicitly —
        # ``http://evil@127.0.0.1:8899`` must never match a loopback origin.
        if "@" in (origin_parts.netloc or "") or "@" in (host_parts.netloc or ""):
            return False
        origin_host = (origin_parts.hostname or "").lower()
        request_host = (host_parts.hostname or "").lower()
        if origin_host not in LOOPBACK_NAMES or request_host not in LOOPBACK_NAMES:
            return False
        if origin_host != request_host:
            return False
        origin_port = _effective_port(origin_parts)
        request_port = _effective_port(host_parts)
        if origin_port is None or origin_port != request_port:
            return False
        bound_port = os.environ.get("MARLIN_DESKTOP_PORT", "")
        if bound_port.isdigit() and origin_port != int(bound_port):
            return False
        return True
    except ValueError:
        # urlsplit/.port raise on malformed ports (:abc, out of range).
        return False


def build_application(instance_id: str | None = None, source_root=None):
    """Assemble the desktop WSGI stack (assets guard runs on every build).

    ``source_root`` anchors the built frontend; it defaults to the Django
    settings source root and exists so tests can point the stack at an
    isolated fake dist without touching the repository.
    """
    try:
        from whitenoise import WhiteNoise
    except ImportError as exc:
        raise RuntimeError(
            "waitress/whitenoise are required for desktop mode:"
            " pip install 'waitress>=3.0,<4' 'whitenoise>=6.12,<7'"
        ) from exc

    from django.conf import settings
    from django.core.wsgi import get_wsgi_application

    # Source-root anchored: the data directory never holds or serves assets.
    source_root = Path(source_root) if source_root is not None else settings.BASE_DIR
    dist_dir = Path(source_root) / "frontend" / "dist"
    assets_root = dist_dir / "assets"
    if not (assets_root.is_dir() and (dist_dir / "index.html").is_file()):
        raise RuntimeError(
            "frontend build output missing under %s — run `npm run build` in"
            " frontend/ first (desktop mode never runs npm install/build)"
            % source_root
        )

    django_app = get_wsgi_application()
    assets_app = WhiteNoise(
        django_app,
        root=str(assets_root),
        prefix="assets/",
        autorefresh=False,
        max_age=3600,
    )
    return DesktopBoundary(assets_app, instance_id=instance_id)


def __getattr__(name):
    # Built lazily so importing this module (tests, tooling) never requires a
    # built dist; the Waitress server still fails fast on first attribute
    # access when the frontend has not been built.
    if name == "application":
        return build_application()
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
