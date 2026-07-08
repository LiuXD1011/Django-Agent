import logging
import re
import threading
import time

from django.db import close_old_connections
from django.db.utils import OperationalError
from django.utils import timezone

from .agent_history import normalize_max_rounds
from .model_providers import role_completion
from .models import Message, Session, Tenant

logger = logging.getLogger(__name__)


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

_DIRECT_GREETING_RE = re.compile(r"[\s，。！？!?,.、；;：:（）()【】\[\]\"'“”‘’~～]+")
_DIRECT_GREETINGS = {"你好", "您好", "嗨", "hi", "hello", "hey"}
_FULL_AGENT_HINTS = {
    "agent",
    "知识库",
    "文档",
    "文件",
    "资料",
    "引用",
    "检索",
    "搜索",
    "wiki",
    "图谱",
    "neo4j",
    "总结",
    "摘要",
    "上传",
    "当前",
    "有哪些",
    "内容",
    "问题",
    "测试",
    "流式",
    "非流式",
    "回答",
}
_SIMPLE_CHAT_HINTS = {"谢谢", "感谢", "没事", "不用了", "好的", "好呀", "可以", "在吗", "你是谁", "开个玩笑", "讲个笑话"}


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


def should_skip_expensive_prefetch(query: str, data: dict | None = None) -> bool:
    """Skip RAG/memory prefetch only when the main Agent can safely decide alone."""
    payload = data or {}
    text = (query or "").strip()
    if not text:
        return False
    if payload.get("images"):
        return False
    if payload.get("attachment_uploads") or payload.get("attachments"):
        return False
    if bool_from_value(payload.get("web_search_enabled"), False):
        return False
    if payload.get("mcp_service_ids") or payload.get("mcp_services"):
        return False
    mentioned_items = payload.get("mentioned_items") or []
    for item in mentioned_items:
        item_type = str(item.get("type") or item.get("kind") or "").lower() if isinstance(item, dict) else ""
        if item_type and item_type not in {"kb", "knowledge_base", "knowledgebase"}:
            return False
    text_lower = text.lower()
    if any(hint in text_lower for hint in _FULL_AGENT_HINTS):
        return False
    stripped = _DIRECT_GREETING_RE.sub("", text).lower()
    if stripped in _DIRECT_GREETINGS:
        return True
    return len(text) <= 24 and any(hint in text_lower for hint in _SIMPLE_CHAT_HINTS)


def _first_with_retry(queryset_factory):
    for attempt in range(5):
        try:
            return queryset_factory().first()
        except OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def save_session_state(session: Session, data: dict, kb_ids: list, query: str) -> None:
    state = session_state_from_payload(data, session.agent_config)
    state.update({
        "query": query,
        "knowledge_base_ids": kb_ids,
        "knowledge_ids": data.get("knowledge_ids") or [],
    })
    session.agent_config = state
    if data.get("agent_id"):
        session.agent_id = data.get("agent_id")
    session.save(update_fields=["agent_config", "agent_id", "updated_at"])


def schedule_title_generation(session_id: str, query: str, tenant_id: str | None = None, model_id: str = "") -> None:
    def _run():
        try:
            close_old_connections()
            session = _first_with_retry(lambda: Session.objects.filter(id=session_id))
            if not session or session.title not in {"", "新的对话"}:
                return
            tenant = _first_with_retry(lambda: Tenant.objects.filter(id=tenant_id)) if tenant_id else getattr(session, "tenant", None)
            title = role_completion(
                "title",
                f"请为下面这次知识库对话生成一个 20 字以内的中文标题，只输出标题。\n\n{query}",
                query,
                40,
                tenant=tenant,
                scenario="title",
            )[:80]
            if title:
                Session.objects.filter(id=session.id).update(title=title, updated_at=timezone.now())
        except Exception:
            logger.exception("Background title generation failed")
        finally:
            close_old_connections()

    threading.Thread(target=_run, daemon=True).start()


def schedule_chat_maintenance(
    *,
    tenant,
    user_message_id: str,
    assistant_message_id: str,
    session_id: str,
    query: str,
    answer: str,
    mode: str,
    max_rounds: int = 5,
    model_id: str = "",
    enable_memory: bool = False,
    user_id: str = "",
    enable_chat_history: bool = True,
    enable_snapshot: bool = True,
    indexer=None,
    snapshot_refresher=None,
) -> None:
    """Run slow post-answer maintenance outside the response hot path."""

    def _run():
        try:
            close_old_connections()
            if enable_memory and user_id:
                try:
                    from .memory import add_episode as memory_add_episode, is_memory_available

                    if is_memory_available():
                        memory_add_episode(
                            tenant,
                            user_id,
                            session_id,
                            [{"role": "user", "content": query}, {"role": "assistant", "content": answer}],
                        )
                except Exception:
                    logger.exception("Background memory store failed")

            user_message = _first_with_retry(lambda: Message.objects.filter(id=user_message_id))
            assistant_message = _first_with_retry(lambda: Message.objects.filter(id=assistant_message_id))
            if not user_message or not assistant_message:
                return

            if enable_chat_history:
                try:
                    if indexer is None:
                        from .chat_history_kb import index_qa_to_kb_async as indexer_fn
                    else:
                        indexer_fn = indexer

                    indexer_fn(tenant, user_message, assistant_message)
                except Exception:
                    logger.exception("Background ChatHistoryKB indexing failed")

            if enable_snapshot:
                try:
                    if snapshot_refresher is None:
                        from .context_snapshot import refresh_context_snapshot_async as snapshot_fn
                    else:
                        snapshot_fn = snapshot_refresher

                    snapshot_session = _first_with_retry(lambda: Session.objects.filter(id=assistant_message.session_id))
                    if not snapshot_session:
                        return
                    snapshot_fn(
                        session=snapshot_session,
                        tenant=tenant,
                        mode=mode,
                        max_rounds=normalize_max_rounds(max_rounds),
                        model_id=model_id,
                    )
                except Exception:
                    logger.exception("Background context snapshot refresh failed")
        except Exception:
            logger.exception("Background chat maintenance failed")
        finally:
            close_old_connections()

    threading.Thread(target=_run, daemon=True).start()
