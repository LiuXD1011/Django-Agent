"""统一响应格式。"""

from django.http import JsonResponse


def ok(data=None, status=200):
    return JsonResponse({"code": 0, "data": data or {}}, status=status)


def fail(message, status=400, code=None):
    return JsonResponse({"code": code or status, "message": message}, status=status)
