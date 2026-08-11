from functools import wraps

from django.db.models import F
from django.shortcuts import get_object_or_404

from .authentication import require_auth, role_for
from .models import Chunk, TenantMember
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
    """Return whether an authenticated principal may address target_tenant."""
    if not target_tenant:
        return False
    if current_tenant and current_tenant.id == target_tenant.id:
        return True
    if user and (user.is_system_admin or user.can_access_all_tenants):
        return True
    return bool(
        user
        and TenantMember.objects.filter(user=user, tenant=target_tenant, status="active").exists()
    )


def can_administer_tenant(user, current_tenant, target_tenant):
    if not can_access_tenant(user, current_tenant, target_tenant):
        return False
    if not user:
        return bool(current_tenant and current_tenant.id == target_tenant.id)
    if user.is_system_admin or user.can_access_all_tenants:
        return True
    if user.tenant_id == target_tenant.id and not TenantMember.objects.filter(
        user=user, tenant=target_tenant, status="active"
    ).exists():
        return True
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
