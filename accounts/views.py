import hashlib
import json
import os
import secrets
import tempfile
from contextlib import contextmanager

from filelock import FileLock, Timeout

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, connections, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.views.decorators.csrf import csrf_exempt

from personal_knowledge_base.authentication import has_tenant_access, hash_password, issue_tokens, require_auth, verify_password
from personal_knowledge_base.permissions import action_response, CREDENTIALS_MANAGE, TENANT_CREATE
from personal_knowledge_base.models import (
    AuditLog,
    AuthToken,
    Tenant,
    TenantMember,
    User,
)
from personal_knowledge_base.personal_spaces import create_personal_user
from personal_knowledge_base.responses import fail, ok

from .device_sessions import (
    REFRESH_COOKIE, clear_device_cookies, create_device_session, device_gate, digest_token, locked_user,
    revoke_all_sessions, revoke_session, rotate_refresh, session_dict, set_device_cookies,
)
from .models import DeviceRefreshToken, DeviceSession
from personal_knowledge_base.view_security import can_access_tenant, can_administer_tenant
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
        data = json.loads(request.body.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def auth_context(request):
    try:
        return require_auth(request)
    except PermissionError:
        return None, None


def _locked_authenticated_user(request, user):
    locked = locked_user(user.pk)
    current, _ = auth_context(request)
    return locked if current and current.pk == locked.pk else None


def _active_memberships(user):
    return TenantMember.objects.filter(
        user=user, status="active", deleted_at__isnull=True,
        tenant__status="active", tenant__deleted_at__isnull=True,
    ).filter(Q(tenant__space_type="legacy") | Q(tenant__personal_owner=user))


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


# Bounded wait for the first-run setup lock (seconds); tests may inject a
# smaller bound. On exhaustion the request fails closed with 503/setup_busy.
AUTO_SETUP_LOCK_TIMEOUT = 10.0


class AutoSetupLockTimeout(Exception):
    """The first-run setup lock could not be acquired within its bound."""


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
        lock = FileLock(
            _sqlite_auto_setup_lock_path(database.settings_dict["NAME"]),
            mode=0o600,
        )
        try:
            lock.acquire(timeout=AUTO_SETUP_LOCK_TIMEOUT)
        except Timeout as exc:
            raise AutoSetupLockTimeout from exc
        try:
            with transaction.atomic(using=database_alias):
                yield
        finally:
            lock.release()
        return

    with transaction.atomic(using=database_alias):
        yield


def _cookie_auth_response(request, user, session, access, refresh, status=200):
    response = ok({
        "auth_mode": "cookie", "user": user_dict(user), "tenant": tenant_dict(user.tenant),
        "memberships": [membership_dict(m) for m in _active_memberships(user)],
        "device": session_dict(session, session.pk), "access_expires_at": session.access_expires_at.isoformat(),
    }, status=status)
    return set_device_cookies(response, request, session, access, refresh)


@require_GET
def auth_csrf(request):
    response = ok({"csrf_token": get_token(request)})
    response["Cache-Control"] = "no-store"
    return response


@csrf_exempt
@require_POST
def auth_register(request):
    data = parse_body(request)
    if data.get("auth_mode") not in (None, "cookie", "bearer"):
        return fail("unsupported auth mode", 400, "invalid_auth_mode")
    username = data.get("username") or data.get("email", "").split("@")[0] or f"user-{secrets.token_hex(3)}"
    email = data.get("email") or f"{username}@local"
    password = data.get("password")
    if not password:
        return fail("password is required", 400)
    if User.objects.filter(Q(username=username) | Q(email=email)).exists():
        return fail("user already exists", 409, "user_exists")
    try:
        with device_gate():
            user = create_personal_user(username=username, email=email, password_hash=hash_password(password))
            if data.get("auth_mode") == "cookie":
                session, access, refresh = create_device_session(user, data.get("device_name"))
                return _cookie_auth_response(request, user, session, access, refresh, status=201)
            token, refresh = issue_tokens(user)
    except IntegrityError:
        return fail("user already exists", 409, "user_exists")
    return ok({"user": user_dict(user), "tenant": tenant_dict(user.tenant), "token": token, "refresh_token": refresh}, status=201)


@csrf_exempt
def auth_auto_setup(request):
    if not settings.ALLOW_AUTO_SETUP:
        return fail("auto setup is disabled", 401, "auto_setup_disabled")

    try:
        # All SQLite paths acquire the device gate before database write locks.
        with device_gate(), _auto_setup_gate():
            if User.objects.exists():
                return fail("setup already completed", 401, "setup_already_completed")

            random_password = secrets.token_urlsafe(12)
            setup_data = parse_body(request)
            request._body = json.dumps({"username": "admin", "email": "admin@knowledge.local", "password": random_password, "auth_mode": setup_data.get("auth_mode"), "device_name": setup_data.get("device_name")}).encode()
            request.content_type = "application/json"
            response = auth_register(request)
    except AutoSetupLockTimeout:
        return fail("setup is busy, please retry", 503, "setup_busy")

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
@require_POST
def auth_login(request):
    data = parse_body(request)
    if data.get("auth_mode") not in (None, "cookie", "bearer"):
        return fail("unsupported auth mode", 400, "invalid_auth_mode")
    login = data.get("email") or data.get("username") or ""
    user = User.objects.filter(Q(email=login) | Q(username=login), deleted_at__isnull=True).first()
    if not user:
        return fail("invalid credentials", 401, "invalid_credentials")
    if data.get("auth_mode") == "cookie":
        with device_gate():
            user = locked_user(user.pk)
            if not has_tenant_access(user, user.tenant) or not verify_password(data.get("password", ""), user.password_hash):
                return fail("invalid credentials", 401, "invalid_credentials")
            session, access, refresh = create_device_session(user, data.get("device_name"))
        return _cookie_auth_response(request, user, session, access, refresh)
    # Existing explicit bearer/native protocol remains unchanged.
    with device_gate():
        user = locked_user(user.pk)
        if not has_tenant_access(user, user.tenant) or not verify_password(data.get("password", ""), user.password_hash):
            return fail("invalid credentials", 401, "invalid_credentials")
        token, refresh = issue_tokens(user)
    memberships = [membership_dict(m) for m in _active_memberships(user)]
    return ok({"user": user_dict(user), "tenant": tenant_dict(user.tenant), "token": token, "refresh_token": refresh, "memberships": memberships})


@csrf_exempt
@require_POST
def auth_refresh(request):
    data = parse_body(request)
    token = data.get("refresh_token") or data.get("refreshToken") or data.get("token")
    if data.get("auth_mode") == "cookie" or (not token and request.COOKIES.get(REFRESH_COOKIE)):
        rotated = rotate_refresh(request.COOKIES.get(REFRESH_COOKIE))
        if not rotated:
            return clear_device_cookies(fail("invalid refresh token", 401, "invalid_refresh"))
        session, access, refresh = rotated
        return _cookie_auth_response(request, session.user, session, access, refresh)
    # Serialize the retained legacy protocol with password/global revocation too.
    with device_gate():
        candidate = AuthToken.objects.filter(token=token, token_type="refresh").first()
        if not candidate:
            return fail("invalid refresh token", 401, "invalid_refresh")
        locked_user(candidate.user_id)
        candidates = AuthToken.objects.filter(
            token=token, token_type="refresh", is_revoked=False,
            expires_at__gt=timezone.now(), deleted_at__isnull=True,
            user__is_active=True, user__deleted_at__isnull=True,
        )
        auth = candidates.select_related("user", "user__tenant").first()
        if not auth or not has_tenant_access(auth.user, auth.user.tenant):
            return fail("invalid refresh token", 401, "invalid_refresh")
        # Consume once with a conditional write; concurrent refresh cannot issue two pairs.
        if not candidates.filter(pk=auth.pk).update(is_revoked=True, updated_at=timezone.now()):
            return fail("invalid refresh token", 401, "invalid_refresh")
        access, refresh = issue_tokens(auth.user)
    return ok({"token": access, "refreshToken": refresh, "refresh_token": refresh, "user": user_dict(auth.user), "tenant": tenant_dict(auth.user.tenant)})


@csrf_exempt
@require_POST
def auth_logout(request):
    user, _ = auth_context(request)
    session = getattr(request, "auth_device", None)
    if user and session:
        with device_gate():
            locked_user(user.pk)
            revoke_session(session, "logout")
    elif request.COOKIES.get(REFRESH_COOKIE) and not request.headers.get("Authorization"):
        # Logout still works after the short access cookie expires.
        token = DeviceRefreshToken.objects.select_related("session").filter(digest=digest_token(request.COOKIES[REFRESH_COOKIE])).first()
        if token:
            with device_gate():
                locked_user(token.session.user_id)
                revoke_session(token.session, "logout")
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        AuthToken.objects.filter(token=header.removeprefix("Bearer ").strip()).update(is_revoked=True)
    return clear_device_cookies(ok({}))


@csrf_exempt
@require_POST
def auth_logout_all(request):
    user, _ = auth_context(request)
    if not user:
        return fail("unauthorized", 401, "unauthorized")
    with device_gate():
        user = _locked_authenticated_user(request, user)
        if not user:
            return fail("unauthorized", 401, "unauthorized")
        revoke_all_sessions(user, "logout_all")
    return clear_device_cookies(ok({}))


@csrf_exempt
@require_GET
def auth_devices(request):
    user, _ = auth_context(request)
    if not user:
        return fail("unauthorized", 401, "unauthorized")
    current = getattr(request, "auth_device", None)
    sessions = DeviceSession.objects.filter(user=user).order_by("-last_seen_at")[:100]
    response = ok({"items": [session_dict(session, current.pk if current else None) for session in sessions]})
    response["Cache-Control"] = "no-store"
    return response


@csrf_exempt
@require_http_methods(["DELETE"])
def auth_device_detail(request, device_id):
    user, _ = auth_context(request)
    if not user:
        return fail("unauthorized", 401, "unauthorized")
    with device_gate():
        user = _locked_authenticated_user(request, user)
        if not user:
            return fail("unauthorized", 401, "unauthorized")
        session = get_object_or_404(DeviceSession, pk=device_id, user=user)
        revoke_session(session, "user_revoked")
    response = ok({})
    current = getattr(request, "auth_device", None)
    return clear_device_cookies(response) if current and current.pk == session.pk else response


@csrf_exempt
def auth_me(request):
    user, tenant = auth_context(request)
    if not user:
        return fail("unauthorized", 401, "unauthorized")
    memberships = [membership_dict(m) for m in _active_memberships(user)]
    session = getattr(request, "auth_device", None)
    response = ok({"user": user_dict(user), "tenant": tenant_dict(tenant or user.tenant), "memberships": memberships,
                   "auth_mode": "cookie" if session else "bearer", "device": session_dict(session, session.pk) if session else None})
    response["Cache-Control"] = "no-store"
    return response


@csrf_exempt
def auth_validate(request):
    user, tenant = auth_context(request)
    return ok({"valid": bool(user or tenant), "user": user_dict(user), "tenant": tenant_dict(tenant)})


@csrf_exempt
@require_http_methods(["GET", "POST", "PATCH", "PUT"])
def auth_preferences(request):
    user, _ = auth_context(request)
    if not user:
        return fail("unauthorized", 401)
    if request.method == "GET":
        return ok({"user": user_dict(user)})
    data = parse_body(request)
    if not isinstance(data, dict):
        return fail("preferences must be an object", 400)
    with device_gate():
        user = _locked_authenticated_user(request, user)
        if not user:
            return fail("unauthorized", 401, "unauthorized")
        prefs = dict(user.preferences or {})
        prefs.update(data)
        user.preferences = prefs
        user.save(update_fields=["preferences", "updated_at"])
    return ok({"user": user_dict(user)})


@csrf_exempt
@require_POST
def auth_change_password(request):
    user, _ = auth_context(request)
    if not user:
        return fail("unauthorized", 401)
    data = parse_body(request)
    password = data.get("new_password", data.get("newPassword", ""))
    if not password:
        return fail("new password is required", 400)
    with device_gate():
        user = _locked_authenticated_user(request, user)
        if not user:
            return fail("unauthorized", 401, "unauthorized")
        if not verify_password(data.get("old_password", data.get("oldPassword", "")), user.password_hash):
            return fail("old password mismatch", 400)
        user.password_hash = hash_password(password)
        user.save(update_fields=["password_hash", "updated_at"])
        revoke_all_sessions(user, "password_changed")
    return clear_device_cookies(ok({}))


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
    user, current_tenant = auth_context(request)
    if not user:
        return fail("unauthorized", 401)
    tenant_id = parse_body(request).get("tenant_id")
    tenant = Tenant.objects.filter(id=tenant_id, deleted_at__isnull=True).first()
    if not tenant:
        return fail("tenant not found", 404)
    if not can_access_tenant(user, current_tenant, tenant):
        return fail("forbidden", 403)
    return ok({"tenant": tenant_dict(tenant), "user": user_dict(user)})


@csrf_exempt
def tenants_collection(request):
    user, tenant = auth_context(request)
    if not user and not tenant:
        return fail("unauthorized", 401)
    if request.method == "GET":
        if user and user.can_access_all_tenants:
            qs = Tenant.objects.filter(deleted_at__isnull=True).filter(Q(space_type="legacy") | Q(personal_owner=user))
        elif user:
            ids = TenantMember.objects.filter(user=user, status="active").values_list("tenant_id", flat=True)
            qs = Tenant.objects.filter(id__in=ids, deleted_at__isnull=True).filter(Q(space_type="legacy") | Q(personal_owner=user))
        else:
            qs = Tenant.objects.filter(id=tenant.id)
        return ok({"items": [tenant_dict(t) for t in qs], "tenants": [tenant_dict(t) for t in qs]})
    denied = action_response(request, TENANT_CREATE)
    if denied is not None:
        return denied
    data = parse_body(request)
    tenant = Tenant.objects.create(name=data.get("name", "新空间"), description=data.get("description", ""), api_key=secrets.token_urlsafe(24), business=data.get("business", "default"))
    if user:
        TenantMember.objects.create(user=user, tenant=tenant, role="owner")
    return ok(tenant_dict(tenant), status=201)


@csrf_exempt
def tenant_detail(request, tenant_id):
    user, tenant = auth_context(request)
    if not user and not tenant:
        return fail("unauthorized", 401)
    target = get_object_or_404(Tenant, id=tenant_id, deleted_at__isnull=True)
    if not can_access_tenant(user, tenant, target):
        return fail("tenant not found", 404)
    if request.method == "GET":
        return ok(tenant_dict(target))
    if not can_administer_tenant(user, tenant, target):
        return fail("forbidden", 403)
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
    user, current_tenant = auth_context(request)
    if not user and not current_tenant:
        return fail("unauthorized", 401)
    tenant = get_object_or_404(Tenant, id=tenant_id, deleted_at__isnull=True)
    if not can_access_tenant(user, current_tenant, tenant):
        return fail("tenant not found", 404)
    if request.method != "GET" and tenant.space_type == "personal":
        return fail("personal space cannot be shared", 409, "personal_space_not_shareable")
    if request.method == "GET":
        members = TenantMember.objects.filter(tenant=tenant, status="active", deleted_at__isnull=True).select_related("user")
        if tenant.space_type == "personal":
            members = members.filter(user_id=tenant.personal_owner_id)
        return ok({"items": [{**membership_dict(m), "user": user_dict(m.user)} for m in members]})
    if not can_administer_tenant(user, current_tenant, tenant):
        return fail("forbidden", 403)
    data = parse_body(request)
    if request.method == "POST":
        user = User.objects.filter(Q(email=data.get("email")) | Q(id=data.get("user_id"))).first()
        if not user:
            return fail("user not found", 404)
        member, _ = TenantMember.objects.update_or_create(
            user=user, tenant=tenant,
            defaults={"role": data.get("role", "viewer"), "status": "active", "deleted_at": None},
        )
        return ok(membership_dict(member))
    member = get_object_or_404(TenantMember, tenant=tenant, user_id=user_id)
    if request.method == "DELETE":
        # Retain a revocation marker so the primary-tenant legacy fallback cannot resurrect access.
        member.status = "revoked"
        member.save(update_fields=["status", "updated_at"])
        return ok({})
    member.role = data.get("role", member.role)
    member.save(update_fields=["role", "updated_at"])
    return ok(membership_dict(member))


@csrf_exempt
def tenant_api_key(request, tenant_id):
    user, current_tenant = auth_context(request)
    if not user and not current_tenant:
        return fail("unauthorized", 401)
    tenant = get_object_or_404(Tenant, id=tenant_id, deleted_at__isnull=True)
    if not can_administer_tenant(user, current_tenant, tenant):
        return fail("forbidden", 403)
    tenant.api_key = secrets.token_urlsafe(24)
    tenant.save(update_fields=["api_key", "updated_at"])
    return ok(tenant_dict(tenant, include_api_key=True))


@csrf_exempt
def tenant_kv(request, key):
    _, tenant = auth_context(request)
    if key.replace("-", "_") in {"model_thinking", "model_thinking_config"} and request.method != "GET":
        return fail("请通过思考级别专用接口更新", 400)
    if not tenant:
        return fail("unauthorized", 401)
    field = TENANT_KV_FIELDS.get(key, f"{key.replace('-', '_')}_config" if not key.endswith("_config") else key.replace("-", "_"))
    if request.method == "GET":
        if field in {"web_search_config", "parser_engine_config", "storage_engine_config", "credentials"}:
            denied = action_response(request, CREDENTIALS_MANAGE)
            if denied is not None:
                return denied
        value = getattr(tenant, field, None) if hasattr(tenant, field) else None
        return ok({"key": key, "field": field, "value": value or {}, "configured": bool(value)})
    # 租户级 KV 承载 agent/retrieval 配置与凭据模板：写操作仅限管理员。
    denied = action_response(request, CREDENTIALS_MANAGE)
    if denied is not None:
        return denied
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
    user, current_tenant = auth_context(request)
    if not user and not current_tenant:
        return fail("unauthorized", 401)
    if tenant_id:
        target = get_object_or_404(Tenant, id=tenant_id, deleted_at__isnull=True)
        if not can_access_tenant(user, current_tenant, target):
            return fail("tenant not found", 404)
        qs = AuditLog.objects.filter(tenant=target).order_by("-created_at")
    elif user and user.is_system_admin:
        qs = AuditLog.objects.all().order_by("-created_at")
    else:
        if not current_tenant:
            return fail("unauthorized", 401)
        qs = AuditLog.objects.filter(tenant=current_tenant).order_by("-created_at")
    return ok({"items": [{"id": a.id, "action": a.action, "outcome": a.outcome, "created_at": a.created_at.isoformat(), "details": a.details} for a in qs[:100]]})
