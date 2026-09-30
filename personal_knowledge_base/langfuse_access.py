"""Authorized Langfuse UI access with a local-only browser session bridge."""
import re
from urllib.parse import urlsplit, quote
import httpx
from django.conf import settings
from django.core.cache import cache
from django.views.decorators.csrf import csrf_exempt
from .responses import ok, fail
from .views import auth_context

SESSION_COOKIE = re.compile(r"^(?:__Secure-)?next-auth\.session-token(?:\.\d+)?$")
LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def configuration():
    from scripts.local_services import langfuse_api_base, local_env
    env = local_env(settings.BASE_DIR)
    server = {}
    path = settings.BASE_DIR / ".env.langfuse"
    if path.exists():
        from dotenv import dotenv_values
        server = dotenv_values(path)
    base = langfuse_api_base(env)
    return {
        "base": base,
        "ui_base": (env.get("LANGFUSE_UI_BASE_URL") or base).rstrip("/"),
        "project": env.get("LANGFUSE_UI_PROJECT_ID") or env.get("LANGFUSE_PROJECT_ID") or server.get("LANGFUSE_INIT_PROJECT_ID", ""),
        "email": env.get("LANGFUSE_LOGIN_EMAIL") or server.get("LANGFUSE_INIT_USER_EMAIL", ""),
        "password": env.get("LANGFUSE_LOGIN_PASSWORD") or server.get("LANGFUSE_INIT_USER_PASSWORD", ""),
        "local_user_id": env.get("LANGFUSE_LOCAL_LOGIN_USER_ID", "").strip(),
        "auto": env.get("LANGFUSE_AUTO_LOGIN", "true").lower() in {"1", "true", "yes"},
    }


def _guard(request, cfg, mutation=False, require_admin=True):
    user, _ = auth_context(request)
    allowed_user = bool(user and user.is_active and (
        user.is_system_admin or
        (cfg.get("local_user_id") and str(user.id) == cfg["local_user_id"])
    ))
    if require_admin and not allowed_user:
        return fail("当前账号未获本地 Langfuse 登录授权，请使用已配置的本地账号或系统管理员", 403, "local_account_required")
    origin = urlsplit(request.build_absolute_uri("/"))
    if mutation and request.headers.get("Origin") != f"{origin.scheme}://{origin.netloc}":
        return fail("请求来源不匹配", 403, "origin_mismatch")
    return None


def _validated_url(value):
    # Reject forms that browsers and Python parse differently before returning a URL.
    if not isinstance(value, str) or re.search(r"[\s\\]", value):
        raise ValueError("url")
    target = urlsplit(value)
    if (target.scheme not in {"http", "https"} or not target.hostname
            or target.username is not None or target.password is not None
            or target.query or target.fragment):
        raise ValueError("url")
    target.port  # Validate invalid or out-of-range ports as well.
    return target


def _local_cookie_guard(request, cfg):
    try:
        target = _validated_url(cfg["base"])
        ui = _validated_url(cfg.get("ui_base") or cfg["base"])
        origin = urlsplit(request.build_absolute_uri("/"))
        if (target.hostname not in LOOPBACK or target.hostname != origin.hostname
                or ui.hostname != target.hostname or target.path not in {"", "/"}
                or request.META.get("REMOTE_ADDR") not in LOOPBACK):
            raise ValueError("host")
    except ValueError:
        return fail("本地登录需要项目与 Langfuse API、界面使用相同的回环主机名", 400, "local_host_required")
    return None


def _open_url(cfg):
    base = cfg.get("ui_base") or cfg["base"]
    _validated_url(base)
    if not cfg["project"]:
        raise ValueError("project")
    return base.rstrip("/") + "/project/" + quote(cfg["project"], safe="") + "/traces"


def _valid_session(data, cfg):
    user = data.get("user") or {}
    if user.get("email", "").casefold() != cfg["email"].casefold():
        return False
    return any(p.get("id") == cfg["project"]
               for org in user.get("organizations", [])
               for p in org.get("projects", []))


def clear_cookies(response, request):
    for name in request.COOKIES:
        if SESSION_COOKIE.fullmatch(name):
            response.delete_cookie(name, path="/", samesite="Lax")
    response["Cache-Control"] = "no-store"
    return response


@csrf_exempt
def langfuse_access(request, action="status"):
    cfg = configuration()
    error = _guard(request, cfg, mutation=action != "status", require_admin=action != "clear")
    if error:
        return error
    if action == "status":
        if request.method != "GET":
            return fail("method not allowed", 405)
        try:
            _validated_url(cfg["base"])
            open_url = _open_url(cfg)
        except ValueError:
            return fail("请配置有效的 Langfuse 界面地址与项目", 400, "invalid_ui_configuration")
        state = cache.get("langfuse:local-health")
        if state is None:
            try:
                with httpx.Client(trust_env=False, timeout=2, follow_redirects=False) as client:
                    state = "healthy" if client.get(cfg["base"] + "/api/public/health").status_code == 200 else "unavailable"
            except httpx.HTTPError:
                state = "unavailable"
            cache.set("langfuse:local-health", state, 5)
        response = ok({"state": state, "auto_login": cfg["auto"],
                       "credentials_configured": bool(cfg["email"] and cfg["password"]),
                       "open_url": open_url})
        response["Cache-Control"] = "no-store"
        return response
    if request.method != "POST":
        return fail("method not allowed", 405)
    if action == "clear":
        error = _local_cookie_guard(request, cfg)
        if error:
            return error
        return clear_cookies(ok({"state": "cleared"}), request)
    if action != "session":
        return fail("not found", 404)
    if not cfg["auto"]:
        return fail("本地自动登录已关闭", 409, "auto_login_disabled")
    error = _local_cookie_guard(request, cfg)
    if error:
        return error
    if not cfg["email"] or not cfg["password"] or not cfg["project"]:
        return fail("请配置本地 Langfuse 登录账号与项目", 409, "credentials_missing")
    user, _ = auth_context(request)
    cooldown_key = f"langfuse:login-cooldown:{user.id}"
    if cache.get(cooldown_key):
        return fail("登录暂时失败，请一分钟后重试", 429, "login_cooldown")
    open_url = _open_url(cfg)
    try:
        with httpx.Client(trust_env=False, timeout=3, follow_redirects=False) as client:
            existing = {k: v for k, v in request.COOKIES.items() if SESSION_COOKIE.fullmatch(k)}
            for name, value in existing.items():
                client.cookies.set(name, value)
            if existing:
                session = client.get(cfg["base"] + "/api/auth/session").json()
                if _valid_session(session, cfg):
                    response = ok({"state": "reused", "open_url": open_url})
                    response["Cache-Control"] = "no-store"
                    return response
                if session.get("user"):
                    return fail("浏览器已登录其他 Langfuse 账号，请先退出该账号", 409, "account_conflict")
                client.cookies.clear()
            csrf = client.get(cfg["base"] + "/api/auth/csrf")
            csrf.raise_for_status()
            token = csrf.json().get("csrfToken")
            if not token:
                raise ValueError("csrf")
            callback = client.post(cfg["base"] + "/api/auth/callback/credentials", data={
                "csrfToken": token, "email": cfg["email"], "password": cfg["password"],
                "json": "true", "callbackUrl": open_url,
            })
            callback.raise_for_status()
            session = client.get(cfg["base"] + "/api/auth/session").json()
            if not _valid_session(session, cfg):
                raise ValueError("session")
            cookies = [c for c in client.cookies.jar if SESSION_COOKIE.fullmatch(c.name)]
            if not cookies or sum(len(c.value) for c in cookies) > 32768:
                raise ValueError("cookie")
            response = clear_cookies(ok({"state": "connected", "open_url": open_url}), request)
            for cookie in cookies:
                response.set_cookie(cookie.name, cookie.value, max_age=3600, httponly=True,
                                    secure=cfg["base"].startswith("https:"), samesite="Lax", path="/")
            return response
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        cache.set(cooldown_key, True, 60)
        return fail("Langfuse 登录验证失败，请检查服务与账号配置", 502, "login_failed")
