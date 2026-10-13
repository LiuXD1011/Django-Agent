from functools import wraps

from django.db.models import F
from django.shortcuts import get_object_or_404

from .authentication import has_tenant_access, require_auth, role_for
from .models import Chunk
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


def can_access_tenant(user, current_tenant, target_tenant):
    """An explicit revoked membership must not fall back to the primary tenant."""
    if not target_tenant or target_tenant.status != "active" or target_tenant.deleted_at is not None:
        return False
    if user is not None:
        return has_tenant_access(user, target_tenant)
    return bool(current_tenant and current_tenant.id == target_tenant.id)


def can_administer_tenant(user, current_tenant, target_tenant):
    if not user or not can_access_tenant(user, current_tenant, target_tenant):
        return False
    return role_for(user, target_tenant) in {"owner", "admin"}


def tenant_chunk_queryset(tenant):
    return Chunk.objects.filter(
        tenant=tenant,
        deleted_at__isnull=True,
        knowledge__tenant=tenant,
        knowledge__deleted_at__isnull=True,
        knowledge_base__tenant=tenant,
        knowledge_base__deleted_at__isnull=True,
        knowledge__knowledge_base__tenant=tenant,
        knowledge__knowledge_base__deleted_at__isnull=True,
        knowledge__knowledge_base_id=F("knowledge_base_id"),
    )


def tenant_chunk_or_404(tenant, **lookup):
    return get_object_or_404(tenant_chunk_queryset(tenant), **lookup)
