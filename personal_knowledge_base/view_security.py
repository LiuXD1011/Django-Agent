from functools import wraps

from django.shortcuts import get_object_or_404

from .authentication import require_auth
from .responses import fail


def tenant_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            user, tenant = require_auth(request)
        except PermissionError:
            return fail("unauthorized", 401, "unauthorized")
        if tenant is None:
            return fail("unauthorized", 401, "unauthorized")
        request.auth_user = user
        request.auth_tenant = tenant
        return view(request, *args, **kwargs)

    return wrapped


def tenant_object_or_404(model_or_qs, tenant, **lookup):
    return get_object_or_404(model_or_qs, tenant=tenant, **lookup)
