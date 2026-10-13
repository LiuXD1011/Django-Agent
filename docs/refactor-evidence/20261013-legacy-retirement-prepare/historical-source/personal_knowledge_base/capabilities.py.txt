"""Public protocol capabilities; no database or credential details."""
import os
import uuid

from filelock import FileLock, Timeout

from config.runtime_paths import app_data_root
from .responses import fail, ok


def service_id():
    directory = app_data_root() / ".settings"
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    path = directory / "service-id"
    with FileLock(str(directory / "service-id.lock"), timeout=5):
        if path.exists():
            return str(uuid.UUID(path.read_text(encoding="utf8").strip()))
        value = str(uuid.uuid4())
        temporary = directory / f"service-id-{os.getpid()}.tmp"
        try:
            fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="utf8") as stream:
                stream.write(value + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return value


def capabilities(request):
    if request.method != "GET":
        return fail("method not allowed", 405, "method_not_allowed")
    try:
        identity = service_id()
    except (OSError, ValueError, Timeout):
        return fail("service identity unavailable", 503, "service_identity_unavailable")
    response = ok({
        "service_id": identity, "api_version": "v1", "client_protocol": 1,
        "client_protocol_min": 1, "client_protocol_max": 1, "recovery_epoch": 1,
        "auth_modes": ["cookie", "legacy_bearer"],
        "features": {
            "personal_spaces": True, "device_sessions": True,
            "incremental_sync": False, "durable_generations": False, "native_clients": False,
        },
        # The current ingestion endpoint has no file-byte limit contract yet.
        # Django's memory threshold is NOT a maximum permitted upload size.
        "limits": {"max_upload_bytes": None},
    })
    response["Cache-Control"] = "no-store"
    return response
