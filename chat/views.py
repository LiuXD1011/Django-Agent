import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from django.db.models import Q
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from personal_knowledge_base.agent_history import (
    build_agent_context_if_needed,
    build_agent_history_messages,
    build_normal_rag_messages,
    build_rag_history_messages,
    normalize_max_rounds,
)
from personal_knowledge_base.chat_history_kb import index_qa_to_kb_async
from personal_knowledge_base.context_snapshot import (
    build_agent_history_with_snapshot,
    build_rag_history_with_snapshot,
    clear_context_snapshots,
    refresh_context_snapshot_async,
)
from personal_knowledge_base.agent_engine import AgentEngine
from personal_knowledge_base.memory import add_episode as memory_add_episode, is_memory_available, retrieve_memory
from personal_knowledge_base.model_providers import ModelConfigurationError, chat_completion, chat_completion_stream, role_completion
from personal_knowledge_base.models import KnowledgeBase, Message, Session
from personal_knowledge_base.query_understand import INTENT_KB_SEARCH, get_intent_system_prompt, needs_retrieval, understand_query
from personal_knowledge_base.responses import fail, ok
from personal_knowledge_base.search import hybrid_search
from personal_knowledge_base.serializers import message_dict, session_dict
from personal_knowledge_base.stream_manager import stream_manager

from personal_knowledge_base.authentication import require_auth

logger = logging.getLogger(__name__)


# ── Helper functions (copied from personal_knowledge_base/views.py) ──────

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


def bool_from_value(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on", "enabled"}


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


# ── Session CRUD ─────────────────────────────────────────────────────────

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


# ── Session actions ──────────────────────────────────────────────────────

@csrf_exempt
def session_messages_clear(request, session_id):
    session = get_object_or_404(Session, id=session_id)
    clear_context_snapshots(session)
    Message.objects.filter(session=session).delete()
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


# ── Continue stream (断线重连) ──────────────────────────────────────────

@csrf_exempt
def continue_stream(request, session_id):
    """
    Continue-stream 端点：断线重连。

    当前端刷新页面或重新打开有未完成消息的会话时，自动发起此请求。
    从 StreamManager 回放已产生的事件，并继续推送新事件直到完成。

    参考同类知识库系统的 ContinueStream 实现。
    """
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)

    session = get_object_or_404(Session, id=session_id, tenant=tenant)

    # 获取 message_id（支持 query param 或 body）
    message_id = request.GET.get("message_id") or request.GET.get("query")
    if not message_id:
        data = parse_body(request) if request.method == "POST" else {}
        message_id = data.get("message_id") or data.get("query")

    if not message_id:
        return fail("message_id is required", 400)

    # 查找消息
    message = Message.objects.filter(
        Q(id=message_id) | Q(request_id=message_id),
        session_id=session_id,
    ).first()

    if not message:
        return fail("message not found", 404)

    # 如果消息已完成，直接返回完成事件
    if message.is_completed:
        def done_events():
            payload = message_dict(message)
            yield f"event: message\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            yield f"event: message\ndata: {json.dumps({'response_type': 'complete', 'assistant_message_id': message.id, 'done': True}, ensure_ascii=False)}\n\n"
            yield f"event: done\ndata: {json.dumps({'message_id': message.id}, ensure_ascii=False)}\n\n"

        return StreamingHttpResponse(done_events(), content_type="text/event-stream")

    # 消息未完成：从 StreamManager 回放事件并继续推送
    msg_id = message.id

    def replay_events():
        # 发送初始事件
        yield f"event: message_start\ndata: {json.dumps({'id': msg_id, 'request_id': message.request_id}, ensure_ascii=False)}\n\n"
        yield f"event: message\ndata: {json.dumps({'response_type': 'agent_query', 'assistant_message_id': msg_id, 'session_id': session_id, 'content': '', 'done': False}, ensure_ascii=False)}\n\n"

        offset = 0
        max_wait = 120  # 最多等待 2 分钟
        waited = 0

        while waited < max_wait:
            events = stream_manager.get_events(msg_id, offset)
            for event in events:
                event_type = event.event_type
                event_data = event.data
                if event_type == "thinking":
                    yield f"event: message\ndata: {json.dumps({'response_type': 'answer', 'assistant_message_id': msg_id, 'content': event_data.get('content', ''), 'done': False}, ensure_ascii=False)}\n\n"
                elif event_type == "tool_call":
                    yield f"event: message\ndata: {json.dumps({'response_type': 'tool_call', 'assistant_message_id': msg_id, 'name': event_data.get('name', ''), 'arguments': event_data.get('arguments', {}), 'iteration': event_data.get('iteration', 0)}, ensure_ascii=False)}\n\n"
                elif event_type == "tool_result":
                    yield f"event: message\ndata: {json.dumps({'response_type': 'tool_result', 'assistant_message_id': msg_id, 'name': event_data.get('name', ''), 'output': event_data.get('output', '')[:300], 'duration_ms': event_data.get('duration_ms', 0)}, ensure_ascii=False)}\n\n"
                elif event_type == "complete":
                    # 生成完成
                    stream_obj = stream_manager.get_stream(msg_id)
                    final_content = stream_obj.final_content if stream_obj else event_data.get("content", "")
                    final_refs = stream_obj.final_refs if stream_obj else []
                    yield f"event: message\ndata: {json.dumps({'response_type': 'answer', 'assistant_message_id': msg_id, 'content': final_content, 'done': True, 'knowledge_references': final_refs}, ensure_ascii=False)}\n\n"
                    yield f"event: message\ndata: {json.dumps({'response_type': 'complete', 'assistant_message_id': msg_id, 'done': True}, ensure_ascii=False)}\n\n"
                    yield f"event: done\ndata: {json.dumps({'message_id': msg_id}, ensure_ascii=False)}\n\n"
                    return
                elif event_type == "error":
                    yield f"event: message\ndata: {json.dumps({'response_type': 'error', 'assistant_message_id': msg_id, 'content': event_data.get('content', '生成失败'), 'done': True}, ensure_ascii=False)}\n\n"
                    yield f"event: done\ndata: {json.dumps({'message_id': msg_id}, ensure_ascii=False)}\n\n"
                    return

            offset += len(events)

            # 检查 StreamManager 中是否已完成
            if stream_manager.is_complete(msg_id) and not events:
                # 已完成但没有更多事件（可能 TTL 过期了）
                # 从数据库读取最终结果
                msg = Message.objects.filter(id=msg_id).first()
                if msg and msg.is_completed:
                    payload = message_dict(msg)
                    yield f"event: message\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    yield f"event: message\ndata: {json.dumps({'response_type': 'complete', 'assistant_message_id': msg_id, 'done': True}, ensure_ascii=False)}\n\n"
                yield f"event: done\ndata: {json.dumps({'message_id': msg_id}, ensure_ascii=False)}\n\n"
                return

            # 等待新事件
            time.sleep(0.1)
            waited += 0.1

        # 超时：标记为完成
        yield f"event: message\ndata: {json.dumps({'response_type': 'error', 'assistant_message_id': msg_id, 'content': '等待超时', 'done': True}, ensure_ascii=False)}\n\n"
        yield f"event: done\ndata: {json.dumps({'message_id': msg_id}, ensure_ascii=False)}\n\n"

    return StreamingHttpResponse(replay_events(), content_type="text/event-stream")


# ── Messages ─────────────────────────────────────────────────────────────

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


# ── Context building helpers ─────────────────────────────────────────────

def _build_document_header(refs: list[dict]) -> str:
    """构建文档头部 XML，列出所有涉及的知识条目及其描述。参考同类知识库系统的 buildDocumentHeader。"""
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
    """构建结构化 XML context，每个 chunk 带编号。参考同类知识库系统的 into_chat_message。"""
    parts = []
    for i, r in enumerate(refs[:5], 1):
        content = r.get("content", "").strip()
        if content:
            parts.append(f'<context id="{i}">{content}</context>')
    return "\n".join(parts)


def _build_context_with_memory(refs: list[dict], memory_str: str, kb_names: str = "") -> str:
    """组装完整的上下文：知识库信息 + 文档头 + 结构化 context + 记忆。"""
    parts = []
    if kb_names:
        parts.append(f"<knowledge_base>\n{kb_names}\n</knowledge_base>")
    doc_header = _build_document_header(refs)
    if doc_header:
        parts.append(doc_header)
    structured = _build_structured_context(refs)
    if structured:
        parts.append(structured)
    if memory_str:
        parts.append(memory_str)
    return "\n\n".join(parts)


SYSTEM_PROMPT_DEFAULT = (
    "你是一个知识库问答助手。请根据提供的知识库上下文回答用户问题。\n\n"
    "## 回答要求\n"
    "- 优先使用上下文中的信息回答，不要依赖预训练知识\n"
    "- 如果上下文包含文档列表，请整理后以清晰的格式列出（标题 + 简要描述）\n"
    "- 引用具体来源时注明文档标题\n"
    "- 如果上下文中没有相关信息，如实说明\n"
    "- 回答要有条理，使用标题、列表等格式组织信息\n"
    "- 对于元问题（如'选择了哪个知识库'、'有哪些文件'），基于上下文中的知识库和文档信息回答\n"
    "- 引用具体来源时注明文档标题\n"
    "- 如果上下文中没有相关信息，如实说明"
)


# ── Session save after chat ──────────────────────────────────────────────

def _save_session_after_chat(session, data, kb_ids, query, tenant):
    """保存 session 配置和标题（对话完成后调用）。"""
    try:
        state = session_state_from_payload(data, session.agent_config)
        state.update({
            "query": query,
            "knowledge_base_ids": kb_ids,
            "knowledge_ids": data.get("knowledge_ids") or [],
        })
        session.agent_config = state
        if data.get("agent_id"):
            session.agent_id = data.get("agent_id")
        if session.title in {"", "新的对话"}:
            try:
                session.title = role_completion("title", f"请为下面这次知识库对话生成一个 20 字以内的中文标题，只输出标题。\n\n{query}", query, 40)[:80] or session.title
            except Exception:
                pass
        session.save(update_fields=["agent_config", "agent_id", "title", "updated_at"])
    finally:
        # 关闭数据库连接以释放锁
        from django.db import connection
        try:
            connection.close()
        except Exception:
            pass


# ── Agent generation (background thread) ─────────────────────────────────

def _run_agent_generation(
    assistant_msg_id: str,
    session_id: str,
    user_msg_id: str,
    query: str,
    history_msgs: list,
    agent_context: str,
    agent_config: dict,
    refs: list,
    tenant,
    user_id: str,
    enable_memory: bool,
    user=None,
):
    """
    在独立线程中运行 Agent 生成。
    事件通过 StreamManager 持久化，不依赖 SSE 连接。
    即使客户端断开，生成也会继续完成。
    """
    stream = stream_manager.create_stream(assistant_msg_id, session_id)

    try:
        engine = AgentEngine(
            tenant=tenant,
            session_id=session_id,
            user_id=user_id,
            agent_config=agent_config,
        )

        collected_content = []
        last_saved_content = {"text": ""}

        def on_event(event_type, event_data):
            collected_content.append((event_type, event_data))
            # 存入 StreamManager
            stream.append_event(event_type, event_data)
            # 定期保存中间内容到数据库
            if event_type == "thinking":
                content = event_data.get("content", "")
                if content and len(content) > len(last_saved_content["text"]):
                    last_saved_content["text"] = content
                    try:
                        Message.objects.filter(id=assistant_msg_id).update(
                            content=content,
                            rendered_content=content,
                            updated_at=timezone.now(),
                        )
                    except Exception:
                        pass

        # 执行 Agent
        result = engine.execute(query, history=history_msgs, context_str=agent_context, on_event=on_event)

        # 更新 assistant 消息（最终状态）
        Message.objects.filter(id=assistant_msg_id).update(
            content=result.content,
            rendered_content=result.content,
            knowledge_references=refs,
            agent_steps=[s.to_dict() for s in result.steps],
            agent_duration_ms=result.duration_ms,
            is_completed=True,
            updated_at=timezone.now(),
        )

        # 设置最终结果到 stream（用于 continue-stream 回放）
        stream.set_final_result(
            content=result.content,
            refs=refs,
            steps=[s.to_dict() for s in result.steps],
            duration_ms=result.duration_ms,
        )

        # 追加 complete 事件
        stream.append_event("complete", {"done": True, "content": result.content})

        # 记忆存储
        if enable_memory and user and is_memory_available():
            try:
                memory_add_episode(tenant, user_id, session_id, [
                    {"role": "user", "content": query},
                    {"role": "assistant", "content": result.content},
                ])
            except Exception:
                pass

        user_message = Message.objects.filter(id=user_msg_id).first()
        assistant_message = Message.objects.filter(id=assistant_msg_id).first()
        if user_message and assistant_message:
            index_qa_to_kb_async(tenant, user_message, assistant_message)
            refresh_context_snapshot_async(
                session=assistant_message.session,
                tenant=tenant,
                mode="agent",
                max_rounds=agent_config.get("max_rounds", 5),
                model_id=agent_config.get("model_id", ""),
            )

        logger.info(f"[Agent] Generation completed for message {assistant_msg_id}")

    except Exception as e:
        logger.exception(f"[Agent] Generation failed for message {assistant_msg_id}")
        stream.append_event("error", {"content": str(e)})
        # 标记消息为完成（带错误）
        try:
            Message.objects.filter(id=assistant_msg_id).update(
                content=f"生成失败: {e}",
                rendered_content=f"生成失败: {e}",
                is_completed=True,
                updated_at=timezone.now(),
            )
        except Exception:
            pass
    finally:
        # 关闭数据库连接以释放锁
        from django.db import connection
        try:
            connection.close()
        except Exception:
            pass


# ── Speed optimization helpers ───────────────────────────────────────────

def _quick_intent_detect(query: str) -> str | None:
    """
    快速意图检测：对简单查询用正则规则判断，跳过 LLM 调用。
    参考同类知识库系统的条件跳过设计。

    Returns:
        意图字符串（如果可以快速判断），None（如果需要 LLM 识别）
    """
    q = query.strip()
    # 短问候语
    if len(q) < 10 and any(w in q for w in ["你好", "hello", "hi", "嗨", "您好", "hey"]):
        return "chitchat"
    # 短查询且是问句形式，直接走搜索
    if len(q) < 20 and ("?" in q or "？" in q or q.startswith(("什么", "怎么", "如何", "为什么", "哪", "谁", "几"))):
        return INTENT_KB_SEARCH
    # 很短的查询，直接走搜索
    if len(q) < 8:
        return INTENT_KB_SEARCH
    # 其他情况需要 LLM 识别
    return None


def _safe_understand_query(tenant, query: str) -> dict | None:
    """线程安全的查询理解包装"""
    try:
        return understand_query(tenant, query)
    except Exception:
        logger.exception("Query understanding failed in parallel task")
        return None


def _safe_retrieve_memory(tenant, user_id: str, query: str) -> str:
    """线程安全的记忆检索包装，返回格式化的记忆上下文字符串"""
    try:
        from personal_knowledge_base.chat_history_kb import sanitize_internal_kb_mentions
        mem_ctx = retrieve_memory(tenant, user_id, query)
        if mem_ctx.related_episodes:
            return "\n\n<relevant_memory>\n" + "\n".join(
                f"- {sanitize_internal_kb_mentions(tenant, ep.summary)}" for ep in mem_ctx.related_episodes
            ) + "\n</relevant_memory>"
    except Exception:
        logger.exception("Memory retrieval failed in parallel task")
    return ""


# ── Core chat endpoint ───────────────────────────────────────────────────

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
    # 知识库选择：优先使用请求指定 > session 绑定 > 空列表（不自动选择所有）
    # 参考同类知识库系统：必须明确指定知识库，不自动回退到所有知识库
    kb_ids = data.get("knowledge_base_ids") or ([session.knowledge_base_id] if session.knowledge_base_id else [])

    # ── RAG 管道执行 ──────────────────────────────────────────────
    # 参考同类知识库系统的 KnowledgeQA 管道：
    # 1. 查询理解（并行） 2. 记忆检索（并行） 3. 知识库检索 4. 构建上下文
    enable_memory = data.get("enable_memory")
    if enable_memory is None:
        enable_memory = (user.preferences or {}).get("enable_memory", True)

    from personal_knowledge_base.rag_pipeline import run_rag_pipeline
    rag_ctx = run_rag_pipeline(
        tenant=tenant,
        query=query,
        kb_ids=kb_ids,
        session=session,
        user=user,
        enable_memory=enable_memory,
        model_id=data.get("model_id", ""),
    )

    # 提取管道结果
    intent = rag_ctx.intent
    search_query = rag_ctx.search_query
    refs = rag_ctx.refs
    memory_context_str = rag_ctx.memory_context
    system_prompt = rag_ctx.system_prompt
    user_prompt = rag_ctx.user_prompt
    kb_names_str = rag_ctx.kb_names

    # 保存 RAG 增强后的用户消息到 rendered_content（参考同类知识库系统）
    # 后续轮次回放时使用增强版本，保留检索上下文
    if user_prompt != query:
        user_msg.rendered_content = user_prompt
        user_msg.save(update_fields=["rendered_content", "updated_at"])

    # ── Stage 5: 生成回答（Agent 模式 vs 普通模式）─────────────────
    agent_steps_data = []
    agent_duration_ms = 0

    if agent:
        # ── Agent 模式：ReAct 循环 ────────────────────────────────
        from personal_knowledge_base.models import GenericResource

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
        agent_config["max_rounds"] = normalize_max_rounds(agent_config.get("max_rounds", 5))

        engine = AgentEngine(
            tenant=tenant,
            session_id=str(session.id),
            user_id=str(user.id) if user else "",
            agent_config=agent_config,
        )

        # 构建历史对话（最近 max_rounds 轮），包含历史 Agent tool_calls/tool results
        history_msgs = build_agent_history_with_snapshot(
            session=session,
            current_user_message=user_msg,
            max_rounds=agent_config["max_rounds"],
            history_builder=build_agent_history_messages,
        )

        # 构建知识库上下文（知识库信息 + 文档头 + chunk 内容）注入 Agent
        agent_memory_context = "\n\n".join(part for part in [memory_context_str, getattr(rag_ctx, "chat_history_context", "")] if part)
        agent_context = build_agent_context_if_needed(_build_context_with_memory, refs, agent_memory_context, kb_names_str)

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

            # 保存 session 配置（在启动线程之前执行）
            _save_session_after_chat(session, data, kb_ids, query, tenant)

            # 启动独立线程执行 Agent 生成
            # 线程不依赖 SSE 连接，客户端断开后仍会继续完成
            gen_thread = threading.Thread(
                target=_run_agent_generation,
                kwargs={
                    "assistant_msg_id": assistant.id,
                    "session_id": str(session.id),
                    "user_msg_id": str(user_msg.id),
                    "query": query,
                    "history_msgs": history_msgs,
                    "agent_context": agent_context,
                    "agent_config": agent_config,
                    "refs": refs,
                    "tenant": tenant,
                    "user_id": str(user.id) if user else "",
                    "enable_memory": enable_memory,
                    "user": user,
                },
                daemon=True,
            )
            gen_thread.start()

            # SSE 处理器：从 StreamManager 读取事件并推送给客户端
            # 客户端断开时仅停止推送，不影响生成线程
            def agent_events():
                # 发送初始事件
                yield f"event: message_start\ndata: {json.dumps({'id': assistant.id, 'request_id': request_id}, ensure_ascii=False)}\n\n"
                yield f"event: message\ndata: {json.dumps({'response_type': 'agent_query', 'assistant_message_id': assistant.id, 'session_id': str(session.id), 'content': '', 'done': False}, ensure_ascii=False)}\n\n"

                offset = 0
                while True:
                    events = stream_manager.get_events(assistant.id, offset)
                    for event in events:
                        event_type = event.event_type
                        event_data = event.data
                        if event_type == "thinking":
                            yield f"event: message\ndata: {json.dumps({'response_type': 'answer', 'assistant_message_id': assistant.id, 'content': event_data.get('content', ''), 'done': False}, ensure_ascii=False)}\n\n"
                        elif event_type == "tool_call":
                            yield f"event: message\ndata: {json.dumps({'response_type': 'tool_call', 'assistant_message_id': assistant.id, 'name': event_data.get('name', ''), 'arguments': event_data.get('arguments', {}), 'iteration': event_data.get('iteration', 0)}, ensure_ascii=False)}\n\n"
                        elif event_type == "tool_result":
                            yield f"event: message\ndata: {json.dumps({'response_type': 'tool_result', 'assistant_message_id': assistant.id, 'name': event_data.get('name', ''), 'output': event_data.get('output', '')[:300], 'duration_ms': event_data.get('duration_ms', 0)}, ensure_ascii=False)}\n\n"
                        elif event_type == "complete":
                            # 生成完成，发送最终事件
                            stream_obj = stream_manager.get_stream(assistant.id)
                            final_content = stream_obj.final_content if stream_obj else event_data.get("content", "")
                            final_refs = stream_obj.final_refs if stream_obj else refs
                            yield f"event: message\ndata: {json.dumps({'response_type': 'answer', 'assistant_message_id': assistant.id, 'content': final_content, 'done': True, 'knowledge_references': final_refs}, ensure_ascii=False)}\n\n"
                            yield f"event: message\ndata: {json.dumps({'response_type': 'complete', 'assistant_message_id': assistant.id, 'done': True}, ensure_ascii=False)}\n\n"
                            yield f"event: done\ndata: {json.dumps({'message_id': assistant.id}, ensure_ascii=False)}\n\n"
                            return
                        elif event_type == "error":
                            yield f"event: message\ndata: {json.dumps({'response_type': 'error', 'assistant_message_id': assistant.id, 'content': event_data.get('content', '生成失败'), 'done': True}, ensure_ascii=False)}\n\n"
                            yield f"event: done\ndata: {json.dumps({'message_id': assistant.id}, ensure_ascii=False)}\n\n"
                            return

                    offset += len(events)

                    # 检查是否已完成（可能在我们轮询期间完成）
                    if stream_manager.is_complete(assistant.id) and not events:
                        # 已完成且没有新事件，退出
                        return

                    # 等待新事件（100ms 轮询间隔）
                    time.sleep(0.1)

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
            index_qa_to_kb_async(tenant, user_msg, assistant)
            refresh_context_snapshot_async(
                session=session,
                tenant=tenant,
                mode="agent",
                max_rounds=agent_config["max_rounds"],
                model_id=agent_config.get("model_id", ""),
            )
    else:
        # ── 普通模式：单次 LLM 调用 ──────────────────────────────
        rag_max_rounds = normalize_max_rounds(session.max_rounds)
        history_msgs = build_rag_history_with_snapshot(
            session=session,
            current_user_message=user_msg,
            max_rounds=rag_max_rounds,
            history_builder=build_rag_history_messages,
        )
        llm_messages = build_normal_rag_messages(system_prompt, history_msgs, user_prompt)
        model_id = data.get("model_id", "")
        is_streaming = request.headers.get("Accept", "").find("text/event-stream") >= 0 or data.get("stream")

        if is_streaming:
            # ── 真正的逐 token 流式输出（经过 StreamManager 解耦）──
            # 参考同类知识库系统：所有模式统一经过 StreamManager，支持断线重连
            assistant = Message.objects.create(
                session=session,
                request_id=request_id,
                role="assistant",
                content="",
                rendered_content="",
                knowledge_references=refs,
                agent_steps=[{"type": "knowledge_search", "query": search_query, "intent": intent, "count": len(refs)}],
                is_completed=False,
                channel=data.get("channel", "web"),
            )

            # 保存 session 配置（在启动线程之前执行）
            _save_session_after_chat(session, data, kb_ids, query, tenant)

            # 创建 StreamManager 流
            stream = stream_manager.create_stream(assistant.id, str(session.id))

            # 启动独立线程执行 LLM 生成
            def _run_normal_generation():
                """普通模式生成线程，事件写入 StreamManager"""
                try:
                    collected = ""
                    for token in chat_completion_stream(tenant, llm_messages, model_id):
                        collected += token
                        stream.append_event("thinking", {"content": collected})

                    # 生成完成
                    stream.set_final_result(content=collected, refs=refs)
                    stream.append_event("complete", {"done": True, "content": collected})

                    # 更新消息
                    Message.objects.filter(id=assistant.id).update(
                        content=collected,
                        rendered_content=collected,
                        is_completed=True,
                        updated_at=timezone.now(),
                    )
                    assistant.content = collected
                    assistant.rendered_content = collected
                    assistant.is_completed = True

                    # 异步记忆存储
                    if enable_memory and user and is_memory_available():
                        threading.Thread(
                            target=_async_memory_store,
                            args=(tenant, str(user.id), str(session.id), query, collected),
                            daemon=True,
                        ).start()

                    index_qa_to_kb_async(tenant, user_msg, assistant)
                    refresh_context_snapshot_async(
                        session=session,
                        tenant=tenant,
                        mode="rag",
                        max_rounds=rag_max_rounds,
                        model_id=model_id,
                    )

                except Exception as exc:
                    logger.warning(f"Normal stream generation failed: {exc}")
                    # 回退到非流式
                    try:
                        collected = chat_completion(tenant, llm_messages, model_id)
                    except Exception:
                        collected = local_answer(query, refs, agent=False)

                    stream.set_final_result(content=collected, refs=refs)
                    stream.append_event("complete", {"done": True, "content": collected})

                    Message.objects.filter(id=assistant.id).update(
                        content=collected,
                        rendered_content=collected,
                        is_completed=True,
                        updated_at=timezone.now(),
                    )
                    assistant.content = collected
                    assistant.rendered_content = collected
                    assistant.is_completed = True
                    index_qa_to_kb_async(tenant, user_msg, assistant)
                    refresh_context_snapshot_async(
                        session=session,
                        tenant=tenant,
                        mode="rag",
                        max_rounds=rag_max_rounds,
                        model_id=model_id,
                    )

            threading.Thread(target=_run_normal_generation, daemon=True).start()

            # SSE 处理器：从 StreamManager 读取事件
            def normal_stream_events():
                yield f"event: message_start\ndata: {json.dumps({'id': assistant.id, 'request_id': request_id}, ensure_ascii=False)}\n\n"
                yield f"event: message\ndata: {json.dumps({'response_type': 'agent_query', 'assistant_message_id': assistant.id, 'session_id': str(session.id), 'content': '', 'done': False}, ensure_ascii=False)}\n\n"

                offset = 0
                while True:
                    events = stream_manager.get_events(assistant.id, offset)
                    for event in events:
                        if event.event_type == "thinking":
                            yield f"event: message\ndata: {json.dumps({'response_type': 'answer', 'assistant_message_id': assistant.id, 'content': event.data.get('content', ''), 'done': False}, ensure_ascii=False)}\n\n"
                        elif event.event_type == "complete":
                            final_content = event.data.get("content", "")
                            yield f"event: message\ndata: {json.dumps({'response_type': 'answer', 'assistant_message_id': assistant.id, 'content': final_content, 'done': True, 'knowledge_references': refs}, ensure_ascii=False)}\n\n"
                            yield f"event: message\ndata: {json.dumps({'response_type': 'complete', 'assistant_message_id': assistant.id, 'done': True}, ensure_ascii=False)}\n\n"
                            yield f"event: done\ndata: {json.dumps({'message_id': assistant.id}, ensure_ascii=False)}\n\n"
                            return

                    offset += len(events)
                    if stream_manager.is_complete(assistant.id) and not events:
                        return
                    time.sleep(0.1)

            return StreamingHttpResponse(normal_stream_events(), content_type="text/event-stream")
        else:
            # 非流式模式
            try:
                answer = chat_completion(tenant, llm_messages, model_id)
            except (ModelConfigurationError, Exception):
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
            index_qa_to_kb_async(tenant, user_msg, assistant)
            refresh_context_snapshot_async(
                session=session,
                tenant=tenant,
                mode="rag",
                max_rounds=rag_max_rounds,
                model_id=model_id,
            )

            # 异步记忆存储 + 标题生成（不阻塞响应）
            if enable_memory and user and is_memory_available():
                threading.Thread(
                    target=_async_memory_store,
                    args=(tenant, str(user.id), str(session.id), query, answer),
                    daemon=True,
                ).start()
            threading.Thread(
                target=_save_session_after_chat,
                args=(session, data, kb_ids, query, tenant),
                daemon=True,
            ).start()

            return ok({"message": message_dict(assistant), "answer": assistant.content, "references": refs})


# ── Async memory store ───────────────────────────────────────────────────

def _async_memory_store(tenant, user_id: str, session_id: str, query: str, answer: str):
    """异步记忆存储，不阻塞主流程"""
    try:
        memory_add_episode(
            tenant, user_id, session_id,
            [{"role": "user", "content": query}, {"role": "assistant", "content": answer}],
        )
    except Exception:
        logger.exception("Async memory store failed")


# ── Stream message helper ────────────────────────────────────────────────

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


# ── Local fallback answer ────────────────────────────────────────────────

def local_answer(query: str, refs: list[dict], agent=False):
    if not refs:
        return "很抱歉，我暂时无法在当前知识库中找到相关内容。"
    intro = "我根据知识库检索到了以下相关内容："
    bullets = "\n".join(f"- {r['knowledge_title']}: {r['content'][:180]}" for r in refs[:3])
    return f"{intro}\n{bullets}"
