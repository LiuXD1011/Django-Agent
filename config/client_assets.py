"""Serve only known public client build artifacts, never user uploads."""
import re

from django.conf import settings
from django.http import FileResponse, Http404
from django.views.decorators.http import require_safe

_FIXED = {
    "manifest": {"manifest.webmanifest"},
    "worker": {"sw.js"},
    "icon": {"icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png"},
}
_SUBDIR = {"icon": "icons", "shell": "pwa-shell", "asset": "assets"}


@require_safe
def client_asset(request, name, kind):
    if kind in _FIXED:
        allowed = name in _FIXED[kind]
    elif kind == "shell":
        allowed = re.fullmatch(r"shell-[0-9a-f]{20}\.html", name) is not None
    elif kind == "asset":
        allowed = re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]+\.(?:js|css|woff2?|ttf|otf|png|jpg|jpeg|svg|webp|gif|ico)", name) is not None
    else:
        allowed = False
    if not allowed:
        raise Http404
    directory = (settings.BASE_DIR / "frontend" / "dist").resolve()
    path = directory / _SUBDIR[kind] / name if kind in _SUBDIR else directory / name
    path = path.resolve()
    if not path.is_relative_to(directory) or not path.is_file():
        raise Http404
    content_type = {
        "worker": "text/javascript", "manifest": "application/manifest+json",
        "shell": "text/html", "icon": "image/png",
    }.get(kind)
    response = FileResponse(path.open("rb"), content_type=content_type)
    fingerprinted = kind == "shell" or (kind == "asset" and re.search(r"-[A-Za-z0-9_-]{8,}\.", name) is not None)
    response["Cache-Control"] = "public, max-age=31536000, immutable" if fingerprinted else "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    if kind == "worker":
        response["Service-Worker-Allowed"] = "/"
    return response
