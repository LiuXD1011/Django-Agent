import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests


MAX_REMOTE_IMAGE_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS = 3
REMOTE_TIMEOUT_SECONDS = 10


class UnsafeRemoteImageError(ValueError):
    pass


def _unsafe_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_remote_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeRemoteImageError("only public HTTP/HTTPS image URLs are allowed")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))}
    except socket.gaierror as exc:
        raise UnsafeRemoteImageError("remote image host cannot be resolved") from exc
    if not addresses or any(_unsafe_address(address) for address in addresses):
        raise UnsafeRemoteImageError("remote image resolves to a blocked network")
    return url


def download_remote_image(url: str, session: requests.Session | None = None) -> tuple[bytes, str, str]:
    client = session or requests.Session()
    current = url
    for redirect_count in range(MAX_REDIRECTS + 1):
        validate_remote_url(current)
        response = client.get(current, stream=True, timeout=REMOTE_TIMEOUT_SECONDS, allow_redirects=False)
        if response.is_redirect or response.is_permanent_redirect:
            if redirect_count >= MAX_REDIRECTS:
                raise UnsafeRemoteImageError("remote image has too many redirects")
            current = urljoin(current, response.headers.get("Location", ""))
            continue
        response.raise_for_status()
        mime_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if not mime_type.startswith("image/"):
            raise UnsafeRemoteImageError("remote resource is not an image")
        chunks = []
        size = 0
        for chunk in response.iter_content(64 * 1024):
            size += len(chunk)
            if size > MAX_REMOTE_IMAGE_BYTES:
                raise UnsafeRemoteImageError("remote image exceeds 10 MiB")
            chunks.append(chunk)
        return b"".join(chunks), mime_type, current
    raise UnsafeRemoteImageError("remote image redirect failed")
