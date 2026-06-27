from django.http import JsonResponse


def ok(data=None, message: str = "success", status: int = 200, **extra):
    payload = {"success": True, "message": message}
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    return JsonResponse(payload, status=status, json_dumps_params={"ensure_ascii": False})


def fail(message: str, status: int = 400, code: str = "error", details=None):
    return JsonResponse(
        {"success": False, "error": {"code": code, "message": message, "details": details or {}}, "message": message},
        status=status,
        json_dumps_params={"ensure_ascii": False},
    )
