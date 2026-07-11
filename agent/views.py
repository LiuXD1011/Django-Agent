import json
import logging
import secrets

logger = logging.getLogger(__name__)

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from personal_knowledge_base.authentication import require_auth
from personal_knowledge_base.models import (
    Chunk,
    GenericResource,
    Session,
)
from personal_knowledge_base.responses import fail, ok
from personal_knowledge_base.serializers import (
    chunk_dict,
    resource_dict,
    session_dict,
)


# ---------------------------------------------------------------------------
# Helpers (imported from personal_knowledge_base.views to keep self-contained)
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


def list_response(items, meta=None, aliases=None):
    payload = {"items": items, "data": items}
    for alias in aliases or []:
        payload[alias] = items
    if meta:
        payload.update(meta)
    return payload


# ---------------------------------------------------------------------------
# Core agent resource views
# ---------------------------------------------------------------------------

@csrf_exempt
def generic_collection(request, resource_type, item_id=None, extra=None, **kwargs):
    item_id = item_id or kwargs.get("log_id") or kwargs.get("share_id") or kwargs.get("inv_id")
    user, tenant = auth_context(request)
    if resource_type in {"system_settings"}:
        from personal_knowledge_base.models import Tenant
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
        if resource_type == "agents":
            seed_builtin_agents(tenant)
            qs = GenericResource.objects.filter(resource_type=resource_type, tenant=tenant, deleted_at__isnull=True, data__agent_mode="multi-agent").order_by("-updated_at")
        else:
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
    if action == "parser-engines/check":
        from personal_knowledge_base.document_parsing import parser_capabilities

        _, tenant = auth_context(request)
        capability = parser_capabilities(tenant)
        return ok({"status": "ok" if capability["available"] else "error", **capability})
    if action in {"test", "validate-credentials", "validate", "storage-engine-check", "remote/check", "embedding/test", "rerank/check", "multimodal/test"}:
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


# ---------------------------------------------------------------------------
# Resource helpers
# ---------------------------------------------------------------------------

def default_resource_payload(resource_type, data):
    payload = dict(data or {})
    if resource_type == "agents":
        payload["name"] = payload.get("name") or payload.get("title") or "智能助手"
        payload.setdefault("description", "自动调度文档、Wiki、图谱子 Agent。")
        payload["type"] = "multi-agent"
        payload["agent_type"] = "multi-agent"
        payload["agent_mode"] = "multi-agent"
        payload.setdefault("avatar", "")
        payload.setdefault("system_prompt", "你是多 Agent 知识工作台的主 Agent。简单问题可直接回答；复杂问题通过 actor 工具调度专业子 Agent。")
        payload.setdefault("opening_statement", "你好，我可以帮你检索知识库并整理答案。")
        payload.setdefault("suggested_questions", ["请总结这个知识库", "有哪些关键风险点？", "给我列出引用来源"])
        payload.setdefault("suggested_prompts", payload.get("suggested_questions") or [])
        payload.setdefault("kb_selection_mode", "selected" if payload.get("knowledge_base_ids") else "all")
        payload.setdefault("knowledge_base_ids", [])
        payload.setdefault("knowledge_bases", payload.get("knowledge_base_ids") or [])
        payload.setdefault("model_id", "")
        payload.setdefault("rerank_model_id", "")
        payload["allowed_tools"] = ["actor", "thinking"]
        payload["tools"] = ["actor", "thinking"]
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
            "id": f"builtin-multi-agent-assistant-{tenant.id}",
            "name": "智能助手",
            "description": "自动调度文档、Wiki、图谱子 Agent，适合默认问答入口。",
            "type": "multi-agent",
            "agent_mode": "multi-agent",
            "system_prompt": "你是多 Agent 知识工作台的主 Agent。简单问题可直接回答；需要文档证据时调用 doc_retriever；需要结构化知识时调用 wiki_researcher；需要实体关系推理时调用 graph_reasoner；需要综合多个结果时调用 answer_writer。",
            "allowed_tools": ["actor", "thinking"],
            "max_rounds": 8,
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
            {"id": "multi-agent", "type": "multi-agent", "name": "智能助手", "agent_mode": "multi-agent", "description": "自动调度文档、Wiki、图谱子 Agent"},
        ]
    return []
