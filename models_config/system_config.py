"""System administrator configuration APIs; secrets never appear in responses."""
import json
import math
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from config.bootstrap import read_startup, startup_path, update_startup
from config.runtime_paths import app_data_root
from personal_knowledge_base.credential_fields import public_parameters
from personal_knowledge_base.integration_config import (
    application_configuration, langfuse_configuration,
    local_services_configuration, neo4j_configuration,
)
from personal_knowledge_base.models import IntegrationConfig
from personal_knowledge_base.responses import fail, ok
from personal_knowledge_base.views import auth_context, parse_body

GETTERS = {
    "application": application_configuration, "neo4j": neo4j_configuration,
    "langfuse": langfuse_configuration, "local_services": local_services_configuration,
}
SECRETS = {"neo4j": {"password"}, "langfuse": {"public_key", "secret_key"}, "local_services": {"password"}}
BOOL_FIELDS = {"enabled", "trace_links_enabled", "log_content", "upload_eval_datasets", "autostart", "auto_login"}


def validate_section(section, changes):
    defaults = GETTERS[section]()
    if not isinstance(changes, dict) or set(changes) - set(defaults):
        raise ValueError("未知配置字段")
    for field, value in changes.items():
        if field in BOOL_FIELDS:
            if type(value) is not bool:
                raise ValueError(f"{field} 需要布尔值")
        elif field in {"sample_rate", "startup_timeout_seconds"}:
            low, high = (0, 1) if field == "sample_rate" else (1, 120)
            if type(value) not in {int, float} or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{field} 需要在 {low} 到 {high} 之间")
        elif not isinstance(value, str) or len(value) > 4096 or value.startswith("enc:v1:"):
            raise ValueError(f"{field} 格式错误")
        if field in {"base_url", "ui_base_url", "uri"} and value:
            url = urlsplit(value)
            schemes = {"bolt", "bolt+s", "bolt+ssc", "neo4j", "neo4j+s", "neo4j+ssc"} if field == "uri" else {"http", "https"}
            if (url.scheme not in schemes or not url.hostname or url.username is not None
                    or url.password is not None or url.query or url.fragment
                    or any(char.isspace() for char in value) or "\\" in value):
                raise ValueError(f"{field} 地址错误")
            url.port
        if field == "orphan_mode" and value not in {"skip", "standalone"}:
            raise ValueError("orphan_mode 需要 skip 或 standalone")
        if field == "name" and not value.strip():
            raise ValueError("应用名称不能为空")
        if field in {"base_url", "uri"} and not value:
            raise ValueError(f"{field} 不能为空")
    return changes


def administrator(request):
    user, _ = auth_context(request)
    if not user or not user.is_active:
        return fail("unauthorized", 401)
    if not user.is_system_admin:
        return fail("仅系统管理员可以修改全局配置", 403)
    return None


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
@transaction.atomic
def system_configuration(request, section):
    error = administrator(request)
    if error is not None:
        return error
    if section == "startup":
        if request.method == "DELETE":
            return fail("启动配置请使用保存操作", 405)
        try:
            if request.method == "PUT":
                update_startup(app_data_root(), parse_body(request))
            saved = read_startup(app_data_root())
            response = ok({
                "values": saved, "active": settings.STARTUP_CONFIG,
                "restart_required": saved != settings.STARTUP_SAVED,
                "path": str(startup_path(app_data_root())),
                "data_root": str(app_data_root()),
                "database_path": str(settings.DATABASES["default"]["NAME"]),
                "environment_overrides": settings.STARTUP_ENV_OVERRIDES,
            })
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return fail(str(exc), 400)
        response["Cache-Control"] = "no-store"
        return response
    if section not in GETTERS:
        return fail("configuration not found", 404)
    if request.method != "GET":
        IntegrationConfig.objects.get_or_create(name=section)
        row = IntegrationConfig.objects.select_for_update().get(name=section)
        config = dict(row.parameters)
        if request.method == "DELETE":
            data = parse_body(request)
            if not isinstance(data, dict) or data.get("field") not in SECRETS.get(section, set()) or set(data) != {"field"}:
                return fail("请指定要清除的凭据字段", 400)
            config[data["field"]] = ""
            if section in {"neo4j", "langfuse"}:
                config["enabled"] = False
            else:
                config["auto_login"] = False
        else:
            try:
                changes = validate_section(section, parse_body(request))
                for field, value in changes.items():
                    if field in SECRETS.get(section, set()) and value in {"", "******"}:
                        continue
                    config[field] = value
                effective = {**GETTERS[section](), **config}
                if section == "neo4j" and effective["enabled"] and not all(effective.get(k) for k in ("uri", "username", "password")):
                    raise ValueError("启用 Neo4j 前请填写地址、用户名和密码")
                if section == "langfuse" and effective["enabled"] and not all(effective.get(k) for k in ("base_url", "public_key", "secret_key")):
                    raise ValueError("启用追踪前请填写 API 地址和密钥")
                if section == "local_services" and effective["auto_login"] and not all(effective.get(k) for k in ("login_email", "password")):
                    raise ValueError("自动登录需要账号和密码")
            except (ValueError, TypeError) as exc:
                return fail(str(exc), 400)
        row.parameters = config
        row.save()
        cache.delete("langfuse:local-health")
    config = GETTERS[section]()
    response = ok({
        "values": public_parameters(config),
        "fields": {field: {"configured": bool(config.get(field))} for field in SECRETS.get(section, set())},
        "restart_required": section == "local_services",
    })
    response["Cache-Control"] = "no-store"
    return response


@csrf_exempt
@require_http_methods(["POST"])
def test_connection(request, section):
    error = administrator(request)
    if error is not None:
        return error
    if section not in {"neo4j", "langfuse"}:
        return fail("connection test not found", 404)
    config = GETTERS[section]()
    try:
        if section == "neo4j":
            from neo4j import GraphDatabase

            with GraphDatabase.driver(
                config["uri"], auth=(config["username"], config["password"]),
                connection_timeout=5, connection_acquisition_timeout=5, max_transaction_retry_time=0,
            ) as driver:
                driver.verify_connectivity()
        else:
            import httpx

            if not config.get("public_key") or not config.get("secret_key"):
                return fail("请先保存 API 凭据", 400)
            with httpx.Client(trust_env=False, timeout=5, follow_redirects=False) as client:
                response = client.get(config["base_url"].rstrip("/") + "/api/public/projects",
                                      auth=(config["public_key"], config["secret_key"]))
                response.raise_for_status()
        return ok({"state": "connected"})
    except Exception:
        # Connection exceptions can contain the endpoint/auth; only return a fixed message.
        return fail("连接测试失败，请检查已保存的地址、凭据与服务状态", 502)


def system_info(request):
    from personal_knowledge_base.graph_rag import graph_database_engine, graph_rag_enabled, neo4j_configured
    from personal_knowledge_base.model_providers import bailian_status

    return ok({
        "name": application_configuration()["name"], "edition": "django-lite",
        "version": "0.6.2-django", "storage": "FileSystemStorage", "cache": "LocMemCache",
        "vector": "sqlite-vec", "graph_database_engine": graph_database_engine(),
        "graph_rag_enabled": graph_rag_enabled(), "neo4j_configured": neo4j_configured(),
        "bailian": bailian_status(),
    })
