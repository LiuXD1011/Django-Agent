import json
import uuid

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from personal_knowledge_base.model_providers import bailian_status, env_models, provider_types
from personal_knowledge_base.model_types import canonical_model_type, frontend_model_group, model_type_aliases
from personal_knowledge_base.model_usage import model_usage_summary
from personal_knowledge_base.models import ModelConfig, ModelUsage
from personal_knowledge_base.responses import fail, ok
from personal_knowledge_base.serializers import model_dict
from personal_knowledge_base.views import auth_context, parse_body


@csrf_exempt
def models_collection(request, model_id=None):
    _, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    if model_id:
        model = get_object_or_404(ModelConfig, id=model_id, tenant=tenant)
        if request.method == "GET":
            return ok(model_dict(model))
        if request.method == "DELETE":
            model.deleted_at = timezone.now()
            model.save(update_fields=["deleted_at", "updated_at"])
            return ok({})
        data = parse_body(request)
        update_model(model, data)
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
    model = ModelConfig(id=data.get("id") or f"{data.get('type', 'chat')}-{uuid.uuid4().hex[:8]}", tenant=tenant)
    update_model(model, data)
    model.save()
    return ok(model_dict(model), status=201)


def update_model(model, data):
    model.name = data.get("name", model.name or "model")
    model.display_name = data.get("display_name", data.get("displayName", model.display_name))
    model.type = canonical_model_type(data.get("type", model.type or "KnowledgeQA"))
    model.source = data.get("source", model.source or "openai")
    model.description = data.get("description", model.description)
    model.parameters = data.get("parameters", model.parameters or {})
    model.is_default = data.get("is_default", model.is_default)
    model.is_builtin = data.get("is_builtin", model.is_builtin)
    model.managed_by = data.get("managed_by", model.managed_by)
    model.status = data.get("status", model.status or "active")


def model_providers(request):
    return ok({"items": provider_types(), "providers": provider_types()})


def model_usage(request):
    _, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    return ok(model_usage_summary(tenant, request.GET))


@csrf_exempt
def model_credentials(request, model_id, field=None):
    _, tenant = auth_context(request)
    model = get_object_or_404(ModelConfig, id=model_id, tenant=tenant)
    params = model.parameters or {}
    if request.method == "DELETE":
        params.pop(field, None)
    else:
        data = parse_body(request)
        params.update(data.get("credentials") or data)
    model.parameters = params
    model.save(update_fields=["parameters", "updated_at"])
    return ok(model_dict(model))
