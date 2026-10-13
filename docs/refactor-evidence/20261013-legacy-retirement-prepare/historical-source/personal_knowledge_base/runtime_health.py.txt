"""Runtime health endpoints: readiness is distinct from optional capability health."""
import time

from django.db import connection
from django.http import JsonResponse

from .permissions import TENANT_ADMIN, action_response
from .view_security import tenant_required


def _health_snapshot():
    components = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        components["database"] = {"ok": True}
    except Exception:
        # Public probes never return exception text containing connection details.
        return {
            "ready": False, "healthy": False,
            "components": {"database": {"ok": False, "error": "database_unavailable"}},
        }
    try:
        # Preserve the existing deferred diagnostics imports: liveness stays dependency-free.
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        unapplied = executor.migration_plan(executor.loader.graph.leaf_nodes())
        components["migrations"] = {"ok": not unapplied, "unapplied": len(unapplied)}
    except Exception:
        components["migrations"] = {"ok": False, "error": "migration_check_failed"}
    try:
        from .search import get_vector_index_state

        state = get_vector_index_state()
        components["vector_index"] = {
            "ok": state.get("status") == "ready",
            "status": state.get("status"),
        }
    except Exception:
        components["vector_index"] = {"ok": False, "error": "vector_check_failed"}
    return {
        "ready": components["database"]["ok"] and components["migrations"]["ok"],
        "healthy": all(component["ok"] for component in components.values()),
        "components": components,
    }


def livez(request):
    return JsonResponse({"status": "alive"})


def readyz(request):
    started = time.monotonic()
    snapshot = _health_snapshot()
    return JsonResponse({
        "status": "ready" if snapshot["ready"] else "not_ready",
        "components": snapshot["components"],
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }, status=200 if snapshot["ready"] else 503)


@tenant_required
def health_components(request):
    denied = action_response(request, TENANT_ADMIN)
    if denied is not None:
        return denied
    started = time.monotonic()
    snapshot = _health_snapshot()
    return JsonResponse({
        "status": "healthy" if snapshot["healthy"] else "degraded",
        "components": snapshot["components"],
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    })
