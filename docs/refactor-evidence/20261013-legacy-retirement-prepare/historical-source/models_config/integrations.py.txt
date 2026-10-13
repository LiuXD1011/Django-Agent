"""Platform-only UI configuration for observability API credentials."""
from urllib.parse import urlsplit

from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from personal_knowledge_base.models import IntegrationConfig
from personal_knowledge_base.responses import ok, fail
from personal_knowledge_base.views import auth_context, parse_body


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
@transaction.atomic
def langfuse_credentials(request):
    user, _ = auth_context(request)
    if not user or not user.is_active:
        return fail("unauthorized", 401)
    if not user.is_system_admin:
        return fail("仅系统管理员可以管理全局追踪凭据", 403)
    if request.method != "GET":
        IntegrationConfig.objects.get_or_create(name="langfuse")
    row = IntegrationConfig.objects.select_for_update().filter(name="langfuse").first()
    config = dict(row.parameters) if row else {}
    if request.method == "DELETE":
        config.pop("public_key", None)
        config.pop("secret_key", None)
        config["enabled"] = False
    elif request.method == "PUT":
        data = parse_body(request)
        if set(data) - {"public_key", "secret_key", "base_url", "enabled"}:
            return fail("unknown configuration field", 400)
        if "enabled" in data and not isinstance(data["enabled"], bool):
            return fail("enabled must be boolean", 400)
        for field in ("public_key", "secret_key"):
            value = data.get(field)
            if value in (None, "", "******"):
                continue
            if not isinstance(value, str) or value.startswith("enc:v1:"):
                return fail("invalid credential", 400)
            config[field] = value
        if "base_url" in data:
            if not isinstance(data["base_url"], str):
                return fail("invalid base_url", 400)
            try:
                url = urlsplit(data["base_url"])
                if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
                    raise ValueError()
                url.port
            except ValueError:
                return fail("invalid base_url", 400)
            config["base_url"] = data["base_url"].rstrip("/")
        if "enabled" in data:
            config["enabled"] = data["enabled"]
        if config.get("enabled") and not all(config.get(k) for k in ("public_key", "secret_key", "base_url")):
            return fail("启用追踪前请填写 API 地址、Public Key 和 Secret Key", 400)
    if request.method != "GET":
        if row is None:
            row = IntegrationConfig(name="langfuse")
        row.parameters = config
        row.save()
    response = ok({
        "enabled": bool(config.get("enabled")),
        "base_url": config.get("base_url", "http://localhost:3000"),
        "fields": {key: {"configured": bool(config.get(key))} for key in ("public_key", "secret_key")},
    })
    response["Cache-Control"] = "no-store"
    return response
