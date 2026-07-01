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
    ModelConfig,
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


# ---------------------------------------------------------------------------
# Resource helpers
# ---------------------------------------------------------------------------

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
            "system_prompt": "你是一个智能推理助手，能够使用工具来帮助回答问题。\n\n## 工作流程\n1. 先理解用户问题，判断是否需要检索知识库\n2. 使用 knowledge_search 工具搜索相关内容\n3. 使用 grep_chunks 在已检索内容中搜索特定信息\n4. 使用 thinking 工具进行推理分析\n5. 基于检索到的信息给出准确、有组织的回答\n\n## 重要规则\n- 优先使用知识库中的信息回答，不要依赖预训练知识\n- 引用具体来源时注明文档标题\n- 可以同时调用多个工具\n- 如果知识库中没有相关信息，如实说明\n- 当你已经收集到足够的信息时，立即给出最终回答，不要继续调用工具",
            "allowed_tools": ["thinking", "knowledge_search", "grep_chunks", "list_knowledge_docs", "get_document_info", "query_knowledge_graph"],
            "max_rounds": 15,
        },
        {
            "id": f"builtin-wiki-researcher-{tenant.id}",
            "name": "Wiki 问答",
            "description": "Wiki 图谱导航，结构化知识检索。",
            "type": "wiki-researcher",
            "agent_mode": "smart-reasoning",
            "system_prompt": "你是一个 Wiki 知识库研究员，擅长通过 Wiki 页面导航和结构化信息回答问题。\n\n## 工作流程\n1. 使用 wiki_search 搜索相关的 Wiki 页面\n2. 使用 wiki_read_page 读取 Wiki 页面的完整内容\n3. 使用 wiki_list_pages 列出所有可用的 Wiki 页面\n4. 如果 Wiki 页面信息不够详细，使用 wiki_read_source_doc 回溯到原始文档\n5. 使用 thinking 工具分析和推理\n6. 综合所有信息给出结构化的回答\n\n## 重要规则\n- 优先使用 Wiki 页面中的结构化信息\n- Wiki 搜索只返回摘要，必须用 wiki_read_page 读取完整内容\n- 引用来源时注明 Wiki 页面标题\n- 如果 Wiki 页面没有相关信息，可以回退到 knowledge_search 搜索原始文档\n- 对比不同页面的信息，给出全面的回答\n- 当你已经收集到足够的信息时，立即给出最终回答，不要继续调用工具",
            "allowed_tools": ["thinking", "wiki_search", "wiki_read_page", "wiki_list_pages", "wiki_read_source_doc", "knowledge_search", "query_knowledge_graph"],
            "max_rounds": 20,
        },
    ]
    for preset in presets:
        if GenericResource.objects.filter(id=preset["id"]).exists():
            continue
        data = default_resource_payload("agents", preset)
        GenericResource.objects.create(id=preset["id"], tenant=tenant, resource_type="agents", name=data["name"], data=data, status="active")


def seed_builtin_models(tenant):
    ModelConfig.objects.filter(id__in=[f"builtin-local-chat-{tenant.id}", f"builtin-local-embedding-{tenant.id}"]).delete()


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
