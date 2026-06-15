import json
import re
from dataclasses import dataclass, field

from django.conf import settings
from django.utils import timezone
from openai import OpenAI

from knowledge.models import KBDocument, KnowledgeBase
from knowledge import services as kb_services
from knowledge import wiki_services

from . import services
from .memory import ConversationContextBuilder, MemoryManager
from .models import AgentEvent, AgentRun


@dataclass
class AgentResult:
    status: str
    summary: str = ""
    context: str = ""
    references: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    error_message: str = ""

    def to_dict(self):
        return {
            "status": self.status,
            "summary": self.summary,
            "context": self.context,
            "references": self.references,
            "metadata": self.metadata,
            "error_message": self.error_message,
        }


def _compact_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _safe_json(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _safe_json(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_json(item) for item in value]
    return str(value)


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


def _bool_value(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "是", "使用"}
    return bool(value)


def _lookup_text(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _trace_summary(trace):
    trace = trace or {}
    return {
        "rewritten_queries": trace.get("rewritten_queries", []),
        "vector_candidate_count": len(trace.get("vector_candidates", [])),
        "fts_candidate_count": len(trace.get("fts_candidates", [])),
        "fusion_candidate_count": len(trace.get("fusion_candidates", [])),
        "final_hit_count": len(trace.get("final_hits", [])),
        "final_hits": trace.get("final_hits", [])[:8],
        "rerank": {
            "enabled": (trace.get("rerank") or {}).get("enabled"),
            "model": (trace.get("rerank") or {}).get("model"),
            "error": (trace.get("rerank") or {}).get("error", ""),
        }
        if trace.get("rerank") is not None
        else {},
    }


class RunRecorder:
    agent_name = "agent"

    def __init__(self, user, message, parent_run=None, kb=None, metadata=None):
        self.user = user
        self.message = message
        self.parent_run = parent_run
        self.kb = kb
        self.run = AgentRun.objects.create(
            user=user,
            parent_run=parent_run,
            agent_name=self.agent_name,
            input={
                "message": message,
                "kb_id": getattr(kb, "id", None),
                "kb_name": getattr(kb, "name", ""),
            },
            metadata=metadata or {},
        )

    def event(self, event_type, payload=None):
        AgentEvent.objects.create(run=self.run, event_type=event_type, payload=_safe_json(payload or {}))

    def finish(self, result=None, status=None, error_message=""):
        result = result or AgentResult(status=status or AgentRun.STATUS_SUCCESS)
        final_status = status or result.status
        self.run.status = final_status
        self.run.output = _safe_json(result.to_dict())
        self.run.error_message = error_message or result.error_message
        self.run.finished_at = timezone.now()
        self.run.save(update_fields=["status", "output", "error_message", "finished_at"])
        self.event("done" if final_status == AgentRun.STATUS_SUCCESS else "error", result.to_dict())
        return result


class DriveAgent(RunRecorder):
    agent_name = "drive"

    def run_agent(self):
        try:
            context = services.drive_context(self.user, self.message)
            fallback_answer = services.file_info_answer(self.user, self.message)
            file_content_context, file_content_metadata = services.temporary_file_content_context(self.user, self.message)
            result = AgentResult(
                status=AgentRun.STATUS_SUCCESS,
                summary="已读取文件信息。",
                context=context,
                metadata={
                    "fallback_answer": fallback_answer,
                    "file_content_context": file_content_context,
                    "file_content": file_content_metadata,
                },
            )
            return self.finish(result)
        except Exception as exc:
            return self.finish(
                AgentResult(
                    status=AgentRun.STATUS_FAILED,
                    summary="文件信息读取失败。",
                    error_message=str(exc),
                )
            )


class WikiAgent(RunRecorder):
    agent_name = "wiki"

    def __init__(self, user, message, parent_run=None, kb=None, chat_history=None, metadata=None):
        super().__init__(user, message, parent_run=parent_run, kb=kb, metadata=metadata)
        self.chat_history = chat_history

    def run_agent(self):
        try:
            search_result = wiki_services.search_wiki_pages_with_trace(
                self.kb,
                self.message,
                top_k=3,
                chat_history=self.chat_history,
            )
            hits = search_result["hits"]
            trace_summary = _trace_summary(search_result["trace"])
            references = wiki_services.refs_payload(hits)
            for ref in references:
                ref["agent_run_id"] = self.run.id
            result = AgentResult(
                status=AgentRun.STATUS_SUCCESS,
                summary=f"找到 {len(hits)} 个 Wiki 页面。",
                context=wiki_services.references_context(hits),
                references=references,
                metadata={"hit_count": len(hits), "trace_summary": trace_summary},
            )
            return self.finish(result)
        except Exception as exc:
            return self.finish(
                AgentResult(
                    status=AgentRun.STATUS_FAILED,
                    summary="Wiki 检索失败。",
                    error_message=str(exc),
                )
            )


class KnowledgeRAGAgent(RunRecorder):
    agent_name = "knowledge_rag"

    def __init__(self, user, message, parent_run=None, kb=None, chat_history=None, metadata=None):
        super().__init__(user, message, parent_run=parent_run, kb=kb, metadata=metadata)
        self.chat_history = chat_history

    def run_agent(self):
        try:
            search_result = kb_services.search_with_trace(self.kb, self.message, top_k=6, chat_history=self.chat_history)
            hits = search_result["hits"]
            trace_summary = _trace_summary(search_result["trace"])
            references = kb_services.refs_payload(hits)
            for ref in references:
                ref["agent_run_id"] = self.run.id
            result = AgentResult(
                status=AgentRun.STATUS_SUCCESS,
                summary=f"找到 {len(hits)} 个原文片段。",
                context=kb_services.references_context(hits),
                references=references,
                metadata={"hit_count": len(hits), "trace_summary": trace_summary},
            )
            return self.finish(result)
        except Exception as exc:
            return self.finish(
                AgentResult(
                    status=AgentRun.STATUS_FAILED,
                    summary="知识库 RAG 检索失败。",
                    error_message=str(exc),
                )
            )


class AnswerAgent(RunRecorder):
    agent_name = "answer"

    def __init__(self, user, message, parent_run=None, kb=None, agent_plan=None, results=None, context=None, metadata=None):
        super().__init__(user, message, parent_run=parent_run, kb=kb, metadata=metadata)
        self.agent_plan = agent_plan or {}
        self.results = results or {}
        self.context = context or {}
        self.answer = ""

    def _drive_result(self):
        return self.results.get("drive")

    def _wiki_context(self):
        result = self.results.get("wiki")
        return result.context if result and result.context else ""

    def _rag_context(self):
        result = self.results.get("knowledge_rag")
        return result.context if result and result.context else ""

    def _drive_context(self):
        result = self._drive_result()
        return result.context if result and result.context else ""

    def _file_content_context(self):
        result = self._drive_result()
        return (result.metadata or {}).get("file_content_context", "") if result else ""

    def references_text(self):
        sections = []
        if self._wiki_context():
            sections.append("Wiki references:\n" + self._wiki_context())
        if self._rag_context():
            sections.append("原文 chunk references:\n" + self._rag_context())
        return "\n\n".join(sections)

    def _fallback_answer(self):
        drive = self._drive_result()
        refs_text = self.references_text()
        file_content_text = self._file_content_context()
        if drive and not refs_text and not file_content_text:
            return drive.metadata.get("fallback_answer") or drive.context or "未读取到文件信息。"
        sections = []
        if drive and drive.context:
            sections.append(f"文件信息：\n{drive.context}")
        if file_content_text:
            sections.append(f"文件库临时解析内容：\n{file_content_text}")
        if refs_text:
            sections.append(f"知识库相关片段：\n{refs_text[:1800]}")
        return "\n\n".join(sections) or "未配置 LLM_API_KEY，AI 服务暂不可用。"

    def stream_tokens(self):
        refs_text = self.references_text()
        drive_text = self._drive_context()
        file_content_text = self._file_content_context()
        if not settings.LLM_API_KEY:
            self.answer = self._fallback_answer()
            yield self.answer
            return

        if drive_text or file_content_text or refs_text:
            prompt = services.assistant_prompt(
                self.message,
                drive_text,
                refs_text,
                file_content_context_text=file_content_text,
                checkpoint_text=self.context.get("checkpoint", ""),
                memory_context_text=self.context.get("memory_context", ""),
                recent_context_text=self.context.get("recent_context", ""),
            )
            system = (
                "你是统一 AI 助手。你会优先使用 Wiki references 理解结构化结论，"
                "再使用原文 chunk references 追溯细节，也可以使用文件信息和文件库临时解析内容。"
                "只基于给出的上下文做可追溯回答；上下文不足时说明不足。"
            )
        else:
            prompt = services.assistant_prompt(
                self.message,
                checkpoint_text=self.context.get("checkpoint", ""),
                memory_context_text=self.context.get("memory_context", ""),
                recent_context_text=self.context.get("recent_context", ""),
            )
            system = "你是一个专业、简洁的中文助手。"

        for token in services.llm_tokens(prompt, system=system):
            self.answer += token
            yield token

    def finish_answer(self):
        result = AgentResult(
            status=AgentRun.STATUS_SUCCESS,
            summary="已生成最终回答。",
            context=self.answer,
            metadata={"answer_length": len(self.answer), "agent_plan": self.agent_plan},
        )
        return self.finish(result)


class AssistantOrchestrator:
    def __init__(self, user, message, conversation, allow_drive=False, kb_id=""):
        self.user = user
        self.message = (message or "").strip()
        self.conversation = conversation
        self.allow_drive = bool(allow_drive)
        self.kb_id = (kb_id or "").strip()
        self.root_run = None
        self.kb = None
        self.agent_plan = {}
        self.child_run_ids = []
        self.results = {}
        self.references = []
        self.answer = ""
        self.context = {}
        self.memory_update = {}

    def event(self, event_type, payload=None):
        AgentEvent.objects.create(run=self.root_run, event_type=event_type, payload=_safe_json(payload or {}))

    def start_root_run(self):
        self.root_run = AgentRun.objects.create(
            user=self.user,
            agent_name="assistant_orchestrator",
            input={
                "message": self.message,
                "allow_drive": self.allow_drive,
                "kb_id": self.kb_id,
                "conversation_id": self.conversation.id,
            },
            metadata={"mode": "sync_lightweight"},
        )
        self.event(
            "start",
            {
                "message": self.message,
                "allow_drive": self.allow_drive,
                "kb_id": self.kb_id,
                "conversation_id": self.conversation.id,
            },
        )

    def finish_root_run(self, status=AgentRun.STATUS_SUCCESS, error_message=""):
        self.root_run.status = status
        self.root_run.output = _safe_json(
            {
                "answer": self.answer,
                "references": self.references,
                "agent_plan": self.agent_plan,
                "child_run_ids": self.child_run_ids,
                "memory_update": self.memory_update,
            }
        )
        metadata = dict(self.root_run.metadata or {})
        metadata.update(
            {
                "agent_plan": self.agent_plan,
                "child_run_ids": self.child_run_ids,
                "reference_count": len(self.references),
                "memory_update": self.memory_update,
                "conversation_id": self.conversation.id,
            }
        )
        self.root_run.metadata = metadata
        self.root_run.error_message = error_message
        self.root_run.finished_at = timezone.now()
        self.root_run.save(update_fields=["status", "output", "metadata", "error_message", "finished_at"])
        self.event("done" if status == AgentRun.STATUS_SUCCESS else "error", self.root_run.output)

    def resolve_kb(self):
        if not self.kb_id:
            return None
        if not self.kb_id.isdigit():
            return "选择的知识库不存在或不可用。"
        self.kb = KnowledgeBase.objects.filter(id=self.kb_id, user=self.user, status="active").first()
        if not self.kb:
            return "选择的知识库不存在或不可用。"
        return None

    def metadata_base(self):
        return {
            "use_drive": self.allow_drive,
            "kb_id": self.kb.id if self.kb else None,
            "kb_name": self.kb.name if self.kb else "",
            "conversation_id": self.conversation.id,
            "run_id": self.root_run.id if self.root_run else None,
        }

    def fallback_plan(self, reason):
        return {
            "use_drive": self.allow_drive,
            "use_wiki": bool(self.kb),
            "use_rag": bool(self.kb),
            "reason": reason,
            "planner": "fallback",
            "raw_plan": {},
            "suppressed_capabilities": [],
        }

    def llm_plan(self):
        if not settings.LLM_API_KEY:
            return self.fallback_plan("未配置 LLM_API_KEY，使用确定性 fallback。")
        if not self.allow_drive and not self.kb:
            return {
                "use_drive": False,
                "use_wiki": False,
                "use_rag": False,
                "reason": "没有可用外部能力，走普通聊天。",
                "planner": "none",
                "raw_plan": {},
                "suppressed_capabilities": [],
            }
        try:
            client = OpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)
            response = client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是轻量个人知识库的多 agent planner。"
                            "只能返回 JSON，格式为："
                            "{\"use_drive\":false,\"use_wiki\":false,\"use_rag\":false,\"reason\":\"...\"}。"
                            "use_drive 表示是否需要文件容量、文件数量、完整文件列表、最近文件、类型统计或文件名搜索。"
                            "use_wiki 表示是否需要结构化 Wiki 页面。"
                            "use_rag 表示是否需要原文 chunk 检索。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"用户问题：{self.message}\n"
                            f"使用文件库：{self.allow_drive}\n"
                            f"是否选择知识库：{bool(self.kb)}\n"
                            "请决定本轮实际调用哪些 agent。"
                        ),
                    },
                ],
                temperature=0,
            )
            raw_content = response.choices[0].message.content or ""
            raw_plan = _extract_json_object(raw_content)
            if not raw_plan:
                return self.fallback_plan("planner JSON 解析失败，使用确定性 fallback。")
        except Exception as exc:
            return self.fallback_plan(f"planner 调用失败：{exc}")

        requested = {
            "use_drive": _bool_value(raw_plan.get("use_drive")),
            "use_wiki": _bool_value(raw_plan.get("use_wiki")),
            "use_rag": _bool_value(raw_plan.get("use_rag")),
        }
        suppressed = []
        plan = dict(requested)
        if plan["use_drive"] and not self.allow_drive:
            plan["use_drive"] = False
            suppressed.append("drive")
        if (plan["use_wiki"] or plan["use_rag"]) and not self.kb:
            if plan["use_wiki"]:
                suppressed.append("wiki")
            if plan["use_rag"]:
                suppressed.append("knowledge_rag")
            plan["use_wiki"] = False
            plan["use_rag"] = False
        plan.update(
            {
                "reason": _compact_text(str(raw_plan.get("reason") or "")) or "planner 未说明原因。",
                "planner": "llm",
                "raw_plan": _safe_json(raw_plan),
                "suppressed_capabilities": suppressed,
            }
        )
        return plan

    def run_planner(self):
        self.agent_plan = self.llm_plan()
        self.apply_deterministic_overrides()
        metadata = dict(self.root_run.metadata or {})
        metadata["agent_plan"] = self.agent_plan
        self.root_run.metadata = metadata
        self.root_run.save(update_fields=["metadata"])
        self.event("planner", self.agent_plan)

    def matched_ready_document(self):
        if not self.kb:
            return None
        query = _lookup_text(self.message)
        if len(query) < 6:
            return None
        documents = KBDocument.objects.filter(
            kb=self.kb,
            status=KBDocument.STATUS_READY,
            chunk_count__gt=0,
        ).only("id", "title", "source")[:500]
        for document in documents:
            candidates = {
                _lookup_text(document.title),
                _lookup_text(document.source),
            }
            for candidate in candidates:
                if not candidate:
                    continue
                if query in candidate or candidate in query:
                    return document
        return None

    def apply_deterministic_overrides(self):
        plan = dict(self.agent_plan or {})
        overrides = list(plan.get("deterministic_overrides") or [])
        if self.allow_drive and not plan.get("use_drive"):
            matched_files, too_many = services.mentioned_files(self.user, self.message)
            if matched_files:
                plan["use_drive"] = True
                overrides.append(
                    {
                        "capability": "drive",
                        "reason": "message_matches_file_library_file",
                        "file_ids": [item.id for item in matched_files],
                        "too_many": bool(too_many),
                    }
                )
        if self.kb and not plan.get("use_rag"):
            document = self.matched_ready_document()
            if document:
                plan["use_rag"] = True
                overrides.append(
                    {
                        "capability": "knowledge_rag",
                        "reason": "message_matches_ready_document",
                        "document_id": document.id,
                        "document_title": document.title,
                    }
                )
                reason = _compact_text(plan.get("reason", ""))
                suffix = "已选择知识库且问题命中已入库文档，强制启用 RAG。"
                plan["reason"] = f"{reason}；{suffix}" if reason else suffix
        if overrides:
            plan["deterministic_overrides"] = overrides
        self.agent_plan = plan

    def run_child_agents(self, chat_history):
        if self.agent_plan.get("use_drive"):
            agent = DriveAgent(
                self.user,
                self.message,
                parent_run=self.root_run,
                kb=self.kb,
                metadata={"conversation_id": self.conversation.id},
            )
            self.child_run_ids.append(agent.run.id)
            self.results["drive"] = agent.run_agent()
        if self.kb and self.agent_plan.get("use_wiki"):
            agent = WikiAgent(
                self.user,
                self.message,
                parent_run=self.root_run,
                kb=self.kb,
                chat_history=chat_history,
                metadata={"conversation_id": self.conversation.id},
            )
            self.child_run_ids.append(agent.run.id)
            self.results["wiki"] = agent.run_agent()
        if self.kb and self.agent_plan.get("use_rag"):
            agent = KnowledgeRAGAgent(
                self.user,
                self.message,
                parent_run=self.root_run,
                kb=self.kb,
                chat_history=chat_history,
                metadata={"conversation_id": self.conversation.id},
            )
            self.child_run_ids.append(agent.run.id)
            self.results["knowledge_rag"] = agent.run_agent()
        for name, result in self.results.items():
            self.event("agent_result", {"agent": name, "result": result.to_dict()})
            self.references.extend(result.references)
        if self.references:
            self.event("references", {"references": self.references})

    def update_conversation_defaults(self):
        self.conversation.default_use_drive = self.allow_drive
        self.conversation.default_kb = self.kb
        self.conversation.save(update_fields=["default_use_drive", "default_kb", "updated_at"])

    def stream(self):
        if not self.message:
            yield {"type": "token", "data": "请输入问题。"}
            yield {"type": "done"}
            return

        self.start_root_run()
        error = self.resolve_kb()
        metadata = self.metadata_base()
        if error:
            metadata["requested_kb_id"] = self.kb_id
            services.save_message(self.user, "user", self.message, self.conversation, metadata=metadata)
            services.save_message(self.user, "assistant", error, self.conversation, metadata=metadata)
            self.answer = error
            self.finish_root_run(status=AgentRun.STATUS_FAILED, error_message=error)
            yield {"type": "token", "data": error}
            yield {"type": "done"}
            return

        self.update_conversation_defaults()
        user_message = services.save_message(self.user, "user", self.message, self.conversation, metadata=metadata)
        self.context = ConversationContextBuilder(
            self.user,
            self.conversation,
            kb=self.kb,
            query=self.message,
        ).build(exclude_message=user_message)
        chat_history = self.context["recent_messages"]
        self.run_planner()
        self.run_child_agents(chat_history)

        answer_agent = AnswerAgent(
            self.user,
            self.message,
            parent_run=self.root_run,
            kb=self.kb,
            agent_plan=self.agent_plan,
            results=self.results,
            context=self.context,
            metadata={"conversation_id": self.conversation.id},
        )
        self.child_run_ids.append(answer_agent.run.id)
        for token in answer_agent.stream_tokens():
            self.answer += token
            yield {"type": "token", "data": token}
        answer_agent.finish_answer()
        self.event("agent_result", {"agent": "answer", "run_id": answer_agent.run.id, "answer_length": len(self.answer)})

        assistant_metadata = {
            **self.metadata_base(),
            "references": self.references,
            "agent_plan": self.agent_plan,
            "child_run_ids": self.child_run_ids,
        }
        assistant_message = services.save_message(
            self.user,
            "assistant",
            self.answer or "未获取到回复",
            self.conversation,
            metadata=assistant_metadata,
        )
        self.memory_update = MemoryManager(self.user, self.conversation, kb=self.kb).run(
            user_message,
            assistant_message,
            self.references,
            self.context,
        )
        assistant_metadata["memory_update"] = self.memory_update
        assistant_message.metadata = assistant_metadata
        assistant_message.save(update_fields=["metadata"])
        self.event("memory", self.memory_update)
        if self.memory_update.get("title_changed"):
            yield {
                "type": "conversation",
                "data": {
                    "id": self.conversation.id,
                    "title": self.conversation.title,
                    "url": f"/assistant/?conversation={self.conversation.id}",
                },
            }
        if self.references:
            yield {"type": "references", "data": {"references": self.references}}
        self.finish_root_run()
        yield {"type": "done"}
