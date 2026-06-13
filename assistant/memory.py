import hashlib
import json
import re

from django.conf import settings
from django.db import connection
from django.db.models import Q
from django.utils import timezone
from openai import OpenAI

from .models import ChatMessage, Conversation, ConversationMemory


def compact_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def short_hash(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def quote_fts_query(query):
    escaped = compact_text(query).replace('"', '""')
    return f'"{escaped}"'


def ensure_memory_fts():
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS assistant_conversation_memory_fts
            USING fts5(title, kind, scope, content, tokenize='trigram')
            """
        )


def delete_memory_index(memory_id):
    ensure_memory_fts()
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM assistant_conversation_memory_fts WHERE rowid = %s", [memory_id])


def upsert_memory_index(memory):
    ensure_memory_fts()
    delete_memory_index(memory.id)
    if memory.status != ConversationMemory.STATUS_ACTIVE:
        return
    title = memory.kb.name if memory.kb_id else "用户长期记忆"
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO assistant_conversation_memory_fts(rowid, title, kind, scope, content)
            VALUES (%s, %s, %s, %s, %s)
            """,
            [memory.id, title, memory.kind, memory.scope, memory.content],
        )


def _active_memory_queryset(user, kb=None):
    qs = ConversationMemory.objects.filter(user=user, status=ConversationMemory.STATUS_ACTIVE)
    if kb:
        return qs.filter(Q(kb__isnull=True) | Q(kb=kb))
    return qs.filter(kb__isnull=True)


def search_memories(user, query, kb=None, limit=6):
    ensure_memory_fts()
    limit = max(1, int(limit))
    qs = _active_memory_queryset(user, kb=kb).select_related("kb")
    if len(compact_text(query)) < 3:
        return list(qs.order_by("-updated_at")[:limit])

    kb_clause = "m.kb_id IS NULL"
    params = [quote_fts_query(query), user.id]
    if kb:
        kb_clause = "(m.kb_id IS NULL OR m.kb_id = %s)"
        params.append(kb.id)
    params.append(limit)

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT m.id
                FROM assistant_conversation_memory_fts
                JOIN assistant_conversationmemory m
                  ON m.id = assistant_conversation_memory_fts.rowid
                WHERE assistant_conversation_memory_fts MATCH %s
                  AND m.user_id = %s
                  AND m.status = 'active'
                  AND {kb_clause}
                ORDER BY bm25(assistant_conversation_memory_fts)
                LIMIT %s
                """,
                params,
            )
            ids = [row[0] for row in cursor.fetchall()]
    except Exception:
        ids = list(qs.filter(content__icontains=compact_text(query)).values_list("id", flat=True)[:limit])

    if not ids:
        return list(qs.order_by("-updated_at")[:limit])
    by_id = {item.id: item for item in qs.filter(id__in=ids)}
    return [by_id[item_id] for item_id in ids if item_id in by_id]


def format_memory_context(memories):
    lines = []
    for memory in memories:
        scope = f"知识库:{memory.kb.name}" if memory.kb_id else "用户"
        lines.append(f"[M{memory.id} · {scope} · {memory.kind}] {memory.content}")
    return "\n".join(lines)


def format_recent_messages(messages):
    labels = {ChatMessage.ROLE_USER: "用户", ChatMessage.ROLE_ASSISTANT: "助手"}
    lines = []
    for message in messages:
        text = compact_text(message.content)
        if not text:
            continue
        lines.append(f"{labels.get(message.role, message.role)}：{text[:1200]}")
    return "\n".join(lines)


class ConversationContextBuilder:
    def __init__(self, user, conversation, kb=None, query=""):
        self.user = user
        self.conversation = conversation
        self.kb = kb
        self.query = query

    def recent_messages(self, limit=12, exclude_message=None):
        qs = self.conversation.messages.order_by("-created_at")
        if exclude_message:
            qs = qs.exclude(id=exclude_message.id)
        return list(reversed(list(qs[:limit])))

    def build(self, exclude_message=None):
        recent = self.recent_messages(exclude_message=exclude_message)
        memories = search_memories(self.user, self.query, kb=self.kb, limit=6)
        return {
            "conversation_id": self.conversation.id,
            "checkpoint": self.conversation.checkpoint,
            "memories": memories,
            "memory_context": format_memory_context(memories),
            "recent_messages": recent,
            "recent_context": format_recent_messages(recent),
        }


def _extract_json_object(text):
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    candidates = [raw]
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def fallback_title(text):
    title = compact_text(text)[:24]
    return title or "新对话"


def ensure_conversation_title(conversation, seed_text, candidate=""):
    if conversation.title and conversation.title != "新对话":
        return False
    title = compact_text(candidate)[:40] or fallback_title(seed_text)
    conversation.title = title
    conversation.save(update_fields=["title", "updated_at"])
    return True


class MemoryManager:
    def __init__(self, user, conversation, kb=None):
        self.user = user
        self.conversation = conversation
        self.kb = kb

    def _prompt(self, user_message, assistant_message, references, context):
        kb_line = f"当前知识库：{self.kb.name}" if self.kb else "当前未选择知识库"
        return f"""
你是轻量个人知识库的对话记忆整理器。请只返回 JSON，不要输出 Markdown。
JSON 格式：
{{
  "title": "不超过20字的对话标题",
  "checkpoint": "当前对话的结构化短摘要，保留用户目标、已完成事项、下一步和关键约束",
  "memories": [
    {{"scope": "user", "kind": "preference", "content": "可跨会话复用的用户偏好或事实"}},
    {{"scope": "kb", "kind": "fact", "content": "只适用于当前知识库的持久信息"}}
  ]
}}

规则：
- 只记录未来会话可能继续用到的信息，不要记录临时寒暄。
- scope 只能是 user 或 kb；未选择知识库时不要输出 scope=kb。
- kind 只能是 fact、preference、decision、task。
- memories 最多 5 条，内容必须具体、短句、中文。
- 如果没有值得长期保存的信息，memories 返回空数组。

{kb_line}

已有会话 checkpoint：
{context.get("checkpoint") or "无"}

已召回长期记忆：
{context.get("memory_context") or "无"}

最近对话：
{context.get("recent_context") or "无"}

本轮用户问题：
{user_message.content}

本轮助手回答：
{assistant_message.content}

本轮引用：
{json.dumps(references or [], ensure_ascii=False)[:3000]}
""".strip()

    def _call_llm(self, user_message, assistant_message, references, context):
        client = OpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL, timeout=8)
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是对话记忆整理器，只返回合法 JSON。"},
                {"role": "user", "content": self._prompt(user_message, assistant_message, references, context)},
            ],
            temperature=0,
        )
        return _extract_json_object(response.choices[0].message.content or "")

    def _upsert_memories(self, memories, source_message):
        saved = []
        for item in memories or []:
            if not isinstance(item, dict):
                continue
            content = compact_text(str(item.get("content") or ""))
            if len(content) < 6:
                continue
            scope = item.get("scope") if item.get("scope") in {ConversationMemory.SCOPE_USER, ConversationMemory.SCOPE_KB} else ConversationMemory.SCOPE_USER
            if scope == ConversationMemory.SCOPE_KB and not self.kb:
                continue
            kind = item.get("kind") if item.get("kind") in {"fact", "preference", "decision", "task"} else ConversationMemory.KIND_FACT
            kb = self.kb if scope == ConversationMemory.SCOPE_KB else None
            digest = short_hash(f"{self.user.id}:{kb.id if kb else ''}:{scope}:{kind}:{content}")
            memory = ConversationMemory.objects.filter(user=self.user, kb=kb, content_hash=digest).first()
            defaults = {
                "scope": scope,
                "kind": kind,
                "content": content,
                "status": ConversationMemory.STATUS_ACTIVE,
                "source_conversation": self.conversation,
                "source_message": source_message,
                "metadata": {"auto": True},
            }
            if memory:
                for field, value in defaults.items():
                    setattr(memory, field, value)
                memory.save(update_fields=[*defaults.keys(), "updated_at"])
            else:
                memory = ConversationMemory.objects.create(
                    user=self.user,
                    kb=kb,
                    content_hash=digest,
                    **defaults,
                )
            saved.append(memory.id)
        return saved

    def run(self, user_message, assistant_message, references, context):
        if not getattr(settings, "ASSISTANT_MEMORY_AUTO_ENABLED", True):
            title_changed = ensure_conversation_title(self.conversation, user_message.content)
            return {
                "status": "disabled",
                "title": self.conversation.title,
                "title_changed": title_changed,
                "memory_ids": [],
            }
        if not settings.LLM_API_KEY:
            title_changed = ensure_conversation_title(self.conversation, user_message.content)
            return {
                "status": "skipped",
                "reason": "missing_llm_api_key",
                "title": self.conversation.title,
                "title_changed": title_changed,
                "memory_ids": [],
            }

        try:
            payload = self._call_llm(user_message, assistant_message, references, context)
        except Exception as exc:
            title_changed = ensure_conversation_title(self.conversation, user_message.content)
            return {
                "status": "failed",
                "error": str(exc),
                "title": self.conversation.title,
                "title_changed": title_changed,
                "memory_ids": [],
            }

        title_changed = ensure_conversation_title(self.conversation, user_message.content, payload.get("title", ""))
        checkpoint = compact_text(str(payload.get("checkpoint") or ""))
        if checkpoint:
            self.conversation.checkpoint = checkpoint[:6000]
            self.conversation.last_checkpoint_message = assistant_message
            self.conversation.save(update_fields=["checkpoint", "last_checkpoint_message", "updated_at"])
        memory_ids = self._upsert_memories(payload.get("memories") or [], assistant_message)
        return {
            "status": "success",
            "title": self.conversation.title,
            "title_changed": title_changed,
            "checkpoint_updated": bool(checkpoint),
            "memory_ids": memory_ids,
            "updated_at": timezone.now().isoformat(),
        }
