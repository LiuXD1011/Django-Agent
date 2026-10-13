import secrets
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from .models import AuthToken, Tenant, TenantMember, User


TOKEN_TTL = timedelta(hours=8)
REFRESH_TTL = timedelta(days=30)


def hash_password(raw: str) -> str:
    return make_password(raw)


def verify_password(raw: str, encoded: str) -> bool:
    return check_password(raw, encoded)


def issue_tokens(user: User) -> tuple[str, str]:
    token = secrets.token_urlsafe(36)
    refresh = secrets.token_urlsafe(48)
    AuthToken.objects.create(user=user, token=token, token_type="access", expires_at=timezone.now() + TOKEN_TTL)
    AuthToken.objects.create(user=user, token=refresh, token_type="refresh", expires_at=timezone.now() + REFRESH_TTL)
    return token, refresh


def has_tenant_access(user, tenant) -> bool:
    """Active principals only; an explicit revoked membership defeats legacy fallback."""
    if tenant is None or tenant.status != "active" or tenant.deleted_at is not None:
        return False
    if user is None or not user.is_active or user.deleted_at is not None:
        return False
    if tenant.space_type == "personal":
        return user.id == tenant.personal_owner_id and TenantMember.objects.filter(
            user=user, tenant=tenant, status="active", deleted_at__isnull=True,
        ).exists()
    if user.is_system_admin or user.can_access_all_tenants:
        return True
    member = TenantMember.objects.filter(user=user, tenant=tenant).first()
    if member is not None:
        return member.status == "active" and member.deleted_at is None
    # Preserve existing single-tenant accounts which never had a membership row.
    return user.tenant_id == tenant.id


def authenticate_request(request):
    header = request.headers.get("Authorization", "")
    api_key = request.headers.get("X-API-Key", "")
    selected_tenant_id = request.headers.get("X-Tenant-ID")
    user = None
    tenant = None
    if header.startswith("Bearer "):
        token = header.removeprefix("Bearer ").strip()
        # 禁用用户的既有 token 立即失效：用户状态进入认证谓词，而非只在登录时检查。
        auth = (
            AuthToken.objects.filter(
                token=token, token_type="access", is_revoked=False,
                expires_at__gt=timezone.now(), user__is_active=True,
                deleted_at__isnull=True, user__deleted_at__isnull=True,
            )
            .select_related("user", "user__tenant")
            .first()
        )
        if auth:
            user = auth.user
            tenant = user.tenant
    elif api_key:
        tenant = Tenant.objects.filter(api_key=api_key, status="active", deleted_at__isnull=True).first()
    elif not header:
        # Import lazily to avoid a cycle with accounts views and Django app loading.
        from accounts.device_sessions import authenticate_device
        device = authenticate_device(request)
        if device:
            user = device.user
            tenant = user.tenant
    if user:
        if selected_tenant_id:
            try:
                tenant = Tenant.objects.filter(id=selected_tenant_id).first()
            except (TypeError, ValueError):
                tenant = None
        # An explicit invalid selector never silently changes the request's tenant.
        if not has_tenant_access(user, tenant):
            return None, None
    return user, tenant


def require_auth(request):
    user, tenant = authenticate_request(request)
    if not user and not tenant:
        raise PermissionError("unauthorized")
    return user, tenant


def role_for(user: User | None, tenant: Tenant | None) -> str:
    from .permissions import principal_role

    return principal_role(user, tenant)
