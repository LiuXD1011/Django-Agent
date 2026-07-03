"""
ChatHistoryKB：对话历史知识库

参考 WeKnora 的 ChatHistoryKB 设计：
- 将对话历史索引到专用知识库
- 支持 keyword/vector/hybrid 三种搜索模式
- 可用于检索历史对话中的相关信息

注意：这是一个可选功能，需要在 Tenant 配置中启用。
"""

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# ChatHistoryKB 配置键
CHAT_HISTORY_KB_CONFIG_KEY = "chat_history_config"

# 默认配置
DEFAULT_CONFIG = {
    "enabled": False,
    "embedding_model_id": "",
    "knowledge_base_id": "",
}


def get_chat_history_config(tenant) -> dict:
    """获取租户的 ChatHistoryKB 配置。"""
    config = tenant.chat_history_config or {}
    return {**DEFAULT_CONFIG, **config}


def is_chat_history_enabled(tenant) -> bool:
    """检查 ChatHistoryKB 是否启用。"""
    config = get_chat_history_config(tenant)
    return config.get("enabled", False)


def sanitize_internal_kb_mentions(tenant, text: str) -> str:
    """Hide internal/system-managed KB names before injecting history into prompts."""
    if not text:
        return ""
    sanitized = str(text)
    internal_names = {"__chat_history__"}
    try:
        from .models import KnowledgeBase
        internal_names.update(
            KnowledgeBase.objects.filter(
                tenant=tenant,
                is_temporary=True,
                deleted_at__isnull=True,
            ).values_list("name", flat=True)
        )
    except Exception:
        pass
    for name in sorted((n for n in internal_names if n), key=len, reverse=True):
        sanitized = sanitized.replace(name, "[internal history]")
    return sanitized


def render_qa_pair_for_index(user_message, assistant_message) -> str:
    user_content = getattr(user_message, "rendered_content", "") or getattr(user_message, "content", "")
    assistant_content = getattr(assistant_message, "content", "")
    return f"User:\n{user_content}\n\nAssistant:\n{assistant_content}".strip()


def get_or_create_chat_history_kb(tenant) -> Optional[str]:
    """
    获取或创建 ChatHistoryKB。
    返回 KnowledgeBase ID。
    """
    from .models import KnowledgeBase

    config = get_chat_history_config(tenant)
    kb_id = config.get("knowledge_base_id", "")

    if kb_id:
        kb = KnowledgeBase.objects.filter(id=kb_id, tenant=tenant, deleted_at__isnull=True).first()
        if kb:
            return kb_id

    # 创建新的 ChatHistoryKB（参考 WeKnora：标记为系统内部知识库，不在前端显示）
    kb = KnowledgeBase.objects.create(
        tenant=tenant,
        name="__chat_history__",
        description="Auto-managed knowledge base for chat history message indexing",
        type="document",
        is_temporary=True,  # ← 关键：标记为系统内部，参考 WeKnora 的 IsTemporary: true
    )

    # 更新配置
    config["knowledge_base_id"] = str(kb.id)
    tenant.chat_history_config = config
    tenant.save(update_fields=["chat_history_config", "updated_at"])

    logger.info(f"[ChatHistoryKB] Created chat history KB: {kb.id}")
    return str(kb.id)


def index_message_to_kb_async(tenant, message):
    """
    异步将消息索引到 ChatHistoryKB。
    参考 WeKnora 的 IndexMessageToKB。
    """
    if not is_chat_history_enabled(tenant):
        return

    def _index():
        try:
            _index_message(tenant, message)
        except Exception as e:
            logger.exception(f"[ChatHistoryKB] Failed to index message: {e}")

    thread = threading.Thread(target=_index, daemon=True)
    thread.start()


def index_qa_to_kb_async(tenant, user_message, assistant_message):
    """Asynchronously index a completed Q&A pair into ChatHistoryKB."""
    if not is_chat_history_enabled(tenant):
        return

    def _index():
        try:
            _index_qa_pair(tenant, user_message, assistant_message)
        except Exception as e:
            logger.exception(f"[ChatHistoryKB] Failed to index QA pair: {e}")

    thread = threading.Thread(target=_index, daemon=True)
    thread.start()


def _index_message(tenant, message):
    """
    将消息索引到 ChatHistoryKB。
    创建一个 Knowledge 记录，内容为消息内容。
    """
    from .models import Knowledge, KnowledgeBase, Chunk

    kb_id = get_or_create_chat_history_kb(tenant)
    if not kb_id:
        return

    kb = KnowledgeBase.objects.filter(id=kb_id, tenant=tenant).first()
    if not kb:
        return

    # 检查是否已索引
    existing = Knowledge.objects.filter(
        tenant=tenant,
        knowledge_base=kb,
        metadata__message_id=str(message.id),
    ).first()
    if existing:
        return

    # 创建 Knowledge 记录
    content = message.content or ""
    if not content.strip():
        return

    knowledge = Knowledge.objects.create(
        tenant=tenant,
        knowledge_base=kb,
        type="file",
        title=f"Chat message {message.id[:8]}",
        description=f"Session: {message.session_id}, Role: {message.role}",
        source="chat_history",
        parse_status="completed",
        file_name=f"chat_{message.id[:8]}.txt",
        file_type="txt",
        metadata={
            "message_id": str(message.id),
            "session_id": str(message.session_id),
            "role": message.role,
            "request_id": message.request_id,
            "created_at": message.created_at.isoformat() if message.created_at else "",
        },
    )

    # 创建 Chunk
    Chunk.objects.create(
        tenant=tenant,
        knowledge_base=kb,
        knowledge=knowledge,
        content=content,
        chunk_index=0,
        is_enabled=True,
    )

    logger.debug(f"[ChatHistoryKB] Indexed message {message.id[:8]}")


def _index_qa_pair(tenant, user_message, assistant_message):
    """Create one Knowledge/Chunk from a completed user+assistant turn."""
    from .models import Knowledge, KnowledgeBase, Chunk

    kb_id = get_or_create_chat_history_kb(tenant)
    if not kb_id:
        return

    kb = KnowledgeBase.objects.filter(id=kb_id, tenant=tenant).first()
    if not kb:
        return

    assistant_id = str(getattr(assistant_message, "id", ""))
    request_id = getattr(assistant_message, "request_id", "") or getattr(user_message, "request_id", "")
    existing = Knowledge.objects.filter(
        tenant=tenant,
        knowledge_base=kb,
        metadata__assistant_message_id=assistant_id,
    ).first()
    if assistant_id and existing:
        return

    content = render_qa_pair_for_index(user_message, assistant_message)
    if not content.strip():
        return

    created_at = getattr(assistant_message, "created_at", None)
    knowledge = Knowledge.objects.create(
        tenant=tenant,
        knowledge_base=kb,
        type="file",
        title=f"Chat turn {str(request_id or assistant_id)[:8]}",
        description=f"Session: {getattr(assistant_message, 'session_id', '')}, Q&A pair",
        source="chat_history",
        parse_status="completed",
        file_name=f"chat_turn_{str(request_id or assistant_id)[:8]}.txt",
        file_type="txt",
        metadata={
            "user_message_id": str(getattr(user_message, "id", "")),
            "assistant_message_id": assistant_id,
            "session_id": str(getattr(assistant_message, "session_id", getattr(user_message, "session_id", ""))),
            "request_id": str(request_id or ""),
            "created_at": created_at.isoformat() if created_at else "",
        },
    )
    Chunk.objects.create(
        tenant=tenant,
        knowledge_base=kb,
        knowledge=knowledge,
        content=content,
        chunk_index=0,
        is_enabled=True,
    )
    logger.debug(f"[ChatHistoryKB] Indexed QA pair {str(request_id or assistant_id)[:8]}")


def format_chat_history_context(results: list[dict], tenant=None, limit: int = 5) -> str:
    """Format hidden chat-history search hits for prompt injection."""
    if not results:
        return ""
    lines = ["<chat_history_context>"]
    for idx, item in enumerate(results[:limit], 1):
        title = sanitize_internal_kb_mentions(tenant, item.get("knowledge_title", "历史对话")) if tenant else item.get("knowledge_title", "历史对话")
        content = sanitize_internal_kb_mentions(tenant, item.get("content", "")) if tenant else item.get("content", "")
        content = content[:800]
        lines.append(f"[{idx}] {title}\n{content}")
    lines.append("</chat_history_context>")
    return "\n".join(lines)


def search_chat_history(tenant, query: str, limit: int = 5) -> list[dict]:
    """
    搜索 ChatHistoryKB 中的历史对话。
    参考 WeKnora 的 MessageSearchParams。
    """
    from .models import Chunk, KnowledgeBase
    from .search import hybrid_search

    config = get_chat_history_config(tenant)
    kb_id = config.get("knowledge_base_id", "")

    if not kb_id:
        return []

    # 使用现有的 hybrid_search 搜索
    try:
        results = hybrid_search(tenant.id, [kb_id], query, limit)
        return results
    except Exception as e:
        logger.warning(f"[ChatHistoryKB] Search failed: {e}")
        return []
