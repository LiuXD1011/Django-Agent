"""Cookie-only device authentication, rotation and cross-process revocation."""
import hashlib
import json
import os
import secrets
import tempfile
from time import monotonic
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta

from django.conf import settings
from asgiref.sync import sync_to_async
from django.db import DatabaseError, close_old_connections, connections, transaction
from django.middleware.csrf import CsrfViewMiddleware, get_token, rotate_token
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin
from filelock import FileLock, Timeout

from personal_knowledge_base.authentication import has_tenant_access
from personal_knowledge_base.models import AuthToken, Tenant, User
from personal_knowledge_base.responses import fail

from .models import DeviceRefreshToken, DeviceSession

ACCESS_COOKIE = "pkb_access"
REFRESH_COOKIE = "pkb_refresh"
REFRESH_PATH = "/api/v1/auth/"
ACCESS_TTL = timedelta(minutes=10)
IDLE_TTL = timedelta(days=30)
ABSOLUTE_TTL = timedelta(days=90)
_GATE_DEPTH = ContextVar("device_gate_depth", default=0)
STREAM_RECHECK_SECONDS = 30


def digest_token(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DeviceSessionBusy(Exception):
    """The bounded SQLite authentication write gate is occupied."""


@contextmanager
def device_gate():
    """Row locks on PostgreSQL; a bounded OS lock also serializes SQLite writers."""
    depth = _GATE_DEPTH.get()
    if depth:
        with transaction.atomic(using=DeviceSession.objects.db):
            yield
        return
    database = connections[DeviceSession.objects.db]
    lock = None
    if database.vendor == "sqlite":
        name = os.fspath(database.settings_dict["NAME"])
        if name != ":memory:" and not name.startswith("file:"):
            name = os.path.realpath(name)
        key = hashlib.sha256(os.fsencode(name)).hexdigest()[:24]
        lock = FileLock(os.path.join(tempfile.gettempdir(), f"pkb-device-{key}.lock"), mode=0o600)
        try:
            lock.acquire(timeout=10)
        except Timeout as exc:
            raise DeviceSessionBusy from exc
    context_token = _GATE_DEPTH.set(depth + 1)
    try:
        with transaction.atomic(using=DeviceSession.objects.db):
            yield
    finally:
        _GATE_DEPTH.reset(context_token)
        if lock is not None:
            lock.release()


def locked_user(user_id):
    return User.objects.select_for_update(of=("self",)).select_related("tenant").get(pk=user_id)


def create_device_session(user, name="网页设备"):
    """Caller holds device_gate and has validated the locked principal."""
    now = timezone.now()
    access, refresh = secrets.token_urlsafe(36), secrets.token_urlsafe(48)
    session = DeviceSession.objects.create(
        user=user, name=str(name or "网页设备")[:100], access_digest=digest_token(access),
        access_expires_at=now + ACCESS_TTL, idle_expires_at=now + IDLE_TTL,
        absolute_expires_at=now + ABSOLUTE_TTL, last_seen_at=now,
    )
    DeviceRefreshToken.objects.create(digest=digest_token(refresh), session=session, expires_at=session.idle_expires_at)
    return session, access, refresh


def session_dict(session, current_id=None):
    return {
        "id": str(session.pk), "name": session.name, "client_type": session.client_type,
        "created_at": session.created_at.isoformat(), "last_seen_at": session.last_seen_at.isoformat(),
        "absolute_expires_at": session.absolute_expires_at.isoformat(),
        "expires_at": session.idle_expires_at.isoformat(),
        "is_revoked": session.revoked_at is not None,
        "current": str(session.pk) == str(current_id) if current_id else False,
    }


def set_device_cookies(response, request, session, access, refresh):
    secure = not settings.DEBUG
    now = timezone.now()
    response.set_cookie(ACCESS_COOKIE, access, max_age=max(0, int((session.access_expires_at - now).total_seconds())),
                        path="/", secure=secure, httponly=True, samesite="Lax")
    response.set_cookie(REFRESH_COOKIE, refresh, max_age=max(0, int((session.idle_expires_at - now).total_seconds())),
                        path=REFRESH_PATH, secure=secure, httponly=True, samesite="Lax")
    rotate_token(request)
    get_token(request)
    response["Cache-Control"] = "no-store"
    return response


def clear_device_cookies(response):
    response.delete_cookie(ACCESS_COOKIE, path="/", samesite="Lax")
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH, samesite="Lax")
    response["Cache-Control"] = "no-store"
    return response


def authenticate_device(request):
    raw = request.COOKIES.get(ACCESS_COOKIE)
    if not raw:
        return None
    now = timezone.now()
    session = DeviceSession.objects.select_related("user", "user__tenant").filter(
        access_digest=digest_token(raw), revoked_at__isnull=True, access_expires_at__gt=now,
        idle_expires_at__gt=now, absolute_expires_at__gt=now,
        user__is_active=True, user__deleted_at__isnull=True,
    ).first()
    if session:
        request.auth_device = session
    return session


def revoke_session(session, reason):
    DeviceSession.objects.filter(pk=session.pk, revoked_at__isnull=True).update(
        revoked_at=timezone.now(), revoke_reason=reason,
    )


def revoke_all_sessions(user, reason):
    DeviceSession.objects.filter(user=user, revoked_at__isnull=True).update(
        revoked_at=timezone.now(), revoke_reason=reason,
    )
    AuthToken.objects.filter(user=user, is_revoked=False).update(is_revoked=True, updated_at=timezone.now())


def rotate_refresh(raw):
    """A consumed token revokes its family; no old-token grace or double issuance."""
    if not raw:
        return None
    with device_gate():
        # Lock the user before the device everywhere, including password change.
        token = DeviceRefreshToken.objects.select_related("session").filter(digest=digest_token(raw)).first()
        if not token:
            return None
        user = locked_user(token.session.user_id)
        session = DeviceSession.objects.select_for_update().get(pk=token.session_id)
        token = DeviceRefreshToken.objects.select_for_update().get(pk=token.pk)
        now = timezone.now()
        if token.consumed_at is not None:
            revoke_session(session, "refresh_replay")
            return None
        if session.revoked_at or session.idle_expires_at <= now or session.absolute_expires_at <= now or token.expires_at <= now:
            return None
        if not has_tenant_access(user, user.tenant):
            revoke_session(session, "principal_disabled")
            return None
        if not DeviceRefreshToken.objects.filter(pk=token.pk, consumed_at__isnull=True).update(consumed_at=now):
            revoke_session(session, "refresh_replay")
            return None
        access, refresh = secrets.token_urlsafe(36), secrets.token_urlsafe(48)
        session.access_digest = digest_token(access)
        session.access_expires_at = min(now + ACCESS_TTL, session.absolute_expires_at)
        session.idle_expires_at = min(now + IDLE_TTL, session.absolute_expires_at)
        session.last_seen_at = now
        session.save(update_fields=["access_digest", "access_expires_at", "idle_expires_at", "last_seen_at"])
        DeviceRefreshToken.objects.create(digest=digest_token(refresh), session=session, expires_at=session.idle_expires_at)
        session.user = user
        return session, access, refresh


def stream_session_is_active(session_id, user_id, tenant_id):
    """Authorize the stable family, not the access digest replaced by refresh.

    No transaction or connection spans a wait for a provider/stream event.
    Existing caller transactions (including Django TestCase) stay intact.
    """
    database = connections[DeviceSession.objects.db]
    if not database.in_atomic_block:
        close_old_connections()
    try:
        now = timezone.now()
        session = DeviceSession.objects.select_related("user", "user__tenant").filter(
            pk=session_id, user_id=user_id, revoked_at__isnull=True,
            idle_expires_at__gt=now, absolute_expires_at__gt=now,
            user__is_active=True, user__deleted_at__isnull=True,
        ).first()
        if not session:
            return False
        tenant = Tenant.objects.filter(pk=tenant_id).first()
        return has_tenant_access(session.user, tenant)
    except (DatabaseError, TypeError, ValueError):
        return False
    finally:
        if not database.in_atomic_block:
            close_old_connections()


def guard_device_stream(response, device, tenant_id):
    """Django 5.2 keeps the actual sync/async iterator in _iterator.

    Replacing streaming_content is its supported wrapping mechanism. Capturing
    that iterator also permits close/aclose of the original source on revoke.
    """
    source = response._iterator
    session_id, user_id = device.pk, device.user_id
    original_closers = tuple(response._resource_closers)

    def close_source():
        for closer in original_closers:
            closer()
        close = getattr(source, "close", None)
        if close and close not in original_closers:
            close()

    def guarded():
        try:
            if not stream_session_is_active(session_id, user_id, tenant_id):
                return
            deadline = monotonic() + STREAM_RECHECK_SECONDS
            for part in source:
                now = monotonic()
                if now >= deadline:
                    if not stream_session_is_active(session_id, user_id, tenant_id):
                        return
                    deadline = now + STREAM_RECHECK_SECONDS
                yield part
        finally:
            close_source()

    async def async_guarded():
        try:
            if not await sync_to_async(stream_session_is_active, thread_sensitive=True)(session_id, user_id, tenant_id):
                return
            deadline = monotonic() + STREAM_RECHECK_SECONDS
            async for part in source:
                now = monotonic()
                if now >= deadline:
                    if not await sync_to_async(stream_session_is_active, thread_sensitive=True)(session_id, user_id, tenant_id):
                        return
                    deadline = now + STREAM_RECHECK_SECONDS
                yield part
        finally:
            aclose = getattr(source, "aclose", None)
            if aclose:
                await aclose()
            await sync_to_async(close_source, thread_sensitive=True)()

    response.streaming_content = async_guarded() if response.is_async else guarded()
    response["Cache-Control"] = "no-store"
    return response


class DeviceSessionCsrfMiddleware(MiddlewareMixin):
    """Protect cookie APIs even when a legacy view deliberately uses csrf_exempt."""
    def process_view(self, request, callback, callback_args, callback_kwargs):
        if request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
            return None
        explicit_cookie = False
        if request.path.rstrip("/") in {
            "/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/register-by-invite",
            "/api/v1/auth/auto-setup", "/api/v1/auth/refresh",
        }:
            if request.content_type and request.content_type.startswith("multipart/"):
                explicit_cookie = request.POST.get("auth_mode") == "cookie"
            else:
                try:
                    data = json.loads(request.body or b"{}")
                    explicit_cookie = isinstance(data, dict) and data.get("auth_mode") == "cookie"
                except (ValueError, UnicodeError):
                    pass
        # Mixed-mode headers never bypass CSRF while ambient auth cookies exist.
        cookie_request = bool(request.COOKIES.get(ACCESS_COOKIE) or request.COOKIES.get(REFRESH_COOKIE))
        if not explicit_cookie and not cookie_request:
            return None
        response = CsrfViewMiddleware(lambda _request: None).process_view(request, lambda _request: None, (), {})
        if response is not None:
            return fail("CSRF verification failed", 403, "csrf_failed")
        return None

    def process_response(self, request, response):
        device = getattr(request, "auth_device", None)
        if device and getattr(response, "streaming", False):
            tenant = getattr(request, "auth_tenant", None)
            tenant_id = tenant.pk if tenant else request.headers.get("X-Tenant-ID") or device.user.tenant_id
            return guard_device_stream(response, device, tenant_id)
        return response

    def process_exception(self, request, exception):
        if isinstance(exception, DeviceSessionBusy):
            return fail("authentication is busy, please retry", 503, "auth_busy")
        return None
