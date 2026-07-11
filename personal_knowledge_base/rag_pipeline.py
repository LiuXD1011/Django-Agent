"""
RAG 管道模块

参考同类知识库系统的 KnowledgeQA 管道设计：
1. 加载历史
2. 查询理解
3. 并行搜索（向量 + 关键词）
4. Rerank
5. 合并过滤
6. 流式 LLM 生成

设计原则：
- 每个阶段独立，可单独优化
- 支持流式输出
- 支持并行执行
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Generator

from django.db import connection
from django.db.models import Q

logger = logging.getLogger(__name__)


@dataclass
class RAGContext:
    """RAG 管道上下文"""
    query: str
    search_query: str = ""
    intent: str = "kb_search"
    refs: list = field(default_factory=list)
    memory_context: str = ""
    chat_history_context: str = ""
    kb_names: str = ""
    history: list = field(default_factory=list)
    system_prompt: str = ""
    user_prompt: str = ""


@dataclass
class RAGResult:
    """RAG 管道结果"""
    answer: str = ""
    refs: list = field(default_factory=list)
    intent: str = ""
    search_query: str = ""
    duration_ms: int = 0


def run_rag_pipeline(
    tenant,
    query: str,
    kb_ids: list[str],
    session=None,
    user=None,
    enable_memory: bool = True,
    model_id: str = "",
) -> RAGContext:
    """
    执行 RAG 管道（同步版本，用于构建上下文）。

    参考同类知识库系统的 KnowledgeQA 管道：
    1. 查询理解（意图识别 + 查询改写）
    2. 记忆检索
    3. 知识库检索（并行 FTS + 向量）
    4. 构建上下文
    """
    from .query_understand import INTENT_KB_SEARCH, get_intent_system_prompt, needs_retrieval, understand_query
    from .search import hybrid_search
    from .memory import is_memory_available, retrieve_memory
    from .chat_history_kb import format_chat_history_context, is_chat_history_enabled
    from .models import KnowledgeBase

    ctx = RAGContext(query=query)

    # ── Stage 1: 查询理解 + 记忆检索（并行）────────────────────────
    # 参考同类知识库系统：两个 LLM 调用互不依赖，可并行执行
    fast_intent = _quick_intent_detect(query)
    is_chitchat = fast_intent == "chitchat"

    if connection.vendor == "sqlite":
        understanding = _safe_understand_query(tenant, query) if fast_intent is None else None
        if understanding:
            ctx.intent = understanding.get("intent", INTENT_KB_SEARCH)
            ctx.search_query = understanding.get("rewrite_query") or query
        else:
            ctx.intent = fast_intent or INTENT_KB_SEARCH
            ctx.search_query = query
        if not is_chitchat and enable_memory and user and is_memory_available():
            ctx.memory_context = _safe_retrieve_memory(tenant, str(user.id), query) or ""
        if not is_chitchat and user and is_chat_history_enabled(tenant):
            history_results = _safe_search_chat_history(tenant, query)
            if history_results:
                ctx.chat_history_context = format_chat_history_context(history_results, tenant=tenant)
    else:
        with ThreadPoolExecutor(max_workers=3) as pool:
            # 查询理解
            future_understanding = None
            if fast_intent is None:
                future_understanding = pool.submit(_safe_understand_query, tenant, query)

            # 记忆检索
            future_memory = None
            if not is_chitchat and enable_memory and user and is_memory_available():
                future_memory = pool.submit(_safe_retrieve_memory, tenant, str(user.id), query)

            future_chat_history = None
            if not is_chitchat and user and is_chat_history_enabled(tenant):
                future_chat_history = pool.submit(_safe_search_chat_history, tenant, query)

            # 等待结果
            if future_understanding:
                understanding = future_understanding.result()
                if understanding:
                    ctx.intent = understanding.get("intent", INTENT_KB_SEARCH)
                    ctx.search_query = understanding.get("rewrite_query") or query
            else:
                ctx.intent = fast_intent or INTENT_KB_SEARCH
                ctx.search_query = query

            if future_memory:
                memory_result = future_memory.result()
                if memory_result:
                    ctx.memory_context = memory_result

            if future_chat_history:
                history_results = future_chat_history.result()
                if history_results:
                    ctx.chat_history_context = format_chat_history_context(history_results, tenant=tenant)

    # ── Stage 2: 知识库检索 ─────────────────────────────────────────
    # 参考同类知识库系统：CHUNK_SEARCH_PARALLEL（向量 + 关键词并行）
    if needs_retrieval(ctx.intent) and kb_ids:
        ctx.refs = hybrid_search(tenant.id, kb_ids, ctx.search_query, 5)

    # ── Stage 3: 构建上下文 ─────────────────────────────────────────
    ctx.kb_names = _build_kb_names(kb_ids, tenant)
    ctx.system_prompt = get_intent_system_prompt(ctx.intent) or SYSTEM_PROMPT_DEFAULT
    ctx.user_prompt = _build_user_prompt(ctx)

    return ctx


def run_rag_pipeline_stream(
    tenant,
    query: str,
    kb_ids: list[str],
    session=None,
    user=None,
    enable_memory: bool = True,
    model_id: str = "",
) -> Generator[str, None, None]:
    """
    执行 RAG 管道（流式版本）。

    参考同类知识库系统的 CHAT_COMPLETION_STREAM：
    - 构建上下文后，逐 token 流式输出
    """
    from .model_providers import chat_completion_stream

    # 构建上下文
    ctx = run_rag_pipeline(tenant, query, kb_ids, session, user, enable_memory, model_id)

    # 流式 LLM 生成
    llm_messages = [
        {"role": "system", "content": ctx.system_prompt},
        {"role": "user", "content": ctx.user_prompt},
    ]

    try:
        for token in chat_completion_stream(tenant, llm_messages, model_id):
            yield token
    except Exception as e:
        logger.warning(f"RAG stream failed: {e}")
        # 回退到非流式
        from .model_providers import chat_completion
        try:
            answer = chat_completion(tenant, llm_messages, model_id)
            yield answer
        except Exception:
            yield "抱歉，生成回答时出现错误。"


# ── 辅助函数 ─────────────────────────────────────────────────────

SYSTEM_PROMPT_DEFAULT = """你是一个知识库问答助手。请根据提供的知识库上下文回答用户问题。
- 优先使用上下文中的信息回答
- 引用具体来源时注明文档标题
- 如果上下文中没有相关信息，如实说明"""


def _quick_intent_detect(query: str) -> str | None:
    """快速意图检测：对简单查询用正则规则判断，跳过 LLM 调用。"""
    q = query.strip()
    if len(q) < 10 and any(w in q for w in ["你好", "hello", "hi", "嗨", "您好", "hey"]):
        return "chitchat"
    if len(q) < 20 and ("?" in q or "？" in q or q.startswith(("什么", "怎么", "如何", "为什么", "哪", "谁", "几"))):
        return "kb_search"
    if len(q) < 8:
        return "kb_search"
    return None


def _safe_understand_query(tenant, query: str) -> dict | None:
    """线程安全的查询理解包装"""
    try:
        from .query_understand import understand_query
        return understand_query(tenant, query)
    except Exception:
        logger.exception("Query understanding failed")
        return None


def _safe_retrieve_memory(tenant, user_id: str, query: str) -> str:
    """线程安全的记忆检索包装"""
    try:
        from .chat_history_kb import sanitize_internal_kb_mentions
        from .memory import retrieve_memory
        mem_ctx = retrieve_memory(tenant, user_id, query)
        if mem_ctx.related_episodes:
            return "\n\n<relevant_memory>\n" + "\n".join(
                f"- {sanitize_internal_kb_mentions(tenant, ep.summary)}" for ep in mem_ctx.related_episodes
            ) + "\n</relevant_memory>"
    except Exception:
        logger.exception("Memory retrieval failed")
    return ""


def _safe_search_chat_history(tenant, query: str) -> list[dict]:
    """线程安全的 ChatHistoryKB 检索包装。"""
    try:
        from .chat_history_kb import search_chat_history
        return search_chat_history(tenant, query, limit=5)
    except Exception:
        logger.exception("ChatHistoryKB retrieval failed")
    return []


def _build_kb_names(kb_ids: list[str], tenant) -> str:
    """构建知识库元数据"""
    from .models import KnowledgeBase
    if not kb_ids:
        return ""
    kb_list = KnowledgeBase.objects.filter(
        id__in=kb_ids, tenant=tenant, deleted_at__isnull=True
    ).values("name", "description")
    kb_lines = []
    for kb in kb_list:
        desc = kb.get("description", "").strip()
        kb_lines.append(f"- {kb['name']}" + (f"：{desc}" if desc else ""))
    if kb_lines:
        return "当前知识库：\n" + "\n".join(kb_lines)
    return ""


def _build_user_prompt(ctx: RAGContext) -> str:
    """构建用户 prompt"""
    memory_context = _merge_context_parts(ctx.memory_context, ctx.chat_history_context)
    if ctx.refs:
        full_context = _build_context_with_memory(ctx.refs, memory_context, ctx.kb_names)
        return f"{full_context}\n\n<user_question>\n{ctx.query}\n</user_question>"
    elif memory_context:
        return f"{ctx.kb_names}\n\n{memory_context}\n\n<user_question>\n{ctx.query}\n</user_question>" if ctx.kb_names else f"{memory_context}\n\n<user_question>\n{ctx.query}\n</user_question>"
    else:
        return f"{ctx.kb_names}\n\n<user_question>\n{ctx.query}\n</user_question>" if ctx.kb_names else ctx.query


def _merge_context_parts(*parts: str) -> str:
    return "\n\n".join(part for part in parts if part)


def _build_context_with_memory(refs: list, memory_context: str, kb_names: str) -> str:
    """构建包含记忆的上下文"""
    from .views import _build_document_header

    parts = []
    if kb_names:
        parts.append(kb_names)

    doc_header = _build_document_header(refs)
    if doc_header:
        parts.append(doc_header)

    if memory_context:
        parts.append(memory_context)

    # 构建结构化上下文
    context_parts = []
    for i, ref in enumerate(refs[:5], 1):
        title = ref.get("knowledge_title", "Unknown")
        content = ref.get("content", "")[:500]
        context_parts.append(f"[{i}] {title}\n{content}")

    if context_parts:
        parts.append("<context>\n" + "\n\n".join(context_parts) + "\n</context>")

    return "\n\n".join(parts)
