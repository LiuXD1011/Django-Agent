import hashlib
import json
import mimetypes
import secrets
import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import FileResponse, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.csrf import csrf_exempt

from .authentication import hash_password, issue_tokens, require_auth, role_for, verify_password
from .document_processing import detect_file_type, process_knowledge
from .document_processing import process_graph as rebuild_knowledge_graph
from .graph_rag import DEFAULT_EXTRACT_CONFIG, delete_kb_graph, delete_knowledge_graph, graph_database_engine, graph_rag_enabled, neo4j_configured, validate_extract_config
from .memory import add_episode as memory_add_episode, is_memory_available, retrieve_memory
from .model_usage import model_usage_summary
from .query_understand import INTENT_KB_SEARCH, get_intent_system_prompt, needs_retrieval, understand_query
from .model_providers import ModelConfigurationError, bailian_status, chat_completion, env_models, provider_types, role_completion, safe_json
from .model_types import canonical_model_type, frontend_model_group, model_type_aliases
from .models import (
    AuditLog,
    AuthToken,
    Chunk,
    GenericResource,
    Knowledge,
    KnowledgeBase,
    KnowledgeTag,
    Message,
    ModelConfig,
    Session,
    TaskRecord,
    Tenant,
    TenantMember,
    User,
    WikiFolder,
    WikiLogEntry,
    WikiPage,
    WikiPendingOp,
)
from .responses import fail, ok
from .search import delete_chunk_index, hybrid_search, index_chunk
from .serializers import (
    DEFAULT_INDEXING_STRATEGY,
    chunk_dict,
    kb_dict,
    knowledge_dict,
    membership_dict,
    message_dict,
    model_dict,
    resource_dict,
    session_dict,
    tag_dict,
    tenant_dict,
    user_dict,
    wiki_folder_dict,
    wiki_page_dict,
    normalize_indexing_strategy,
)
from .tasks import enqueue, task_status
from .wiki_ingest import cleanup_wiki_for_kb, cleanup_wiki_for_knowledge, enqueue_wiki_ingest, prepare_wiki_for_reparse, sync_manual_page_links


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


SESSION_CONFIG_FIELDS = {
    "agent_enabled",
    "agent_id",
    "model_id",
    "summary_model_id",
    "knowledge_base_ids",
    "web_search_enabled",
    "enable_memory",
    "mcp_service_ids",
}


def normalize_session_state(value=None):
    raw = value if isinstance(value, dict) else {}
    state = {
        "agent_enabled": bool_from_value(raw.get("agent_enabled"), False),
        "agent_id": str(raw.get("agent_id") or ""),
        "model_id": str(raw.get("model_id") or ""),
        "summary_model_id": str(raw.get("summary_model_id") or ""),
        "knowledge_base_ids": raw.get("knowledge_base_ids") if isinstance(raw.get("knowledge_base_ids"), list) else [],
        "web_search_enabled": bool_from_value(raw.get("web_search_enabled"), False),
        "enable_memory": bool_from_value(raw.get("enable_memory"), True),
        "mcp_service_ids": raw.get("mcp_service_ids") if isinstance(raw.get("mcp_service_ids"), list) else [],
    }
    return state


def session_state_from_payload(data, fallback=None):
    source = data.get("agent_config") if isinstance(data.get("agent_config"), dict) else data
    state = normalize_session_state(fallback)
    for field in SESSION_CONFIG_FIELDS:
        if field in source:
            state[field] = source[field]
    return normalize_session_state(state)


def bounded_int(value, default, minimum=None, maximum=None):
    try:
        number = int(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        number = default
    if minimum is not None:
        number = max(number, minimum)
    if maximum is not None:
        number = min(number, maximum)
    return number


def paginate(qs, request):
    page_size = bounded_int(request.GET.get("page_size", request.GET.get("limit", 20)), 20, 1, 200)
    if "offset" in request.GET and "page" not in request.GET:
        offset = bounded_int(request.GET.get("offset"), 0, 0)
        page = offset // page_size + 1
    else:
        page = bounded_int(request.GET.get("page"), 1, 1)
        offset = (page - 1) * page_size
    total = qs.count()
    return qs[offset : offset + page_size], {"page": page, "page_size": page_size, "total": total}


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


def list_response(items, meta=None, aliases=None):
    payload = {"items": items, "data": items}
    for alias in aliases or []:
        payload[alias] = items
    if meta:
        payload.update(meta)
    return payload


KNOWLEDGE_TYPE_VALUES = {"file"}
PROCESSING_STATUSES = {"pending", "processing", "finalizing"}
KB_TYPES = {"document"}


def csv_values(value):
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        values = value
    else:
        values = str(value).split(",")
    return [str(item).strip() for item in values if str(item).strip()]


def normalize_ids(data):
    ids = data.get("ids") or data.get("knowledge_ids") or data.get("knowledgeIds") or []
    if isinstance(ids, str):
        ids = csv_values(ids)
    seen = set()
    result = []
    for item in ids:
        item = str(item).strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def extract_process_config(data, default=None):
    for key in ["process_config", "processConfig"]:
        if key in data:
            return safe_json(data.get(key))
    return default


def with_process_config(metadata, process_config, include_empty=False):
    metadata = dict(metadata or {})
    if process_config is None and not include_empty:
        return metadata
    config = process_config or {}
    metadata["process_config"] = config
    metadata["process_overrides"] = config
    return metadata


def normalize_kb_payload(data, existing: KnowledgeBase | None = None, partial=False):
    kb_type = data.get("type", existing.type if existing else "document")
    if kb_type == "faq":
        return None, fail("FAQ knowledge bases are no longer supported", 400)
    if kb_type not in KB_TYPES and kb_type != "wiki":
        return None, fail("unsupported knowledge base type", 400)

    config = data.get("config") or data
    existing_strategy = existing.indexing_strategy if existing else None
    raw_strategy = config.get("indexing_strategy", existing_strategy if partial else DEFAULT_INDEXING_STRATEGY)
    strategy = normalize_indexing_strategy(raw_strategy, kb_type)
    if not any(strategy.values()):
        return None, fail("at least one indexing strategy must be enabled", 400)

    wiki_config = config.get("wiki_config", existing.wiki_config if existing else None)
    if strategy["wiki_enabled"] and wiki_config is None:
        wiki_config = {}
    extract_config = config.get("extract_config", existing.extract_config if existing else None)
    if strategy["graph_enabled"]:
        graph_config = extract_config if isinstance(extract_config, dict) and extract_config else DEFAULT_EXTRACT_CONFIG
        extract_config = {**DEFAULT_EXTRACT_CONFIG, **graph_config, "enabled": True}
    elif isinstance(extract_config, dict):
        extract_config = {**extract_config, "enabled": False}
    error = validate_extract_config(extract_config)
    if error:
        return None, fail(error, 400)

    payload = {
        "type": "document",
        "indexing_strategy": strategy,
        "wiki_config": wiki_config,
        "extract_config": extract_config,
    }
    return payload, None


def delete_knowledge_content(item: Knowledge, cleanup_wiki=True):
    if cleanup_wiki:
        try:
            cleanup_wiki_for_knowledge(item)
        except Exception:
            pass
    delete_knowledge_graph(item)
    for chunk in Chunk.objects.filter(knowledge=item):
        delete_chunk_index(chunk.id, chunk.seq_id)
    Chunk.objects.filter(knowledge=item).delete()


def apply_knowledge_filters(qs, params):
    keyword = params.get("keyword") or params.get("q") or params.get("query")
    if keyword:
        qs = qs.filter(
            Q(title__icontains=keyword)
            | Q(file_name__icontains=keyword)
            | Q(source__icontains=keyword)
            | Q(description__icontains=keyword)
            | Q(metadata__content__icontains=keyword)
        )

    tag_id = params.get("tag_id") or params.get("tagId")
    if tag_id:
        qs = qs.filter(tag_id=tag_id)

    parse_status = params.get("parse_status") or params.get("parseStatus")
    statuses = csv_values(parse_status)
    if len(statuses) == 1:
        qs = qs.filter(parse_status=statuses[0])
    elif statuses:
        qs = qs.filter(parse_status__in=statuses)

    file_values = csv_values(params.get("file_types") or params.get("file_type") or params.get("fileType"))
    if file_values:
        file_query = Q()
        for value in file_values:
            if value in KNOWLEDGE_TYPE_VALUES:
                file_query |= Q(type=value)
            else:
                file_query |= Q(file_type=value)
        qs = qs.filter(file_query)

    source = params.get("source") or params.get("channel")
    if source:
        if source in KNOWLEDGE_TYPE_VALUES:
            qs = qs.filter(type=source)
        else:
            qs = qs.filter(Q(channel=source) | Q(source=source))

    start_time = params.get("start_time") or params.get("startTime")
    end_time = params.get("end_time") or params.get("endTime")
    if start_time:
        qs = qs.filter(created_at__gte=start_time)
    if end_time:
        qs = qs.filter(created_at__lte=end_time)
    return qs


def bool_from_value(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on", "enabled"}


def health(request):
    return JsonResponse({"status": "ok"})


@csrf_exempt
def auth_register(request):
    data = parse_body(request)
    username = data.get("username") or data.get("email", "").split("@")[0] or f"user-{secrets.token_hex(3)}"
    email = data.get("email") or f"{username}@local"
    password = data.get("password") or "knowledge"
    if User.objects.filter(Q(username=username) | Q(email=email)).exists():
        return fail("user already exists", 409, "user_exists")
    tenant = Tenant.objects.create(name=f"{username} 的空间", api_key=secrets.token_urlsafe(24), business="default")
    user = User.objects.create(username=username, email=email, password_hash=hash_password(password), tenant=tenant)
    TenantMember.objects.create(user=user, tenant=tenant, role="owner")
    seed_builtin_models(tenant)
    token, refresh = issue_tokens(user)
    return ok({"user": user_dict(user), "tenant": tenant_dict(tenant), "token": token, "refresh_token": refresh}, status=201)


@csrf_exempt
def auth_auto_setup(request):
    user = User.objects.order_by("created_at").first()
    if not user:
        request._body = json.dumps({"username": "admin", "email": "admin@knowledge.local", "password": "admin123456"}).encode()
        return auth_register(request)
    if user.email == "admin@weknora.local" and not User.objects.filter(email="admin@knowledge.local").exists():
        user.email = "admin@knowledge.local"
        user.save(update_fields=["email", "updated_at"])
    seed_builtin_models(user.tenant)
    token, refresh = issue_tokens(user)
    return ok({"user": user_dict(user), "tenant": tenant_dict(user.tenant), "token": token, "refresh_token": refresh})


@csrf_exempt
def auth_login(request):
    data = parse_body(request)
    login = data.get("email") or data.get("username") or ""
    user = User.objects.filter(Q(email=login) | Q(username=login), deleted_at__isnull=True).first()
    if not user and login == "admin@knowledge.local":
        user = User.objects.filter(email="admin@weknora.local", deleted_at__isnull=True).first()
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


@csrf_exempt
def knowledge_bases(request, kb_id=None):
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    if kb_id:
        kb = get_object_or_404(KnowledgeBase, id=kb_id, deleted_at__isnull=True)
        if request.method == "GET":
            return ok(kb_dict(kb))
        if request.method == "DELETE":
            delete_kb_graph(kb)
            cleanup_wiki_for_kb(kb)
            kb.deleted_at = timezone.now()
            kb.save(update_fields=["deleted_at", "updated_at"])
            return ok({})
        data = parse_body(request)
        config = data.get("config") or data
        normalized, error = normalize_kb_payload(data, kb, partial=True)
        if error:
            return error
        for field in ["name", "description"]:
            if field in data:
                setattr(kb, field, data[field])
        for field in ["chunking_config", "image_processing_config"]:
            if field in config:
                setattr(kb, field, config[field])
        for field, value in normalized.items():
            setattr(kb, field, value)
        kb.save()
        return ok(kb_dict(kb))
    if request.method == "GET":
        qs = KnowledgeBase.objects.filter(tenant=tenant, deleted_at__isnull=True, is_temporary=False).order_by("-is_pinned", "-updated_at")
        creator = request.GET.get("creator")
        keyword = request.GET.get("keyword") or request.GET.get("q") or request.GET.get("query")
        kb_type = request.GET.get("type")
        if creator == "mine" and user:
            qs = qs.filter(creator_id=user.id)
        elif creator == "others" and user:
            qs = qs.exclude(creator_id=user.id)
        if keyword:
            qs = qs.filter(Q(name__icontains=keyword) | Q(description__icontains=keyword))
        if kb_type:
            if kb_type == "faq":
                qs = qs.none()
            elif kb_type == "wiki":
                qs = qs.filter(Q(type="wiki") | Q(indexing_strategy__wiki_enabled=True))
            else:
                qs = qs.filter(type=kb_type)
        page, meta = paginate(qs, request)
        items = [kb_dict(kb) for kb in page]
        for item in items:
            if user and item.get("creator_id") == user.id:
                item["creator_name"] = user.username
        return ok(list_response(items, meta, ["knowledge_bases"]))
    data = parse_body(request)
    normalized, error = normalize_kb_payload(data)
    if error:
        return error
    kb = KnowledgeBase.objects.create(
        tenant=tenant,
        name=data.get("name", "未命名知识库"),
        description=data.get("description", ""),
        type=normalized["type"],
        chunking_config=data.get("chunking_config") or default_chunk_config(),
        image_processing_config=data.get("image_processing_config") or {"enable_multimodal": False, "model_id": ""},
        embedding_model_id=data.get("embedding_model_id", ""),
        summary_model_id=data.get("summary_model_id", ""),
        storage_provider_config=data.get("storage_provider_config") or {"provider": "local"},
        vlm_config=data.get("vlm_config") or {},
        asr_config=data.get("asr_config"),
        extract_config=normalized["extract_config"],
        wiki_config=normalized["wiki_config"],
        indexing_strategy=normalized["indexing_strategy"],
        vector_store_id=data.get("vector_store_id") or "",
        creator_id=user.id if user else "",
    )
    return ok(kb_dict(kb), status=201)


@csrf_exempt
def kb_pin(request, kb_id):
    kb = get_object_or_404(KnowledgeBase, id=kb_id)
    if request.method == "DELETE":
        kb.is_pinned = False
    elif request.method in {"POST", "PUT"}:
        data = parse_body(request)
        kb.is_pinned = bool_from_value(data.get("is_pinned"), not kb.is_pinned)
    else:
        kb.is_pinned = not kb.is_pinned
    kb.pinned_at = timezone.now() if kb.is_pinned else None
    kb.save(update_fields=["is_pinned", "pinned_at", "updated_at"])
    return ok(kb_dict(kb))


@csrf_exempt
def kb_copy(request):
    user, tenant = auth_context(request)
    data = parse_body(request)
    src = get_object_or_404(KnowledgeBase, id=data.get("source_id"))
    clone = KnowledgeBase.objects.create(
        tenant=tenant,
        name=f"{src.name} copy",
        description=src.description,
        type=src.type,
        chunking_config=src.chunking_config,
        image_processing_config=src.image_processing_config,
        embedding_model_id=src.embedding_model_id,
        summary_model_id=src.summary_model_id,
        storage_provider_config=src.storage_provider_config,
        vlm_config=src.vlm_config,
        asr_config=src.asr_config,
        extract_config=src.extract_config,
        wiki_config=src.wiki_config,
        indexing_strategy=normalize_indexing_strategy(src.indexing_strategy, src.type),
        creator_id=user.id if user else "",
    )
    return ok({"knowledge_base": kb_dict(clone), "task_id": ""})


def kb_move_targets(request, kb_id):
    _, tenant = auth_context(request)
    source = get_object_or_404(KnowledgeBase, id=kb_id)
    qs = KnowledgeBase.objects.filter(tenant=tenant, type=source.type, deleted_at__isnull=True).exclude(id=kb_id)
    return ok({"items": [kb_dict(kb) for kb in qs]})


@csrf_exempt
def knowledge_collection(request, kb_id):
    user, tenant = auth_context(request)
    kb = get_object_or_404(KnowledgeBase, id=kb_id)
    if request.method == "GET":
        qs = Knowledge.objects.filter(knowledge_base=kb, deleted_at__isnull=True).order_by("-updated_at")
        qs = apply_knowledge_filters(qs, request.GET)
        page, meta = paginate(qs, request)
        items = [knowledge_dict(item) for item in page]
        return ok(list_response(items, meta, ["knowledge"]))
    if request.method == "DELETE":
        for item in Knowledge.objects.filter(knowledge_base=kb):
            delete_knowledge_content(item)
        Knowledge.objects.filter(knowledge_base=kb).update(deleted_at=timezone.now())
        cleanup_wiki_for_kb(kb)
        return ok({})
    return fail("method not allowed", 405)


@csrf_exempt
def knowledge_file(request, kb_id):
    _, tenant = auth_context(request)
    kb = get_object_or_404(KnowledgeBase, id=kb_id)
    uploaded = request.FILES.get("file")
    if not uploaded:
        return fail("file is required", 400)
    data = uploaded.read()
    file_hash = hashlib.sha256(data).hexdigest()
    existing = Knowledge.objects.filter(
        knowledge_base=kb,
        file_hash=file_hash,
        file_name=uploaded.name,
        deleted_at__isnull=True,
    ).order_by("-created_at").first()
    if existing:
        return ok({"knowledge": knowledge_dict(existing), "task_id": "", "deduplicated": True}, status=200)
    path = default_storage.save(f"tenant-{tenant.id}/{kb.id}/{uuid.uuid4()}-{uploaded.name}", ContentFile(data))

    # 重试逻辑：SQLite 并发写入可能导致 database is locked
    import time as _time
    max_retries = 3
    item = None
    for attempt in range(max_retries):
        try:
            with transaction.atomic():
                existing = Knowledge.objects.select_for_update().filter(
                    knowledge_base=kb,
                    file_hash=file_hash,
                    file_name=uploaded.name,
                    deleted_at__isnull=True,
                ).order_by("-created_at").first()
                if existing:
                    default_storage.delete(path)
                    return ok({"knowledge": knowledge_dict(existing), "task_id": "", "deduplicated": True}, status=200)
                item = Knowledge.objects.create(
                    tenant=tenant,
                    knowledge_base=kb,
                    type="file",
                    title=request.POST.get("fileName") or uploaded.name,
                    source=uploaded.name,
                    parse_status="pending",
                    file_name=uploaded.name,
                    file_type=detect_file_type(uploaded.name),
                    file_size=len(data),
                    file_path=path,
                    file_hash=file_hash,
                    storage_size=len(data),
                    tag_id=request.POST.get("tag_id", ""),
                    metadata=with_process_config({}, safe_json(request.POST.get("process_config")), include_empty=True),
                )
            break  # 成功，跳出重试循环
        except IntegrityError:
            default_storage.delete(path)
            existing = Knowledge.objects.filter(
                knowledge_base=kb,
                file_hash=file_hash,
                file_name=uploaded.name,
                deleted_at__isnull=True,
            ).order_by("-created_at").first()
            if existing:
                return ok({"knowledge": knowledge_dict(existing), "task_id": "", "deduplicated": True}, status=200)
            raise
        except Exception as exc:
            if "database is locked" in str(exc) and attempt < max_retries - 1:
                _time.sleep(2 * (attempt + 1))
                continue
            default_storage.delete(path)
            raise

    if item is None:
        default_storage.delete(path)
        return fail("upload failed after retries", 500)
    task = enqueue("process_knowledge", lambda: (process_knowledge(item.id), {"knowledge_id": item.id})[1], {"knowledge_id": item.id})
    return ok({"knowledge": knowledge_dict(item), "task_id": task.id}, status=201)


@csrf_exempt
def knowledge_detail(request, knowledge_id):
    item = get_object_or_404(Knowledge, id=knowledge_id)
    if request.method == "GET":
        return ok(knowledge_dict(item))
    if request.method == "DELETE":
        delete_knowledge_content(item)
        item.deleted_at = timezone.now()
        item.save(update_fields=["deleted_at", "updated_at"])
        return ok({"id": knowledge_id, "task_id": ""})
    data = parse_body(request)
    for field in ["title", "description", "enable_status", "tag_id"]:
        if field in data:
            setattr(item, field, data[field])
    item.save()
    return ok(knowledge_dict(item))


@csrf_exempt
def knowledge_reparse(request, knowledge_id):
    item = get_object_or_404(Knowledge, id=knowledge_id)
    data = parse_body(request)
    prepare_wiki_for_reparse(item)
    delete_knowledge_content(item, cleanup_wiki=False)
    process_config = extract_process_config(data)
    update_fields = ["parse_status", "updated_at"]
    if process_config is not None:
        item.metadata = with_process_config(item.metadata, process_config)
        update_fields.append("metadata")
    item.parse_status = "pending"
    item.save(update_fields=update_fields)
    task = enqueue("process_knowledge", lambda: (process_knowledge(item.id), {"knowledge_id": item.id})[1], {"knowledge_id": item.id})
    return ok({"knowledge": knowledge_dict(item), "task_id": task.id})


@csrf_exempt
def knowledge_cancel(request, knowledge_id):
    item = get_object_or_404(Knowledge, id=knowledge_id)
    item.parse_status = "cancelled"
    item.save(update_fields=["parse_status", "updated_at"])
    return ok(knowledge_dict(item))


@csrf_exempt
def knowledge_batch_delete(request, kb_id=None):
    data = parse_body(request)
    source_kb_id = kb_id or data.get("kb_id") or data.get("knowledge_base_id") or data.get("source_kb_id")
    ids = normalize_ids(data)
    count = 0
    qs = Knowledge.objects.filter(id__in=ids, deleted_at__isnull=True)
    if source_kb_id:
        qs = qs.filter(knowledge_base_id=source_kb_id)
    for item in qs:
        delete_knowledge_content(item)
        item.deleted_at = timezone.now()
        item.save(update_fields=["deleted_at", "updated_at"])
        count += 1
    return ok({"deleted": count, "deleted_count": count, "ids": ids, "kb_id": source_kb_id, "task_id": ""})


@csrf_exempt
def knowledge_move(request, kb_id=None):
    data = parse_body(request)
    ids = normalize_ids(data)
    source_kb_id = kb_id or data.get("source_kb_id") or data.get("kb_id")
    target_id = data.get("target_kb_id") or data.get("target_knowledge_base_id") or data.get("knowledge_base_id")
    target = get_object_or_404(KnowledgeBase, id=target_id)
    moved = 0
    qs = Knowledge.objects.filter(id__in=ids, deleted_at__isnull=True)
    if source_kb_id:
        qs = qs.filter(knowledge_base_id=source_kb_id)
    for item in qs:
        old_kb_id = item.knowledge_base_id
        cleanup_wiki_for_knowledge(item)
        delete_knowledge_graph(item)
        item.knowledge_base = target
        item.tenant = target.tenant
        item.save(update_fields=["knowledge_base", "tenant", "updated_at"])
        chunks = []
        for chunk in Chunk.objects.filter(knowledge=item):
            delete_chunk_index(chunk.id, chunk.seq_id)
            chunk.knowledge_base = target
            chunk.tenant = target.tenant
            chunk.relation_chunks = None
            chunk.indirect_relation_chunks = None
            chunk.save(update_fields=["knowledge_base", "tenant", "updated_at"])
            index_chunk(chunk)
            chunks.append(chunk)
        try:
            rebuild_knowledge_graph(item, chunks)
        except Exception:
            metadata = dict(item.metadata or {})
            warnings = list(metadata.get("processing_warnings") or [])
            warnings.append({"stage": "graph_move_rebuild", "message": f"graph rebuild skipped after move from {old_kb_id}"})
            metadata["processing_warnings"] = warnings
            item.metadata = metadata
            item.save(update_fields=["metadata", "updated_at"])
        try:
            enqueue_wiki_ingest(item)
        except Exception:
            metadata = dict(item.metadata or {})
            warnings = list(metadata.get("processing_warnings") or [])
            warnings.append({"stage": "wiki_move_rebuild", "message": f"wiki rebuild skipped after move from {old_kb_id}"})
            metadata["processing_warnings"] = warnings
            item.metadata = metadata
            item.save(update_fields=["metadata", "updated_at"])
        moved += 1
    return ok({"moved": moved, "knowledge_count": moved, "source_kb_id": source_kb_id, "target_kb_id": target.id, "target_knowledge_base_id": target.id, "task_id": "", "message": "Knowledge move task started"})


def knowledge_batch(request):
    ids = request.GET.get("ids", "")
    items = Knowledge.objects.filter(id__in=[x for x in ids.split(",") if x])
    return ok({"items": [knowledge_dict(item) for item in items]})


def knowledge_search(request):
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    qs = Knowledge.objects.filter(tenant=tenant, deleted_at__isnull=True)
    qs = apply_knowledge_filters(qs, request.GET)
    page, meta = paginate(qs, request)
    return ok({"items": [knowledge_dict(item) for item in page], **meta})


def knowledge_stats(request, kb_id):
    kb = get_object_or_404(KnowledgeBase, id=kb_id)
    qs = Knowledge.objects.filter(knowledge_base=kb, deleted_at__isnull=True)
    total = qs.count()
    status_counts = {}
    for status in ["pending", "processing", "finalizing", "completed", "failed", "cancelled"]:
        status_counts[status] = qs.filter(parse_status=status).count()
    processing = qs.filter(parse_status__in=PROCESSING_STATUSES).count()
    chunk_count = Chunk.objects.filter(knowledge_base=kb, deleted_at__isnull=True).count()
    storage_size = sum(size or 0 for size in qs.values_list("storage_size", flat=True))
    return ok(
        {
            "knowledge_base_id": kb.id,
            "knowledge_count": total,
            "document_count": total,
            "total": total,
            "completed": status_counts["completed"],
            "processing": processing,
            "pending": status_counts["pending"],
            "failed": status_counts["failed"],
            "cancelled": status_counts["cancelled"],
            "chunk_count": chunk_count,
            "storage_size": storage_size,
            "status_counts": status_counts,
            "is_processing": processing > 0,
        }
    )


def knowledge_spans(request, knowledge_id):
    from .span_tracker import SpanTracker

    item = get_object_or_404(Knowledge, id=knowledge_id)
    tracker = SpanTracker(knowledge_id)
    spans = tracker.get_spans()

    # 如果没有 span 数据，返回基本状态
    if not spans:
        return ok({"items": [{"name": "parse", "status": item.parse_status, "started_at": item.created_at.isoformat(), "finished_at": item.processed_at.isoformat() if item.processed_at else None}]})

    return ok({"items": spans})


def knowledge_download(request, knowledge_id):
    item = get_object_or_404(Knowledge, id=knowledge_id)
    filename = item.file_name or f"{item.title or item.id}.txt"
    if not item.file_path:
        response = HttpResponse(item.metadata.get("content", ""), content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = content_disposition_header(True, filename)
        return response
    return FileResponse(default_storage.open(item.file_path, "rb"), as_attachment=True, filename=filename)


def knowledge_preview(request, knowledge_id):
    item = get_object_or_404(Knowledge, id=knowledge_id)
    filename = item.file_name or f"{item.title or item.id}.txt"
    file_type = detect_file_type(filename)
    inline_types = {
        "txt",
        "md",
        "markdown",
        "csv",
        "json",
        "log",
        "pdf",
        "jpg",
        "jpeg",
        "png",
        "gif",
        "bmp",
        "webp",
        "mp3",
        "wav",
        "mp4",
        "webm",
    }
    if item.file_path and file_type in inline_types:
        content_type = mimetypes.guess_type(filename)[0] or ("text/plain; charset=utf-8" if file_type in {"txt", "md", "markdown", "csv", "json", "log"} else "application/octet-stream")
        response = FileResponse(default_storage.open(item.file_path, "rb"), as_attachment=False, filename=filename, content_type=content_type)
        response["Content-Disposition"] = content_disposition_header(False, filename)
        return response

    chunks = Chunk.objects.filter(knowledge=item, deleted_at__isnull=True).order_by("chunk_index")
    preview_text = "\n\n".join(chunk.content for chunk in chunks)
    if not preview_text:
        metadata = item.metadata or {}
        preview_text = metadata.get("content") or metadata.get("summary") or item.error_message or "该文件暂无可预览文本。"
    response = HttpResponse(preview_text, content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = content_disposition_header(False, f"{Path(filename).stem or item.title}.txt")
    return response


@csrf_exempt
def chunks_collection(request, knowledge_id=None, chunk_id=None):
    if knowledge_id == "by-id" and chunk_id:
        knowledge_id = None
    if chunk_id and not knowledge_id:
        chunk = get_object_or_404(Chunk, id=chunk_id)
        if request.method == "GET":
            return ok(chunk_dict(chunk))
        if request.method == "DELETE":
            delete_knowledge_graph(chunk.knowledge)
            delete_chunk_index(chunk.id, chunk.seq_id)
            chunk.delete()
            return ok({})
    if knowledge_id and chunk_id:
        chunk = get_object_or_404(Chunk, id=chunk_id, knowledge_id=knowledge_id)
        if request.method == "GET":
            return ok(chunk_dict(chunk))
        if request.method == "DELETE":
            delete_knowledge_graph(chunk.knowledge)
            delete_chunk_index(chunk.id, chunk.seq_id)
            chunk.delete()
            return ok({})
        data = parse_body(request)
        chunk.content = data.get("content", chunk.content)
        chunk.is_enabled = data.get("is_enabled", chunk.is_enabled)
        chunk.metadata = data.get("metadata", chunk.metadata)
        chunk.save()
        index_chunk(chunk)
        return ok(chunk_dict(chunk))
    if knowledge_id and request.method == "GET":
        chunks = Chunk.objects.filter(knowledge_id=knowledge_id).order_by("chunk_index")
        chunk_type = request.GET.get("chunk_type")
        if chunk_type:
            chunks = chunks.filter(chunk_type=chunk_type)
        page, meta = paginate(chunks, request)
        items = [chunk_dict(c) for c in page]
        return ok(list_response(items, meta, ["chunks"]))
    if knowledge_id and request.method == "DELETE":
        item = Knowledge.objects.filter(id=knowledge_id).first()
        if item:
            delete_knowledge_content(item)
        return ok({})
    return fail("not found", 404)


@csrf_exempt
def kb_hybrid_search(request, kb_id):
    _, tenant = auth_context(request)
    data = parse_body(request) if request.method == "POST" else request.GET
    query = data.get("query") or data.get("q") or ""
    top_k = int(data.get("top_k") or data.get("limit") or 10)
    results = hybrid_search(tenant.id, [kb_id], query, top_k)
    return ok({"items": results, "results": results})


@csrf_exempt
def knowledge_search_post(request):
    _, tenant = auth_context(request)
    data = parse_body(request)
    kb_ids = data.get("knowledge_base_ids") or data.get("kb_ids") or []
    query = data.get("query") or data.get("q") or ""
    results = hybrid_search(tenant.id, kb_ids, query, int(data.get("top_k", 10)))
    return ok({"items": results, "results": results})


@csrf_exempt
def tags_collection(request, kb_id, tag_id=None):
    _, tenant = auth_context(request)
    kb = get_object_or_404(KnowledgeBase, id=kb_id)
    if request.method == "GET":
        tags = KnowledgeTag.objects.filter(knowledge_base=kb).order_by("sort_order", "created_at")
        return ok({"items": [tag_dict(t) for t in tags]})
    if tag_id:
        tag = get_object_or_404(KnowledgeTag, id=tag_id, knowledge_base=kb)
        if request.method == "DELETE":
            tag.delete()
            return ok({})
        data = parse_body(request)
        tag.name = data.get("name", tag.name)
        tag.color = data.get("color", tag.color)
        tag.sort_order = data.get("sort_order", tag.sort_order)
        tag.save()
        return ok(tag_dict(tag))
    data = parse_body(request)
    tag = KnowledgeTag.objects.create(tenant=tenant, knowledge_base=kb, name=data.get("name", "未命名"), color=data.get("color", ""), sort_order=data.get("sort_order", 0))
    return ok(tag_dict(tag), status=201)


@csrf_exempt
def sessions_collection(request, session_id=None):
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    if session_id:
        session = get_object_or_404(Session, id=session_id, tenant=tenant)
        if request.method == "GET":
            return ok(session_dict(session))
        if request.method == "DELETE":
            session.deleted_at = timezone.now()
            session.save(update_fields=["deleted_at", "updated_at"])
            return ok({})
        data = parse_body(request)
        for field in ["title", "description", "knowledge_base_id", "agent_id"]:
            if field in data:
                setattr(session, field, data[field])
        if "agent_config" in data or any(field in data for field in SESSION_CONFIG_FIELDS):
            session.agent_config = session_state_from_payload(data, session.agent_config)
            if session.agent_config.get("agent_id"):
                session.agent_id = session.agent_config["agent_id"]
            if session.agent_config.get("knowledge_base_ids"):
                session.knowledge_base_id = session.agent_config["knowledge_base_ids"][0]
        session.save()
        return ok(session_dict(session))
    if request.method == "GET":
        qs = Session.objects.filter(tenant=tenant, deleted_at__isnull=True).order_by("-is_pinned", "-updated_at")
        page, meta = paginate(qs, request)
        return ok({"items": [session_dict(s) for s in page], **meta})
    if request.method == "DELETE":
        data = parse_body(request)
        if data.get("delete_all"):
            Session.objects.filter(tenant=tenant).update(deleted_at=timezone.now())
        else:
            Session.objects.filter(id__in=data.get("ids", []), tenant=tenant).update(deleted_at=timezone.now())
        return ok({})
    data = parse_body(request)
    state = session_state_from_payload(data)
    knowledge_base_id = data.get("knowledge_base_id") or (state["knowledge_base_ids"][0] if state["knowledge_base_ids"] else "")
    agent_id = data.get("agent_id") or state["agent_id"]
    session = Session.objects.create(
        tenant=tenant,
        title=data.get("title", "新的对话"),
        knowledge_base_id=knowledge_base_id,
        agent_id=agent_id,
        user_id=user.id if user else "",
        agent_config=state,
    )
    return ok(session_dict(session), status=201)


@csrf_exempt
def session_messages_clear(request, session_id):
    Message.objects.filter(session_id=session_id).delete()
    return ok({})


@csrf_exempt
def session_pin(request, session_id):
    session = get_object_or_404(Session, id=session_id)
    pinned = request.method == "POST"
    session.is_pinned = pinned
    session.pinned_at = timezone.now() if pinned else None
    session.save(update_fields=["is_pinned", "pinned_at", "updated_at"])
    return ok(session_dict(session))


@csrf_exempt
def session_title(request, session_id):
    session = get_object_or_404(Session, id=session_id)
    data = parse_body(request)
    source = data.get("title") or data.get("query") or "新的对话"
    title = role_completion("title", f"请为下面这次知识库对话生成一个 20 字以内的中文标题，只输出标题。\n\n{source}", source, 40)
    session.title = title[:80]
    session.save(update_fields=["title", "updated_at"])
    return ok(session_dict(session))


@csrf_exempt
def session_stop(request, session_id):
    data = parse_body(request)
    message_id = data.get("message_id") or data.get("id")
    if message_id:
        Message.objects.filter(Q(id=message_id) | Q(request_id=message_id), session_id=session_id).update(is_completed=True, updated_at=timezone.now())
    return ok({"session_id": session_id, "message_id": message_id, "stopped": True})


def continue_stream(request, session_id):
    return StreamingHttpResponse(iter(["event: done\ndata: {}\n\n"]), content_type="text/event-stream")


def messages_load(request, session_id):
    limit = bounded_int(request.GET.get("limit"), 50, 1, 200)
    qs = Message.objects.filter(session_id=session_id)
    before_time = request.GET.get("before_time") or request.GET.get("before")
    if before_time:
        try:
            parsed = timezone.datetime.fromisoformat(before_time.replace("Z", "+00:00"))
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed)
            qs = qs.filter(created_at__lt=parsed)
        except Exception:
            pass
    qs = qs.order_by("-created_at")[:limit]
    items = [message_dict(m) for m in reversed(list(qs))]
    return ok({"items": items, "messages": items, "has_more": len(items) >= limit})


@csrf_exempt
def messages_search(request):
    _, tenant = auth_context(request)
    data = parse_body(request)
    q = data.get("query") or data.get("q") or ""
    qs = Message.objects.filter(session__tenant=tenant)
    if q:
        qs = qs.filter(content__icontains=q)
    return ok({"items": [message_dict(m) for m in qs.order_by("-created_at")[:50]]})


def chat_history_stats(request):
    _, tenant = auth_context(request)
    return ok({"total_sessions": Session.objects.filter(tenant=tenant).count(), "total_messages": Message.objects.filter(session__tenant=tenant).count()})


@csrf_exempt
def message_delete(request, session_id, message_id):
    Message.objects.filter(id=message_id, session_id=session_id).delete()
    return ok({})


def _build_document_header(refs: list[dict]) -> str:
    """构建文档头部 XML，列出所有涉及的知识条目及其描述。参考 WeKnora 的 buildDocumentHeader。"""
    seen = set()
    docs = []
    for r in refs:
        kid = r.get("knowledge_id", "")
        if kid in seen:
            continue
        seen.add(kid)
        title = r.get("knowledge_title", "")
        if not title:
            continue
        desc = r.get("knowledge_description", "").strip()
        if desc:
            docs.append(f"<document>\n<title>{title}</title>\n<description>{desc}</description>\n</document>")
        else:
            docs.append(f"<document>\n<title>{title}</title>\n</document>")
    if not docs:
        return ""
    return "<documents>\n" + "\n".join(docs) + "\n</documents>"


def _build_structured_context(refs: list[dict]) -> str:
    """构建结构化 XML context，每个 chunk 带编号。参考 WeKnora 的 into_chat_message。"""
    parts = []
    for i, r in enumerate(refs[:5], 1):
        content = r.get("content", "").strip()
        if content:
            parts.append(f'<context id="{i}">{content}</context>')
    return "\n".join(parts)


def _build_context_with_memory(refs: list[dict], memory_str: str) -> str:
    """组装完整的上下文：文档头 + 结构化 context + 记忆。"""
    doc_header = _build_document_header(refs)
    structured = _build_structured_context(refs)
    parts = []
    if doc_header:
        parts.append(doc_header)
    parts.append(structured)
    if memory_str:
        parts.append(memory_str)
    return "\n\n".join(parts)


SYSTEM_PROMPT_DEFAULT = (
    "你是一个知识库问答助手。请根据提供的知识库上下文回答用户问题。\n"
    "要求：\n"
    "- 优先使用上下文中的信息回答\n"
    "- 如果上下文包含相关文档列表，直接列出文档信息\n"
    "- 引用具体来源时注明文档标题\n"
    "- 如果上下文中没有相关信息，如实说明"
)


@csrf_exempt
def chat_endpoint(request, session_id, agent=False):
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    session = get_object_or_404(Session, id=session_id, tenant=tenant)
    data = parse_body(request)
    query = data.get("query", "")
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    images = data.get("images") or []
    attachments = data.get("attachment_uploads") or data.get("attachments") or []
    mentioned_items = data.get("mentioned_items") or []
    user_msg = Message.objects.create(
        session=session,
        request_id=request_id,
        role="user",
        content=query,
        mentioned_items=mentioned_items,
        images=[{"url": img.get("data") or img.get("url", "")} if isinstance(img, dict) else img for img in images],
        attachments=[
            {
                "file_name": item.get("file_name") or item.get("name") or "attachment",
                "file_size": item.get("file_size") or item.get("size") or 0,
            }
            if isinstance(item, dict)
            else item
            for item in attachments
        ],
        is_completed=True,
        channel=data.get("channel", "web"),
    )
    kb_ids = data.get("knowledge_base_ids") or ([session.knowledge_base_id] if session.knowledge_base_id else list(KnowledgeBase.objects.filter(tenant=tenant).values_list("id", flat=True)))

    # ── Stage 1: 查询理解（意图识别 + 查询改写）──────────────────────
    intent = INTENT_KB_SEARCH
    search_query = query
    try:
        understanding = understand_query(tenant, query)
        intent = understanding.get("intent", INTENT_KB_SEARCH)
        search_query = understanding.get("rewrite_query") or query
    except Exception:
        logger.exception("Query understanding failed, using raw query")

    # ── Stage 2: 知识库检索（仅检索意图执行）────────────────────────
    refs = []
    if needs_retrieval(intent):
        refs = hybrid_search(tenant.id, kb_ids, search_query, 5)

    # ── Stage 3: 记忆检索 ──────────────────────────────────────────
    enable_memory = data.get("enable_memory")
    if enable_memory is None:
        enable_memory = (user.preferences or {}).get("enable_memory", True)
    memory_context_str = ""
    if enable_memory and user and is_memory_available():
        try:
            mem_ctx = retrieve_memory(tenant, str(user.id), search_query)
            if mem_ctx.related_episodes:
                memory_context_str = "\n\n<relevant_memory>\n" + "\n".join(
                    f"- {ep.summary}" for ep in mem_ctx.related_episodes
                ) + "\n</relevant_memory>"
        except Exception:
            logger.exception("Memory retrieval failed")

    # ── Stage 4: 构建上下文 + System Prompt ─────────────────────────
    system_prompt = get_intent_system_prompt(intent) or SYSTEM_PROMPT_DEFAULT

    if refs:
        full_context = _build_context_with_memory(refs, memory_context_str)
        user_prompt = f"{full_context}\n\n<user_question>\n{query}\n</user_question>"
    elif memory_context_str:
        user_prompt = f"{memory_context_str}\n\n<user_question>\n{query}\n</user_question>"
    else:
        user_prompt = query

    # ── Stage 5: 生成回答（Agent 模式 vs 普通模式）─────────────────
    agent_steps_data = []
    agent_duration_ms = 0

    if agent:
        # ── Agent 模式：ReAct 循环 ────────────────────────────────
        from .agent_engine import AgentEngine

        # 加载 agent 配置
        agent_config = {}
        if session.agent_id:
            agent_resource = GenericResource.objects.filter(id=session.agent_id, resource_type="agents", tenant=tenant).first()
            if agent_resource:
                agent_config = agent_resource.data or {}

        # 合并 session 级配置
        agent_config.setdefault("model_id", data.get("model_id", ""))
        agent_config.setdefault("knowledge_base_ids", kb_ids)
        agent_config.setdefault("temperature", agent_config.get("temperature", 0.7))
        agent_config.setdefault("max_rounds", agent_config.get("max_rounds", 5))

        engine = AgentEngine(
            tenant=tenant,
            session_id=str(session.id),
            user_id=str(user.id) if user else "",
            agent_config=agent_config,
        )

        # 构建历史对话（最近 5 轮）
        history_msgs = []
        recent_messages = Message.objects.filter(
            session=session, is_completed=True
        ).order_by("-created_at")[:10]
        for msg in reversed(list(recent_messages)):
            if msg.role in ("user", "assistant") and msg.content:
                history_msgs.append({"role": msg.role, "content": msg.content})

        # 构建知识库上下文（文档头 + chunk 内容）注入 Agent
        agent_context = ""
        if refs:
            agent_context = _build_context_with_memory(refs, memory_context_str)

        is_streaming = request.headers.get("Accept", "").find("text/event-stream") >= 0 or data.get("stream")

        if is_streaming:
            # 流式模式：创建空 assistant 消息，逐步更新
            assistant = Message.objects.create(
                session=session,
                request_id=request_id,
                role="assistant",
                content="",
                rendered_content="",
                knowledge_references=refs,
                is_completed=False,
                channel=data.get("channel", "web"),
            )

            def agent_events():
                import time as _time

                # 发送初始事件
                yield f"event: message_start\ndata: {json.dumps({'id': assistant.id, 'request_id': request_id}, ensure_ascii=False)}\n\n"
                yield f"event: message\ndata: {json.dumps({'response_type': 'agent_query', 'assistant_message_id': assistant.id, 'session_id': str(session.id), 'content': '', 'done': False}, ensure_ascii=False)}\n\n"

                collected_content = []
                all_steps = []

                def on_event(event_type, event_data):
                    collected_content.append((event_type, event_data))

                # 执行 Agent
                result = engine.execute(query, history=history_msgs, context_str=agent_context, on_event=on_event)

                # 逐步发送事件
                for event_type, event_data in collected_content:
                    if event_type == "thinking":
                        yield f"event: message\ndata: {json.dumps({'response_type': 'answer', 'assistant_message_id': assistant.id, 'content': event_data.get('content', ''), 'done': False}, ensure_ascii=False)}\n\n"
                    elif event_type == "tool_call":
                        yield f"event: message\ndata: {json.dumps({'response_type': 'tool_call', 'assistant_message_id': assistant.id, 'name': event_data.get('name', ''), 'arguments': event_data.get('arguments', {}), 'iteration': event_data.get('iteration', 0)}, ensure_ascii=False)}\n\n"
                    elif event_type == "tool_result":
                        yield f"event: message\ndata: {json.dumps({'response_type': 'tool_result', 'assistant_message_id': assistant.id, 'name': event_data.get('name', ''), 'output': event_data.get('output', '')[:300], 'duration_ms': event_data.get('duration_ms', 0)}, ensure_ascii=False)}\n\n"

                # 更新 assistant 消息
                assistant.content = result.content
                assistant.rendered_content = result.content
                assistant.knowledge_references = refs
                assistant.agent_steps = [s.to_dict() for s in result.steps]
                assistant.agent_duration_ms = result.duration_ms
                assistant.is_completed = True
                assistant.save(update_fields=["content", "rendered_content", "knowledge_references", "agent_steps", "agent_duration_ms", "is_completed", "updated_at"])

                # 发送最终回答
                yield f"event: message\ndata: {json.dumps({'response_type': 'answer', 'assistant_message_id': assistant.id, 'content': result.content, 'done': True, 'knowledge_references': refs}, ensure_ascii=False)}\n\n"
                yield f"event: message\ndata: {json.dumps({'response_type': 'complete', 'assistant_message_id': assistant.id, 'done': True}, ensure_ascii=False)}\n\n"
                yield f"event: done\ndata: {json.dumps({'message_id': assistant.id}, ensure_ascii=False)}\n\n"

                # 记忆存储
                if enable_memory and user and is_memory_available():
                    try:
                        memory_add_episode(tenant, str(user.id), str(session.id), [{"role": "user", "content": query}, {"role": "assistant", "content": result.content}])
                    except Exception:
                        pass

            return StreamingHttpResponse(agent_events(), content_type="text/event-stream")
        else:
            # 非流式模式
            result = engine.execute(query, history=history_msgs, context_str=agent_context)
            answer = result.content
            agent_steps_data = [s.to_dict() for s in result.steps]
            agent_duration_ms = result.duration_ms

            assistant = Message.objects.create(
                session=session,
                request_id=request_id,
                role="assistant",
                content=answer,
                rendered_content=answer,
                knowledge_references=refs,
                agent_steps=agent_steps_data,
                agent_duration_ms=agent_duration_ms,
                is_completed=True,
                channel=data.get("channel", "web"),
            )
    else:
        # ── 普通模式：单次 LLM 调用 ──────────────────────────────
        try:
            answer = chat_completion(
                tenant,
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                data.get("model_id", ""),
            )
        except ModelConfigurationError:
            answer = local_answer(query, refs, agent=False)
        except Exception:
            answer = local_answer(query, refs, agent=False)

        assistant = Message.objects.create(
            session=session,
            request_id=request_id,
            role="assistant",
            content=answer,
            rendered_content=answer,
            knowledge_references=refs,
            agent_steps=[{"type": "knowledge_search", "query": search_query, "intent": intent, "count": len(refs)}],
            is_completed=True,
            channel=data.get("channel", "web"),
        )

    # ── Stage 6: 记忆存储（异步）───────────────────────────────────
    if not agent and enable_memory and user and is_memory_available():
        memory_add_episode(
            tenant,
            str(user.id),
            str(session.id),
            [{"role": "user", "content": query}, {"role": "assistant", "content": answer}],
        )
    state = session_state_from_payload(data, session.agent_config)
    state.update({
        "query": query,
        "knowledge_base_ids": kb_ids,
        "knowledge_ids": data.get("knowledge_ids") or [],
        "mentioned_items": mentioned_items,
    })
    session.agent_config = state
    if data.get("agent_id"):
        session.agent_id = data.get("agent_id")
    if session.title in {"", "新的对话"}:
        session.title = role_completion("title", f"请为下面这次知识库对话生成一个 20 字以内的中文标题，只输出标题。\n\n{query}", query, 40)[:80] or session.title
    session.save(update_fields=["agent_config", "agent_id", "title", "updated_at"])
    if request.headers.get("Accept", "").find("text/event-stream") >= 0 or data.get("stream"):
        if not agent:
            return stream_message(assistant)
    return ok({"message": message_dict(assistant), "answer": assistant.content, "references": refs})


def stream_message(message: Message):
    def events():
        payload = message_dict(message)
        start = {"id": message.id, "request_id": message.request_id, "assistant_message_id": message.id, "session_id": message.session_id, "response_type": "agent_query", "content": "", "done": False}
        yield f"event: message_start\ndata: {json.dumps({'id': message.id, 'request_id': message.request_id}, ensure_ascii=False)}\n\n"
        yield f"event: message\ndata: {json.dumps(start, ensure_ascii=False)}\n\n"
        text = message.content or ""
        step = max(1, len(text) // 12)
        sent = ""
        for index in range(0, len(text), step):
            sent += text[index : index + step]
            chunk = {**payload, "content": sent, "is_completed": False}
            yield f"event: message\ndata: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            compat = {"id": message.request_id, "assistant_message_id": message.id, "session_id": message.session_id, "response_type": "answer", "content": sent, "done": False, "knowledge_references": message.knowledge_references}
            yield f"event: message\ndata: {json.dumps(compat, ensure_ascii=False)}\n\n"
        refs = {"id": message.id, "knowledge_references": message.knowledge_references}
        yield f"event: references\ndata: {json.dumps(refs, ensure_ascii=False)}\n\n"
        yield f"event: message\ndata: {json.dumps({**refs, 'response_type': 'references', 'assistant_message_id': message.id, 'session_id': message.session_id}, ensure_ascii=False)}\n\n"
        yield f"event: message\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        yield f"event: message\ndata: {json.dumps({'id': message.request_id, 'assistant_message_id': message.id, 'session_id': message.session_id, 'response_type': 'answer', 'content': text, 'done': True, 'knowledge_references': message.knowledge_references}, ensure_ascii=False)}\n\n"
        yield f"event: message\ndata: {json.dumps({'id': message.request_id, 'assistant_message_id': message.id, 'session_id': message.session_id, 'response_type': 'complete', 'done': True}, ensure_ascii=False)}\n\n"
        yield f"event: done\ndata: {json.dumps({'message_id': message.id}, ensure_ascii=False)}\n\n"

    return StreamingHttpResponse(events(), content_type="text/event-stream")


def local_answer(query: str, refs: list[dict], agent=False):
    if not refs:
        return "很抱歉，我暂时无法在当前知识库中找到相关内容。"
    intro = "我根据知识库检索到了以下相关内容："
    bullets = "\n".join(f"- {r['knowledge_title']}: {r['content'][:180]}" for r in refs[:3])
    return f"{intro}\n{bullets}"


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
            group = frontend_model_group(item.get("type") or item.get("raw_type") or item.get("legacy_type"))
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


def initialization_config(request, kb_id):
    kb = get_object_or_404(KnowledgeBase, id=kb_id)
    return ok({"knowledge_base": kb_dict(kb), "config": kb_dict(kb, counts=False)})


@csrf_exempt
def initialization_update(request, kb_id):
    return knowledge_bases(request, kb_id)


def system_info(request):
    return ok({
        "name": settings.APP_NAME,
        "edition": "django-lite",
        "version": "0.6.2-django",
        "storage": "FileSystemStorage",
        "cache": "LocMemCache",
        "vector": "sqlite-vec",
        "graph_database_engine": graph_database_engine(),
        "graph_rag_enabled": graph_rag_enabled(),
        "neo4j_configured": neo4j_configured(),
        "bailian": bailian_status(),
    })


def parser_engines(request):
    return ok({"items": [{"name": "builtin", "display_name": "Builtin Python Parser", "enabled": True}]})


def storage_status(request):
    return ok({"provider": "local", "status": "available"})


@csrf_exempt
def generic_collection(request, resource_type, item_id=None, extra=None, **kwargs):
    item_id = item_id or kwargs.get("log_id") or kwargs.get("share_id") or kwargs.get("inv_id")
    user, tenant = auth_context(request)
    if resource_type in {"system_settings"}:
        tenant = tenant or Tenant.objects.first()
    if not tenant:
        return fail("unauthorized", 401)
    if item_id:
        item = get_object_or_404(GenericResource, id=item_id, resource_type=resource_type)
        if request.method == "GET":
            return ok(resource_dict(item))
        if request.method == "DELETE":
            item.deleted_at = timezone.now()
            item.save(update_fields=["deleted_at", "updated_at"])
            return ok({})
        data = parse_body(request)
        item.name = data.get("name", item.name)
        item.status = data.get("status", item.status)
        item.data = {**(item.data or {}), **data}
        item.save()
        return ok(resource_dict(item))
    if request.method == "GET":
        qs = GenericResource.objects.filter(resource_type=resource_type, tenant=tenant, deleted_at__isnull=True).order_by("-updated_at")
        if resource_type == "agents" and not qs.exists():
            seed_builtin_agents(tenant)
            qs = GenericResource.objects.filter(resource_type=resource_type, tenant=tenant, deleted_at__isnull=True).order_by("-updated_at")
        keyword = request.GET.get("keyword") or request.GET.get("q") or request.GET.get("query")
        if keyword:
            qs = qs.filter(Q(name__icontains=keyword) | Q(data__description__icontains=keyword))
        items, meta = paginate(qs, request)
        return ok(list_response([resource_dict(x) for x in items], meta))
    data = parse_body(request)
    defaults = default_resource_payload(resource_type, data)
    item = GenericResource.objects.create(tenant=tenant, resource_type=resource_type, name=defaults.get("name", data.get("name", data.get("title", ""))), data=defaults, status=defaults.get("status", data.get("status", "active")))
    return ok(resource_dict(item), status=201)


@csrf_exempt
def generic_action(request, resource_type, action="", item_id=None, sub_id=None, **kwargs):
    item_id = item_id or kwargs.get("channel_id") or kwargs.get("pending_id")
    sub_id = sub_id or kwargs.get("tool_name") or kwargs.get("field")
    if action in {"types", "providers", "placeholders", "type-presets"}:
        return ok({"items": static_types(resource_type, action)})
    if action in {"test", "validate-credentials", "validate", "storage-engine-check", "parser-engines/check", "remote/check", "embedding/test", "rerank/check", "asr/check", "multimodal/test"}:
        return ok({"status": "ok", "available": True})
    if action == "suggested-questions":
        _, tenant = auth_context(request)
        questions = []
        if tenant:
            chunks = Chunk.objects.filter(tenant=tenant, is_enabled=True).select_related("knowledge").order_by("-updated_at")[:6]
            for chunk in chunks:
                title = chunk.knowledge.title if chunk.knowledge_id else "知识库"
                questions.append({"question": f"{title} 的核心内容是什么？", "source": "knowledge"})
        if not questions:
            questions = [
                {"question": "这个知识库里有哪些重要内容？", "source": "builtin"},
                {"question": "请总结最近上传的资料。", "source": "builtin"},
                {"question": "帮我查找和当前问题相关的引用。", "source": "builtin"},
            ]
        return ok({"items": questions, "questions": questions})
    if resource_type == "agents" and action == "copy":
        _, tenant = auth_context(request)
        src = get_object_or_404(GenericResource, id=item_id, resource_type="agents", tenant=tenant)
        clone_data = {**(src.data or {}), "name": f"{src.name} 副本", "copied_from": src.id}
        clone = GenericResource.objects.create(tenant=tenant, resource_type="agents", name=clone_data["name"], data=clone_data, status=src.status)
        return ok(resource_dict(clone), status=201)
    if resource_type in {"im_channels", "embed_channels"} and action == "toggle":
        _, tenant = auth_context(request)
        item = get_object_or_404(GenericResource, id=item_id, resource_type=resource_type, tenant=tenant)
        enabled = not bool((item.data or {}).get("enabled", item.status == "active"))
        item.data = {**(item.data or {}), "enabled": enabled}
        item.status = "active" if enabled else "disabled"
        item.save(update_fields=["data", "status", "updated_at"])
        return ok(resource_dict(item))
    if resource_type == "embed_channels" and action == "rotate-token":
        _, tenant = auth_context(request)
        item = get_object_or_404(GenericResource, id=item_id, resource_type=resource_type, tenant=tenant)
        token = secrets.token_urlsafe(24)
        item.data = {**(item.data or {}), "token": token}
        item.save(update_fields=["data", "updated_at"])
        return ok({"id": item.id, "token": token, "config": resource_dict(item)})
    if resource_type == "embed_channels" and action == "preview-session":
        _, tenant = auth_context(request)
        session = Session.objects.create(tenant=tenant, title="Agent 预览会话", agent_id=item_id or "")
        return ok({"session": session_dict(session)})
    if action == "stats":
        return ok({"sessions": 0, "messages": 0, "last_active_at": None})
    if action in {"tools", "resources", "tool-approvals", "oauth/status", "stats", "logs", "members", "shares", "agent-shares", "join-requests", "shared-knowledge-bases", "shared-agents"}:
        return ok({"items": []})
    if action in {"sync", "pause", "resume", "toggle", "rotate-token", "preview-session", "leave", "request-upgrade", "invite-code", "invite", "join", "join-request", "join-by-id", "promote", "revoke", "rebuild-links", "auto-fix"}:
        return ok({"status": "ok"})
    return ok({"status": "ok"})


def default_resource_payload(resource_type, data):
    payload = dict(data or {})
    if resource_type == "agents":
        payload.setdefault("name", payload.get("title") or "未命名 Agent")
        payload.setdefault("description", "")
        payload.setdefault("type", payload.get("agent_type") or "rag-qa")
        payload.setdefault("agent_type", payload.get("type") or "rag-qa")
        payload.setdefault("agent_mode", "quick-answer")
        payload.setdefault("avatar", "")
        payload.setdefault("system_prompt", "你是一个严谨的知识库问答助手。请优先基于知识库引用回答。")
        payload.setdefault("opening_statement", "你好，我可以帮你检索知识库并整理答案。")
        payload.setdefault("suggested_questions", ["请总结这个知识库", "有哪些关键风险点？", "给我列出引用来源"])
        payload.setdefault("suggested_prompts", payload.get("suggested_questions") or [])
        payload.setdefault("kb_selection_mode", "selected" if payload.get("knowledge_base_ids") else "all")
        payload.setdefault("knowledge_base_ids", [])
        payload.setdefault("knowledge_bases", payload.get("knowledge_base_ids") or [])
        payload.setdefault("model_id", "")
        payload.setdefault("rerank_model_id", "")
        payload.setdefault("allowed_tools", payload.get("tools") or [])
        payload.setdefault("tools", [])
        payload.setdefault("mcp_selection_mode", "selected" if payload.get("mcp_services") else "none")
        payload.setdefault("mcp_services", [])
        payload.setdefault("web_search_enabled", False)
        payload.setdefault("memory_enabled", True)
        payload.setdefault("rerank_enabled", True)
        payload.setdefault("temperature", 0.3)
        payload.setdefault("max_rounds", 8)
        payload.setdefault("status", "active")
    elif resource_type == "embed_channels":
        payload.setdefault("name", "网页嵌入")
        payload.setdefault("enabled", True)
        payload.setdefault("token", secrets.token_urlsafe(24))
        payload.setdefault("allowed_origins", ["*"])
    elif resource_type == "im_channels":
        payload.setdefault("name", "IM 渠道")
        payload.setdefault("enabled", False)
        payload.setdefault("provider", "wechat")
    return payload


def seed_builtin_agents(tenant):
    presets = [
        {
            "id": f"builtin-quick-answer-{tenant.id}",
            "name": "快速问答",
            "description": "基于知识库直接回答，单轮检索，快速准确。",
            "type": "quick-answer",
            "agent_mode": "quick-answer",
            "system_prompt": "你是一个严谨的知识库问答助手。请优先基于知识库上下文回答用户问题。\n\n要求：\n- 优先使用上下文中的信息回答\n- 引用具体来源时注明文档标题\n- 如果上下文中没有相关信息，如实说明\n- 不要编造信息",
            "allowed_tools": [],
            "max_rounds": 1,
        },
        {
            "id": f"builtin-smart-reasoning-{tenant.id}",
            "name": "智能推理",
            "description": "多步推理，工具调用，深度检索知识库。",
            "type": "smart-reasoning",
            "agent_mode": "smart-reasoning",
            "system_prompt": "你是一个智能推理助手，能够使用工具来帮助回答问题。\n\n## 工作流程\n1. 先理解用户问题，判断是否需要检索知识库\n2. 使用 knowledge_search 工具搜索相关内容\n3. 使用 grep_chunks 在已检索内容中搜索特定信息\n4. 使用 thinking 工具进行推理分析\n5. 基于检索到的信息给出准确、有组织的回答\n\n## 重要规则\n- 优先使用知识库中的信息回答，不要依赖预训练知识\n- 引用具体来源时注明文档标题\n- 可以同时调用多个工具\n- 如果知识库中没有相关信息，如实说明",
            "allowed_tools": ["thinking", "knowledge_search", "grep_chunks", "list_knowledge_docs", "get_document_info"],
            "max_rounds": 5,
        },
        {
            "id": f"builtin-wiki-researcher-{tenant.id}",
            "name": "Wiki 问答",
            "description": "Wiki 图谱导航，结构化知识检索。",
            "type": "wiki-researcher",
            "agent_mode": "smart-reasoning",
            "system_prompt": "你是一个 Wiki 知识库研究员，擅长通过 Wiki 页面导航和结构化信息回答问题。\n\n## 工作流程\n1. 使用 wiki_search 搜索相关的 Wiki 页面\n2. 使用 wiki_read_page 读取 Wiki 页面的完整内容\n3. 使用 wiki_list_pages 列出所有可用的 Wiki 页面\n4. 如果 Wiki 页面信息不够详细，使用 wiki_read_source_doc 回溯到原始文档\n5. 使用 thinking 工具分析和推理\n6. 综合所有信息给出结构化的回答\n\n## 重要规则\n- 优先使用 Wiki 页面中的结构化信息\n- Wiki 搜索只返回摘要，必须用 wiki_read_page 读取完整内容\n- 引用来源时注明 Wiki 页面标题\n- 如果 Wiki 页面没有相关信息，可以回退到 knowledge_search 搜索原始文档\n- 对比不同页面的信息，给出全面的回答",
            "allowed_tools": ["thinking", "wiki_search", "wiki_read_page", "wiki_list_pages", "wiki_read_source_doc", "knowledge_search"],
            "max_rounds": 5,
        },
    ]
    for preset in presets:
        if GenericResource.objects.filter(id=preset["id"]).exists():
            continue
        data = default_resource_payload("agents", preset)
        GenericResource.objects.create(id=preset["id"], tenant=tenant, resource_type="agents", name=data["name"], data=data, status="active")


def static_types(resource_type, action):
    if resource_type == "vector_stores":
        return [{"type": "sqlite", "name": "SQLite sqlite-vec", "builtin": True}]
    if resource_type == "web_search_providers":
        return [{"provider": "duckduckgo"}, {"provider": "bing"}, {"provider": "google"}, {"provider": "searxng"}]
    if resource_type == "data_sources":
        return []
    if resource_type == "agents":
        if action == "placeholders":
            return [
                {"key": "query", "label": "用户问题", "fields": ["system_prompt", "context_template"]},
                {"key": "context", "label": "知识库上下文", "fields": ["system_prompt", "context_template"]},
                {"key": "history", "label": "历史对话", "fields": ["system_prompt"]},
                {"key": "current_date", "label": "当前日期", "fields": ["system_prompt"]},
            ]
        return [
            {"id": "quick-answer", "type": "quick-answer", "name": "快速问答", "agent_mode": "quick-answer", "description": "基于知识库直接回答，单轮检索"},
            {"id": "smart-reasoning", "type": "smart-reasoning", "name": "智能推理", "agent_mode": "smart-reasoning", "description": "多步推理，工具调用，深度检索"},
            {"id": "wiki-researcher", "type": "wiki-researcher", "name": "Wiki 问答", "agent_mode": "smart-reasoning", "description": "Wiki 图谱导航，结构化知识检索"},
        ]
    return []


@csrf_exempt
def wiki_pages(request, kb_id, slug=None):
    _, tenant = auth_context(request)
    kb = get_object_or_404(KnowledgeBase, id=kb_id)
    if slug:
        slug = slug.lstrip("/")
        page = get_object_or_404(WikiPage, knowledge_base=kb, slug=slug)
        if request.method == "GET":
            return ok(wiki_page_dict(page))
        if request.method == "DELETE":
            page.delete()
            return ok({})
        data = parse_body(request)
        page.title = data.get("title", page.title)
        page.content = data.get("content", page.content)
        page.summary = data.get("summary", page.summary)
        page.folder_id = data.get("folder_id", page.folder_id)
        if "page_type" in data:
            page.page_type = data.get("page_type") or page.page_type
        if "aliases" in data and isinstance(data.get("aliases"), list):
            page.aliases = data.get("aliases")
        page.save()
        sync_manual_page_links(page)
        return ok(wiki_page_dict(page))
    if request.method == "GET":
        pages = WikiPage.objects.filter(knowledge_base=kb).order_by("title")
        return ok({"items": [wiki_page_dict(p) for p in pages]})
    data = parse_body(request)
    title = data.get("title", "Untitled")
    page = WikiPage.objects.create(
        tenant=tenant or kb.tenant,
        knowledge_base=kb,
        slug=data.get("slug") or slugify(title),
        title=title,
        content=data.get("content", ""),
        summary=data.get("summary", ""),
        folder_id=data.get("folder_id", ""),
        page_type=data.get("page_type") or "page",
        aliases=data.get("aliases") if isinstance(data.get("aliases"), list) else [],
        status=data.get("status") or "published",
    )
    sync_manual_page_links(page)
    return ok(wiki_page_dict(page), status=201)


@csrf_exempt
def wiki_folders(request, kb_id, folder_id=None):
    _, tenant = auth_context(request)
    kb = get_object_or_404(KnowledgeBase, id=kb_id)
    if folder_id:
        folder = get_object_or_404(WikiFolder, id=folder_id, knowledge_base=kb)
        if request.method == "DELETE":
            folder.delete()
            return ok({})
        data = parse_body(request)
        folder.name = data.get("name", folder.name)
        folder.parent_id = data.get("parent_id", folder.parent_id)
        folder.path = data.get("path", folder.path)
        folder.depth = data.get("depth", folder.depth)
        folder.sort_order = data.get("sort_order", folder.sort_order)
        folder.save()
        return ok(wiki_folder_dict(folder))
    if request.method == "GET":
        folders = WikiFolder.objects.filter(knowledge_base=kb).order_by("sort_order")
        return ok({"items": [wiki_folder_dict(f) for f in folders]})
    data = parse_body(request)
    name = data.get("name", "Folder")
    folder = WikiFolder.objects.create(
        tenant=tenant or kb.tenant,
        knowledge_base=kb,
        name=name,
        parent_id=data.get("parent_id", ""),
        path=data.get("path") or name,
        depth=data.get("depth", 0),
        sort_order=data.get("sort_order", 0),
    )
    return ok(wiki_folder_dict(folder), status=201)


def wiki_index(request, kb_id):
    kb = get_object_or_404(KnowledgeBase, id=kb_id)
    pages = WikiPage.objects.filter(knowledge_base=kb).order_by("page_type", "sort_order", "title")
    labels = {"index": "目录", "summary": "摘要", "entity": "实体", "concept": "概念", "synthesis": "综合", "comparison": "对比", "page": "页面"}
    groups = []
    for page_type in sorted({page.page_type for page in pages}):
        grouped = [wiki_page_dict(page) for page in pages if page.page_type == page_type]
        groups.append({"type": page_type, "title": labels.get(page_type, page_type), "pages": grouped})
    return ok({"groups": groups, "items": [wiki_page_dict(p) for p in pages]})


def wiki_search(request, kb_id):
    kb = get_object_or_404(KnowledgeBase, id=kb_id)
    q = request.GET.get("q") or request.GET.get("query") or ""
    limit = min(max(int(request.GET.get("limit", 50) or 50), 1), 200)
    pages = WikiPage.objects.filter(knowledge_base=kb)
    if q:
        pages = pages.filter(Q(title__icontains=q) | Q(content__icontains=q))
    items = [wiki_page_dict(p) for p in pages.order_by("title")[:limit]]
    return ok({"items": items, "pages": items})


def wiki_link_slugs(page: WikiPage) -> list[str]:
    refs = page.out_links if isinstance(page.out_links, list) and page.out_links else []
    if not refs:
        refs = page.source_refs if isinstance(page.source_refs, list) else []
    slugs = []
    for ref in refs:
        if isinstance(ref, dict):
            value = ref.get("slug") or ref.get("target") or ref.get("page_slug")
        else:
            value = ref
        value = str(value or "").strip()
        if value and value not in slugs:
            slugs.append(value)
    return slugs


def wiki_graph_dataset(kb_id):
    pages = list(WikiPage.objects.filter(knowledge_base_id=kb_id))
    by_slug = {page.slug: page for page in pages}
    out_map = {page.slug: [slug for slug in wiki_link_slugs(page) if slug in by_slug and slug != page.slug] for page in pages}
    in_map = {slug: [] for slug in by_slug}
    for source, targets in out_map.items():
        for target in targets:
            in_map.setdefault(target, []).append(source)
    return pages, by_slug, out_map, in_map


def wiki_graph_node(page: WikiPage, out_map, in_map):
    link_count = len(set(out_map.get(page.slug, [])) | set(in_map.get(page.slug, [])))
    return {"id": page.slug, "slug": page.slug, "label": page.title, "title": page.title, "page_type": page.page_type, "link_count": link_count}


def wiki_graph_type_filter(request):
    raw = request.GET.get("types") or ""
    return {item.strip() for item in raw.split(",") if item.strip()}


def wiki_graph_subgraph(kb_id, request):
    pages, by_slug, out_map, in_map = wiki_graph_dataset(kb_id)
    type_filter = wiki_graph_type_filter(request)
    eligible = [page for page in pages if not type_filter or page.page_type in type_filter]
    eligible_slugs = {page.slug for page in eligible}
    mode = (request.GET.get("mode") or "overview").strip() or "overview"
    if mode not in {"overview", "ego"}:
        return None, "mode must be 'overview' or 'ego'"
    limit = min(max(int(request.GET.get("limit", 500) or 500), 1), 2000)
    depth = min(max(int(request.GET.get("depth", 1) or 1), 1), 3)
    center = (request.GET.get("center") or "").strip()
    if mode == "ego":
        if not center:
            return None, "center is required when mode=ego"
        if center not in by_slug:
            selected_slugs = []
        else:
            seen = {center}
            frontier = {center}
            for _ in range(depth):
                next_frontier = set()
                for slug in frontier:
                    next_frontier.update(out_map.get(slug, []))
                    next_frontier.update(in_map.get(slug, []))
                next_frontier = {slug for slug in next_frontier if slug in eligible_slugs and slug not in seen}
                seen.update(next_frontier)
                frontier = next_frontier
            selected_slugs = [slug for slug in seen if slug in eligible_slugs or slug == center]
    else:
        ranked = sorted(eligible, key=lambda page: (-(len(set(out_map.get(page.slug, [])) | set(in_map.get(page.slug, [])))), page.title))
        selected_slugs = [page.slug for page in ranked]
    total = len(selected_slugs)
    selected_slugs = selected_slugs[:limit]
    selected = set(selected_slugs)
    nodes = [wiki_graph_node(by_slug[slug], out_map, in_map) for slug in selected_slugs if slug in by_slug]
    edges = []
    for source in selected_slugs:
        for target in out_map.get(source, []):
            if target in selected:
                edges.append({"source": source, "target": target})
    meta = {"mode": mode, "total": total if mode == "ego" else len(eligible), "returned": len(nodes), "truncated": total > len(nodes), "center": center, "depth": depth}
    return {"nodes": nodes, "edges": edges, "meta": meta}, None


def wiki_graph(request, kb_id):
    data, error = wiki_graph_subgraph(kb_id, request)
    if error:
        return fail(error, 400)
    return ok(data)


def wiki_stats(request, kb_id):
    pages = WikiPage.objects.filter(knowledge_base_id=kb_id)
    folders = WikiFolder.objects.filter(knowledge_base_id=kb_id)
    _, _, out_map, in_map = wiki_graph_dataset(kb_id)
    by_type = {}
    for page in pages:
        by_type[page.page_type] = by_type.get(page.page_type, 0) + 1
    total_links = sum(len(targets) for targets in out_map.values())
    orphan_count = sum(1 for page in pages if not out_map.get(page.slug) and not in_map.get(page.slug))
    return ok({
        "pages": pages.count(),
        "folders": folders.count(),
        "total_pages": pages.count(),
        "total_links": total_links,
        "pages_by_type": by_type,
        "orphan_count": orphan_count,
        "recent_updates": [wiki_page_dict(p) for p in pages.order_by("-updated_at")[:5]],
        "pending_tasks": WikiPendingOp.objects.filter(scope_id=kb_id).count(),
        "pending_issues": 0,
        "is_active": True,
    })


def wiki_log(request, kb_id):
    items = [
        {
            "id": item.id,
            "knowledge_base_id": item.knowledge_base_id,
            "knowledge_id": item.knowledge_id,
            "action": item.action,
            "doc_title": item.doc_title,
            "summary": item.summary,
            "pages_affected": item.pages_affected,
            "details": item.details,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in WikiLogEntry.objects.filter(knowledge_base_id=kb_id).order_by("-created_at")[:100]
    ]
    return ok({"items": items})


def wiki_lint(request, kb_id):
    return ok({"issues": []})


def wiki_issues(request, kb_id, issue_id=None):
    return ok({"items": []} if not issue_id else {"id": issue_id, "status": "resolved"})


@csrf_exempt
def embed_public(request, channel_id, action=None, session_id=None, chunk_id=None):
    channel = GenericResource.objects.filter(id=channel_id, resource_type="embed_channels").first()
    if action == "exchange":
        return ok({"token": f"embed-{channel_id}-{secrets.token_urlsafe(12)}", "session": {}})
    if action == "config":
        return ok(channel.data if channel else {"id": channel_id, "enabled": True})
    if action == "suggested-questions":
        return ok({"items": []})
    if action == "chunks":
        chunk = get_object_or_404(Chunk, id=chunk_id)
        return ok(chunk_dict(chunk))
    if action == "sessions":
        tenant = Tenant.objects.first()
        session = Session.objects.create(tenant=tenant, title="Embed chat")
        return ok(session_dict(session), status=201)
    if action in {"knowledge-chat", "agent-chat"}:
        return chat_endpoint(request, session_id, agent=action == "agent-chat")
    if action == "messages":
        return messages_load(request, session_id)
    if action == "stop":
        return ok({"stopped": True})
    if action == "events":
        return ok({})
    return ok({})


def serve_file(request):
    file_path = request.GET.get("file_path") or request.GET.get("path") or ""
    file_path = file_path.removeprefix("local://").lstrip("/")
    if not file_path:
        return fail("file_path required", 400)
    return FileResponse(default_storage.open(file_path, "rb"), content_type=mimetypes.guess_type(file_path)[0] or "application/octet-stream")


def presigned_file(request):
    return serve_file(request)


@csrf_exempt
def im_callback(request, channel_id):
    return ok({"channel_id": channel_id, "status": "received"})


def task_progress(request, task_id):
    return ok(task_status(task_id))


def audit_logs(request, tenant_id=None):
    qs = AuditLog.objects.all().order_by("-created_at")
    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)
    return ok({"items": [{"id": a.id, "action": a.action, "outcome": a.outcome, "created_at": a.created_at.isoformat(), "details": a.details} for a in qs[:100]]})


def default_chunk_config():
    return {"chunk_size": 512, "chunk_overlap": 50, "split_markers": ["\n\n", "\n", "。"], "keep_separator": True}


def seed_builtin_models(tenant):
    ModelConfig.objects.filter(id__in=[f"builtin-local-chat-{tenant.id}", f"builtin-local-embedding-{tenant.id}"]).delete()


def slugify(value):
    value = (value or "page").strip().lower()
    value = "".join(ch if ch.isalnum() else "-" for ch in value)
    return "-".join(part for part in value.split("-") if part) or "page"
