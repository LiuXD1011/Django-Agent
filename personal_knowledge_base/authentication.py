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


def authenticate_request(request):
    header = request.headers.get("Authorization", "")
    api_key = request.headers.get("X-API-Key", "")
    selected_tenant_id = request.headers.get("X-Tenant-ID")
    user = None
    tenant = None
    if header.startswith("Bearer "):
        token = header.removeprefix("Bearer ").strip()
        auth = (
            AuthToken.objects.filter(token=token, token_type="access", is_revoked=False, expires_at__gt=timezone.now())
            .select_related("user", "user__tenant")
            .first()
        )
        if auth:
            user = auth.user
            tenant = user.tenant
    elif api_key:
        tenant = Tenant.objects.filter(api_key=api_key, status="active", deleted_at__isnull=True).first()
    if user and selected_tenant_id:
        if user.can_access_all_tenants or TenantMember.objects.filter(user=user, tenant_id=selected_tenant_id, status="active").exists():
            tenant = Tenant.objects.filter(id=selected_tenant_id).first() or tenant
    return user, tenant


def require_auth(request):
    user, tenant = authenticate_request(request)
    if not user and not tenant:
        raise PermissionError("unauthorized")
    return user, tenant


def role_for(user: User | None, tenant: Tenant | None) -> str:
    if not user or not tenant:
        return "owner"
    if user.is_system_admin:
        return "owner"
    member = TenantMember.objects.filter(user=user, tenant=tenant, status="active").first()
    return member.role if member else "viewer"
