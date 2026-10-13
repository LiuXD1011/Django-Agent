import json
import logging
import uuid

from django.http import JsonResponse
from django.db import transaction
from django.views.decorators.http import require_http_methods
from personal_knowledge_base.credential_fields import SECRET_KEYS, is_secret_key
from personal_knowledge_base.authentication import role_for
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from personal_knowledge_base.model_providers import (
    bailian_status,
    env_models,
    provider_types,
    test_embedding_config,
    test_rerank_config,
    testable_model_config,
)
from personal_knowledge_base.model_types import canonical_model_type, frontend_model_group, is_removed_model_type, model_type_aliases
from personal_knowledge_base.model_usage import model_usage_summary
from personal_knowledge_base.models import ModelConfig, ModelUsage
from personal_knowledge_base.responses import fail, ok
from personal_knowledge_base.search import notify_embedding_config_changed
from personal_knowledge_base.serializers import model_dict
from personal_knowledge_base.views import auth_context, parse_body


logger = logging.getLogger(__name__)


def _safe_notify_embedding_changed(tenant):
    """生效 Embedding 配置变化后标记向量索引重建；失败不得阻断模型保存。"""
    try:
        notify_embedding_config_changed(tenant)
    except Exception:
        logger.exception("notify_embedding_config_changed failed")


@csrf_exempt
@require_http_methods(["GET", "POST", "PUT", "PATCH", "DELETE"])
@transaction.atomic
def models_collection(request, model_id=None):
    user, tenant = auth_context(request)
    if request.method not in {"GET", "DELETE"}:
        body = parse_body(request)
        if isinstance(body.get("parameters"), dict) and "thinking" in body["parameters"]:
            return fail("请通过思考级别专用接口更新 thinking", 400)
    if not tenant:
        return fail("unauthorized", 401)
    if request.method != "GET" and not (user and (user.is_system_admin or role_for(user, tenant) in {"owner", "admin"})):
        return fail("仅工作空间管理员可修改或测试模型配置", 403)
    if not model_id and request.method not in {"GET", "POST"}:
        return fail("method not allowed", 405)
    if model_id and request.method == "POST":
        return fail("method not allowed", 405)
    if request.method not in {"GET", "DELETE"}:
        params = body.get("parameters", {})
        if not isinstance(params, dict):
            return fail("parameters must be an object", 400)
        if "is_default" in body and not isinstance(body["is_default"], bool):
            return fail("is_default must be boolean", 400)
        if any(is_secret_key(key) and (not isinstance(value, str) or value.startswith("enc:v1:")) for key, value in params.items() if value is not None):
            return fail("invalid credential value", 400)
    if model_id:
        model = get_object_or_404(ModelConfig, id=model_id, tenant=tenant, deleted_at__isnull=True)
        if request.method == "GET":
            return ok(model_dict(model))
        if request.method == "DELETE":
            was_embedding = canonical_model_type(model.type) == "Embedding"
            model.deleted_at = timezone.now()
            model.save(update_fields=["deleted_at", "updated_at"])
            if was_embedding:
                _safe_notify_embedding_changed(tenant)
            return ok({})
        data = parse_body(request)
        if is_removed_model_type(data.get("type")):
            return fail("ASR model type is no longer supported", 400, "unsupported_model_type")
        update_model(model, data)
        model.save()
        if canonical_model_type(model.type) == "Embedding":
            _safe_notify_embedding_changed(tenant)
        return ok(model_dict(model))
    if request.method == "GET":
        qs = ModelConfig.objects.filter(tenant=tenant, deleted_at__isnull=True)
        typ = request.GET.get("type")
        if typ:
            qs = qs.filter(type__in=model_type_aliases(typ))
        items = [model_dict(m) for m in qs]
        items = env_models(tenant, typ or "") + items
        counts_by_type = {}
        for item in items:
            group = frontend_model_group(item.get("type") or item.get("raw_type"))
            counts_by_type[group] = counts_by_type.get(group, 0) + 1
        return ok({"items": items, "models": items, "total": len(items), "counts_by_type": counts_by_type, "bailian": bailian_status()})
    data = parse_body(request)
    if is_removed_model_type(data.get("type")):
        return fail("ASR model type is no longer supported", 400, "unsupported_model_type")
    model = ModelConfig(id=f"model-{uuid.uuid4().hex}", tenant=tenant)
    update_model(model, data)
    model.save()
    if canonical_model_type(model.type) == "Embedding":
        _safe_notify_embedding_changed(tenant)
    return ok(model_dict(model), status=201)


# 与 serializers.model_dict 的掩码字段保持一致
_CREDENTIAL_PARAMETER_KEYS = SECRET_KEYS | {"apiKey"}
_CREDENTIAL_MASK = "******"


def _merge_model_parameters(existing, incoming):
    """编辑表单约定：凭证字段留空（或回传掩码）表示不修改，保留已保存密钥。"""
    merged = dict(existing or {})
    for key, value in (incoming or {}).items():
        if key in _CREDENTIAL_PARAMETER_KEYS and (value is None or value == "" or value == _CREDENTIAL_MASK):
            continue
        if key in {"apiKey", "apikey"}:
            key = "api_key"
        merged[key] = value
    return merged


def update_model(model, data):
    model.name = data.get("name", model.name or "model")
    model.display_name = data.get("display_name", data.get("displayName", model.display_name))
    model.type = canonical_model_type(data.get("type", model.type or "KnowledgeQA"))
    model.source = data.get("source", model.source or "openai")
    model.description = data.get("description", model.description)
    parameters = data.get("parameters")
    if parameters is not None:
        model.parameters = _merge_model_parameters(model.parameters, parameters)
    model.is_default = data.get("is_default", model.is_default)
    if model.is_default:
        # Lock the workspace to serialize concurrent default selection.
        type(model.tenant).objects.select_for_update().get(pk=model.tenant_id)
        ModelConfig.objects.filter(tenant=model.tenant, type__in=model_type_aliases(model.type), deleted_at__isnull=True).exclude(pk=model.pk).update(is_default=False)
    model.is_builtin = data.get("is_builtin", model.is_builtin)
    model.managed_by = data.get("managed_by", model.managed_by)
    model.fallback_priority = int(data.get("fallback_priority", 0) or 0)
    model.status = data.get("status", model.status or "active")
    if "context_window" in data:
        raw = data.get("context_window")
        try:
            model.context_window = int(raw) if raw and int(raw) > 0 else None
        except (TypeError, ValueError):
            model.context_window = model.context_window


def model_providers(request):
    return ok({"items": provider_types(), "providers": provider_types()})


def model_usage(request):
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    if request.method != "GET" and not (user and (user.is_system_admin or role_for(user, tenant) in {"owner", "admin"})):
        return fail("仅工作空间管理员可修改或测试模型配置", 403)
    return ok(model_usage_summary(tenant, request.GET))


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
@transaction.atomic
def model_credentials(request, model_id, field=None):
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    if request.method != "GET" and not (user and (user.is_system_admin or role_for(user, tenant) in {"owner", "admin"})):
        return fail("仅工作空间管理员可修改或测试模型配置", 403)
    model = get_object_or_404(ModelConfig.objects.select_for_update(), id=model_id, tenant=tenant, deleted_at__isnull=True)
    params = dict(model.parameters or {})
    allowed = {"api_key", "app_secret", "token"}
    if field is not None and field not in allowed:
        return fail("unknown credential field", 400)
    if request.method == "DELETE":
        if field is None:
            return fail("credential field required", 400)
        params.pop(field, None)
        if field == "api_key":
            params.pop("apiKey", None)
            params.pop("apikey", None)
    elif request.method == "PUT":
        data = parse_body(request)
        incoming = data.get("credentials", data)
        if not isinstance(incoming, dict) or set(incoming) - allowed:
            return fail("unknown credential field", 400)
        for key, value in incoming.items():
            if value is None or value in ("", "******"):
                continue
            if not isinstance(value, str) or value.startswith("enc:v1:"):
                return fail("invalid credential value", 400)
            if key == "api_key":
                params.pop("apiKey", None)
                params.pop("apikey", None)
            params[key] = value
    if request.method != "GET":
        model.parameters = params
        model.save(update_fields=["parameters", "updated_at"])
    response = ok({"fields": {key: {"configured": bool(params.get(key))} for key in sorted(allowed)}})
    response["Cache-Control"] = "no-store"
    return response


@csrf_exempt
@require_http_methods(["POST"])
def model_test(request, model_id):
    """POST /api/v1/models/<id>/test：对 Embedding/Rerank 模型发起真实校验请求，返回仅含模型/维度/延迟的结果。"""
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    if request.method != "GET" and not (user and (user.is_system_admin or role_for(user, tenant) in {"owner", "admin"})):
        return fail("仅工作空间管理员可修改或测试模型配置", 403)
    target = testable_model_config(tenant, model_id)
    if target is None:
        return fail("model not found", 404)
    canonical, cfg = target
    if cfg is None:
        return fail("test not supported for this model type", 400, "unsupported_model_type")
    try:
        result = test_embedding_config(cfg) if canonical == "Embedding" else test_rerank_config(cfg)
    except Exception as exc:
        return fail("模型连接校验失败，请检查地址、模型名称和凭据。", 400, "model_test_failed")
    return ok(result)
