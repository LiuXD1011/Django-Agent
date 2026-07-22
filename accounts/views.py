import fcntl
import hashlib
import json
import os
import secrets
import tempfile
from contextlib import contextmanager

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import connections, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from personal_knowledge_base.authentication import hash_password, issue_tokens, require_auth, verify_password
from personal_knowledge_base.models import (
    AuditLog,
    AuthToken,
    Tenant,
    TenantMember,
    User,
)
from personal_knowledge_base.responses import fail, ok
from personal_knowledge_base.serializers import (
    membership_dict,
    tenant_dict,
    user_dict,
)


# ---------------------------------------------------------------------------
# Internal helpers (moved from personal_knowledge_base.views)
# ---------------------------------------------------------------------------

def parse_body(request):
    if request.content_type and request.content_type.startswith("multipart/"):
        return request.POST.dict()
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except Exception:
        return {}


def auth_context(request):
    try:
        return require_auth(request)
    except PermissionError:
        return None, None


TENANT_KV_FIELDS = {
    "agent-config": "agent_config",
    "agent_config": "agent_config",
    "context-config": "context_config",
    "context_config": "context_config",
    "conversation-config": "conversation_config",
    "conversation_config": "conversation_config",
    "web-search-config": "web_search_config",
    "web_search_config": "web_search_config",
    "parser-engine-config": "parser_engine_config",
    "parser_engine_config": "parser_engine_config",
    "storage-engine-config": "storage_engine_config",
    "storage_engine_config": "storage_engine_config",
    "chat-history-config": "chat_history_config",
    "chat_history_config": "chat_history_config",
    "retrieval-config": "retrieval_config",
    "retrieval_config": "retrieval_config",
    "prompt-templates": "credentials",
}


# ---------------------------------------------------------------------------
# Auth views
# ---------------------------------------------------------------------------


def _sqlite_auto_setup_lock_path(database_name):
    database_key = os.fspath(database_name)
    if database_key != ":memory:" and not database_key.startswith("file:"):
        database_key = os.path.realpath(database_key)
    digest = hashlib.sha256(os.fsencode(database_key)).hexdigest()[:24]
    return os.path.join(tempfile.gettempdir(), f"django-agent-auto-setup-{digest}.lock")


@contextmanager
def _auto_setup_gate():
    database_alias = User.objects.db
    database = connections[database_alias]

    if database.features.has_select_for_update:
        with transaction.atomic(using=database_alias):
            ContentType.objects.using(database_alias).select_for_update().get(
                app_label=User._meta.app_label,
                model=User._meta.model_name,
            )
            yield
        return

    if database.vendor == "sqlite":
        lock_fd = os.open(
            _sqlite_auto_setup_lock_path(database.settings_dict["NAME"]),
            os.O_CREAT | os.O_RDWR,
            0o600,
        )
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            with transaction.atomic(using=database_alias):
                yield
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        return

    with transaction.atomic(using=database_alias):
        yield


@csrf_exempt
def auth_register(request):
    data = parse_body(request)
    username = data.get("username") or data.get("email", "").split("@")[0] or f"user-{secrets.token_hex(3)}"
    email = data.get("email") or f"{username}@local"
    password = data.get("password")
    if not password:
        return fail("password is required", 400)
    if User.objects.filter(Q(username=username) | Q(email=email)).exists():
        return fail("user already exists", 409, "user_exists")
    tenant = Tenant.objects.create(name=f"{username} 的空间", api_key=secrets.token_urlsafe(24), business="default")
    user = User.objects.create(username=username, email=email, password_hash=hash_password(password), tenant=tenant)
    TenantMember.objects.create(user=user, tenant=tenant, role="owner")
    token, refresh = issue_tokens(user)
    return ok({"user": user_dict(user), "tenant": tenant_dict(tenant), "token": token, "refresh_token": refresh}, status=201)


@csrf_exempt
def auth_auto_setup(request):
    if not settings.ALLOW_AUTO_SETUP:
        return fail("auto setup is disabled", 401, "auto_setup_disabled")

    with _auto_setup_gate():
        if User.objects.exists():
            return fail("setup already completed", 401, "setup_already_completed")

        random_password = secrets.token_urlsafe(12)
        request._body = json.dumps({"username": "admin", "email": "admin@knowledge.local", "password": random_password}).encode()
        response = auth_register(request)

    # 在响应中添加临时密码提示
    if hasattr(response, 'content'):
        try:
            data = json.loads(response.content)
            if 'data' in data:
                data['data']['temp_password'] = random_password
                data['data']['require_password_change'] = True
                response.content = json.dumps(data).encode()
        except Exception:
            pass
    return response


@csrf_exempt
def auth_login(request):
    data = parse_body(request)
    login = data.get("email") or data.get("username") or ""
    user = User.objects.filter(Q(email=login) | Q(username=login), deleted_at__isnull=True).first()
    if not user or not verify_password(data.get("password", ""), user.password_hash):
        return fail("invalid credentials", 401, "invalid_credentials")
    token, refresh = issue_tokens(user)
    tenant = user.tenant
    memberships = [membership_dict(m) for m in TenantMember.objects.filter(user=user, status="active")]
    return ok({"user": user_dict(user), "tenant": tenant_dict(tenant), "token": token, "refresh_token": refresh, "memberships": memberships})


@csrf_exempt
def auth_refresh(request):
    data = parse_body(request)
    token = data.get("refresh_token") or data.get("refreshToken") or data.get("token")
    auth = AuthToken.objects.filter(token=token, token_type="refresh", is_revoked=False, expires_at__gt=timezone.now()).select_related("user").first()
    if not auth:
        return fail("invalid refresh token", 401, "invalid_refresh")
    access, refresh = issue_tokens(auth.user)
    auth.is_revoked = True
    auth.save(update_fields=["is_revoked", "updated_at"])
    return ok({"token": access, "refreshToken": refresh, "refresh_token": refresh, "user": user_dict(auth.user), "tenant": tenant_dict(auth.user.tenant)})


@csrf_exempt
def auth_logout(request):
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        AuthToken.objects.filter(token=header.removeprefix("Bearer ").strip()).update(is_revoked=True)
    return ok({})


@csrf_exempt
def auth_me(request):
    user, tenant = auth_context(request)
    if not user:
        return fail("unauthorized", 401, "unauthorized")
    memberships = [membership_dict(m) for m in TenantMember.objects.filter(user=user, status="active")]
    return ok({"user": user_dict(user), "tenant": tenant_dict(tenant or user.tenant), "memberships": memberships})


@csrf_exempt
def auth_validate(request):
    user, tenant = auth_context(request)
    return ok({"valid": bool(user or tenant), "user": user_dict(user), "tenant": tenant_dict(tenant)})


@csrf_exempt
def auth_preferences(request):
    user, _ = auth_context(request)
    if not user:
        return fail("unauthorized", 401)
    data = parse_body(request)
    prefs = user.preferences or {}
    prefs.update(data)
    user.preferences = prefs
    user.save(update_fields=["preferences", "updated_at"])
    return ok({"user": user_dict(user)})


@csrf_exempt
def auth_change_password(request):
    user, _ = auth_context(request)
    if not user:
        return fail("unauthorized", 401)
    data = parse_body(request)
    if not verify_password(data.get("old_password", data.get("oldPassword", "")), user.password_hash):
        return fail("old password mismatch", 400)
    user.password_hash = hash_password(data.get("new_password", data.get("newPassword", "")))
    user.save(update_fields=["password_hash", "updated_at"])
    return ok({})


def auth_config(request):
    return ok({"registration_mode": "self_serve", "oidc_enabled": False})


def oidc_config(request):
    return ok({"enabled": False, "provider_display_name": ""})


def oidc_url(request):
    return ok({"authorization_url": "", "state": ""})


def oidc_callback(request):
    return ok({"success": False, "message": "OIDC is not configured"})


# ---------------------------------------------------------------------------
# Tenant views
# ---------------------------------------------------------------------------

@csrf_exempt
def switch_tenant(request):
    user, _ = auth_context(request)
    if not user:
        return fail("unauthorized", 401)
    tenant_id = parse_body(request).get("tenant_id")
    tenant = Tenant.objects.filter(id=tenant_id).first()
    if not tenant:
        return fail("tenant not found", 404)
    return ok({"tenant": tenant_dict(tenant), "user": user_dict(user)})


@csrf_exempt
def tenants_collection(request):
    user, tenant = auth_context(request)
    if not user and not tenant:
        return fail("unauthorized", 401)
    if request.method == "GET":
        if user and user.can_access_all_tenants:
            qs = Tenant.objects.filter(deleted_at__isnull=True)
        elif user:
            ids = TenantMember.objects.filter(user=user, status="active").values_list("tenant_id", flat=True)
            qs = Tenant.objects.filter(id__in=ids, deleted_at__isnull=True)
        else:
            qs = Tenant.objects.filter(id=tenant.id)
        return ok({"items": [tenant_dict(t) for t in qs], "tenants": [tenant_dict(t) for t in qs]})
    data = parse_body(request)
    tenant = Tenant.objects.create(name=data.get("name", "新空间"), description=data.get("description", ""), api_key=secrets.token_urlsafe(24), business=data.get("business", "default"))
    if user:
        TenantMember.objects.create(user=user, tenant=tenant, role="owner")
    return ok(tenant_dict(tenant), status=201)


@csrf_exempt
def tenant_detail(request, tenant_id):
    user, tenant = auth_context(request)
    target = get_object_or_404(Tenant, id=tenant_id)
    if request.method == "GET":
        return ok(tenant_dict(target))
    if request.method == "DELETE":
        target.deleted_at = timezone.now()
        target.save(update_fields=["deleted_at", "updated_at"])
        return ok({})
    data = parse_body(request)
    for field in ["name", "description", "business", "status"]:
        if field in data:
            setattr(target, field, data[field])
    target.save()
    return ok(tenant_dict(target))


@csrf_exempt
def tenant_members(request, tenant_id, user_id=None):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    if request.method == "GET":
        members = TenantMember.objects.filter(tenant=tenant, status="active").select_related("user")
        return ok({"items": [{**membership_dict(m), "user": user_dict(m.user)} for m in members]})
    data = parse_body(request)
    if request.method == "POST":
        user = User.objects.filter(Q(email=data.get("email")) | Q(id=data.get("user_id"))).first()
        if not user:
            return fail("user not found", 404)
        member, _ = TenantMember.objects.update_or_create(user=user, tenant=tenant, defaults={"role": data.get("role", "viewer"), "status": "active"})
        return ok(membership_dict(member))
    member = get_object_or_404(TenantMember, tenant=tenant, user_id=user_id)
    if request.method == "DELETE":
        member.delete()
        return ok({})
    member.role = data.get("role", member.role)
    member.save(update_fields=["role", "updated_at"])
    return ok(membership_dict(member))


@csrf_exempt
def tenant_api_key(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    tenant.api_key = secrets.token_urlsafe(24)
    tenant.save(update_fields=["api_key", "updated_at"])
    return ok(tenant_dict(tenant))


@csrf_exempt
def tenant_kv(request, key):
    _, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    field = TENANT_KV_FIELDS.get(key, f"{key.replace('-', '_')}_config" if not key.endswith("_config") else key.replace("-", "_"))
    if request.method == "GET":
        value = getattr(tenant, field, None) if hasattr(tenant, field) else None
        return ok({"key": key, "field": field, "value": value or {}, "configured": bool(value)})
    data = parse_body(request)
    if hasattr(tenant, field):
        value = data.get("value", data)
        setattr(tenant, field, value)
        tenant.save(update_fields=[field, "updated_at"])
    return ok({"key": key, "field": field, "value": getattr(tenant, field, None) if hasattr(tenant, field) else data})


# ---------------------------------------------------------------------------
# Audit views
# ---------------------------------------------------------------------------

def audit_logs(request, tenant_id=None):
    qs = AuditLog.objects.all().order_by("-created_at")
    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)
    return ok({"items": [{"id": a.id, "action": a.action, "outcome": a.outcome, "created_at": a.created_at.isoformat(), "details": a.details} for a in qs[:100]]})
