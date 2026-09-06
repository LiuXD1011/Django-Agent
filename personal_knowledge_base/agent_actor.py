import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from django.conf import settings
from django.utils import timezone

from .models import AgentActor, Message, Session, Tenant
from .db_retry import retry_on_db_lock
from .stream_manager import stream_manager

logger = logging.getLogger(__name__)


SUBAGENT_CONFIGS = {
    "doc_retriever": {
        "name": "文档检索子 Agent",
        "system_prompt": (
            "你是文档检索子 Agent，只基于原始文档 chunk 查找证据，输出简洁证据摘要。"
            "输出格式：每条证据独立一行，注明来源文档标题并引用关键原文短语。"
            "已获得足够证据（一般 3 条以内）就立即停止检索，不要重复搜索；"
            "确实找不到相关内容时明确说明'未检索到相关证据'，不要编造。"
        ),
        "allowed_tools": ["knowledge_search", "grep_chunks", "list_knowledge_docs", "get_document_info"],
        "max_rounds": 6,
    },
    "wiki_researcher": {
        "name": "Wiki 研究子 Agent",
        "system_prompt": (
            "你是 Wiki 研究子 Agent，优先读取 Wiki 页面和页面来源，输出结构化知识摘要。"
            "输出格式：按主题分点的结构化摘要，每个要点注明来源 Wiki 页面标题；"
            "页面之间内容冲突时并列列出，不要自行取舍。"
            "已有足够页面覆盖主题就停止，不要逐页通读。"
        ),
        "allowed_tools": ["wiki_search", "wiki_read_page", "wiki_list_pages", "wiki_read_source_doc"],
        "max_rounds": 6,
    },
    "graph_reasoner": {
        "name": "图谱推理子 Agent",
        "system_prompt": (
            "你是知识图谱推理子 Agent，围绕实体和关系进行多跳查询，并说明关系链。"
            "输出格式：先给结论，再用 'A -[关系]-> B' 的形式列出支撑该结论的关系链；"
            "图谱中不存在的路径不要推测补全。"
            "关系链已能支撑结论即停止查询。"
        ),
        "allowed_tools": ["query_knowledge_graph", "wiki_search", "wiki_read_page", "knowledge_search"],
        "max_rounds": 6,
    },
    "answer_writer": {
        "name": "答案综合子 Agent",
        "system_prompt": (
            "你是答案综合子 Agent，不调用检索工具，只把已有子 Agent 结果整理为最终回答草稿。"
            "综合时保留每条结论的来源标注（文档标题或 Wiki 页面标题）；"
            "多个来源冲突时明确指出冲突及各方说法，不要默默取舍；"
            "不要添加输入中不存在的信息。"
        ),
        "allowed_tools": ["thinking"],
        "max_rounds": 4,
    },
}

TERMINAL_STATUSES = {"idle", "cancelled"}
_ID_RESERVATION_LOCK = threading.Lock()
_ID_RESERVATIONS: dict[tuple[str, str], int] = {}


@dataclass
class ActorResult:
    actor_id: str
    status: str
    output: str = ""
    error: str = ""
    duration_ms: int = 0
    metadata: dict | None = None
    # 子 Agent 检索到的结构化引用，供主 Agent 引擎回填到最终回答
    references: list | None = None

    def to_output_text(self) -> str:
        if self.error:
            return f"[Actor {self.actor_id} {self.status}]\nError: {self.error}"
        return f"[Actor {self.actor_id} {self.status}]\n{self.output}"


def actor_to_trace(actor: AgentActor) -> dict:
    return {
        "id": actor.id,
        "actor_id": actor.actor_id,
        "agent_type": actor.agent_type,
        "name": SUBAGENT_CONFIGS.get(actor.agent_type, {}).get("name", actor.agent_type),
        "mode": actor.mode,
        "status": actor.status,
        "last_outcome": actor.last_outcome,
        "background": actor.background,
        "input_prompt": actor.input_prompt,
        "output": actor.output,
        "error": actor.error,
        "parent_actor_id": actor.parent_actor_id,
        "parent_message_id": actor.parent_message_id,
        "started_at": actor.started_at.isoformat() if actor.started_at else None,
        "completed_at": actor.completed_at.isoformat() if actor.completed_at else None,
        "metadata": actor.metadata or {},
        "events": [],
    }


def emit_actor_event(parent_message_id: str, event_type: str, actor: AgentActor, extra: dict | None = None):
    if not parent_message_id:
        return None
    event_data = dict(extra or {})
    if event_type in {"actor_tool_call", "actor_tool_result"} and event_data.get("name"):
        event_data["tool_name"] = event_data["name"]
    payload = {
        **event_data,
        "response_type": event_type,
        "actor_id": actor.actor_id,
        "agent_type": actor.agent_type,
        "name": SUBAGENT_CONFIGS.get(actor.agent_type, {}).get("name", actor.agent_type),
        "status": actor.status,
        "last_outcome": actor.last_outcome,
        "background": actor.background,
        "parent_message_id": actor.parent_message_id,
        "metadata": actor.metadata or {},
    }
    _mirror_actor_trajectory(event_type, actor)
    return stream_manager.append_event(parent_message_id, event_type, payload)


def _mirror_actor_trajectory(event_type: str, actor: AgentActor):
    """把子代理生命周期镜像进会话事件日志（spawned/completed/failed；失败静默）。

    载荷包含调试子代理所需的最小事实集：委派指令、产出摘要、耗时、错误。
    """
    trajectory_event = {
        "actor_started": "spawned",
        "actor_completed": "completed",
        "actor_failed": "failed",
    }.get(event_type)
    if trajectory_event is None:
        return
    try:
        from . import event_log
        from .models import Message as _Message, Session as _Session

        parent = _Message.objects.filter(id=actor.parent_message_id).only("request_id").first()
        if parent is None:
            return
        session = _Session.objects.filter(pk=actor.session_id).only("pk", "tenant_id").first()
        if session is None:
            return
        metadata = actor.metadata or {}
        payload = {
            "event": trajectory_event,
            "actor_id": actor.actor_id,
            "agent_type": actor.agent_type,
            "status": actor.status,
        }
        if trajectory_event == "spawned":
            payload["input_prompt"] = (actor.input_prompt or "")[:300]
        elif trajectory_event == "completed":
            payload["output_excerpt"] = (actor.output or "")[:500]
            duration = metadata.get("duration_ms")
            if duration is not None:
                payload["duration_ms"] = int(duration)
        elif trajectory_event == "failed":
            payload["error"] = (actor.error or "")[:200]
            duration = metadata.get("duration_ms")
            if duration is not None:
                payload["duration_ms"] = int(duration)
        event_log.append_event(session, parent.request_id, event_log.AGENT_ACTOR, payload)
    except Exception:
        pass


class ActorRegistry:
    @staticmethod
    def ensure_main_actor(session: Session) -> AgentActor:
        actor, _ = AgentActor.objects.get_or_create(
            session=session,
            actor_id="main",
            defaults={
                "agent_type": "main",
                "mode": "main",
                "status": "idle",
                "last_outcome": "success",
                "background": False,
                "tool_whitelist": ["actor"],
            },
        )
        return actor

    @staticmethod
    def allocate_actor_id(session: Session, agent_type: str) -> str:
        with _ID_RESERVATION_LOCK:
            prefix = f"{agent_type}-"
            existing = AgentActor.objects.filter(session=session, actor_id__startswith=prefix).values_list("actor_id", flat=True)
            max_index = 0
            for actor_id in existing:
                try:
                    max_index = max(max_index, int(str(actor_id).split("-")[-1]))
                except ValueError:
                    continue
            key = (str(session.id), agent_type)
            max_index = max(max_index, _ID_RESERVATIONS.get(key, 0))
            next_index = max_index + 1
            _ID_RESERVATIONS[key] = next_index
            return f"{agent_type}-{next_index}"

    @staticmethod
    def create_subagent(
        session: Session,
        parent_actor: AgentActor,
        agent_type: str,
        input_prompt: str,
        parent_message_id: str = "",
        background: bool = False,
        tool_whitelist: list[str] | None = None,
    ) -> AgentActor:
        if agent_type not in SUBAGENT_CONFIGS:
            raise ValueError(f"Unknown subagent_type: {agent_type}")
        actor_id = ActorRegistry.allocate_actor_id(session, agent_type)
        config = SUBAGENT_CONFIGS[agent_type]
        return AgentActor.objects.create(
            session=session,
            parent_actor_id=parent_actor.actor_id,
            actor_id=actor_id,
            agent_type=agent_type,
            mode="subagent",
            status="pending",
            background=background,
            tool_whitelist=tool_whitelist if tool_whitelist is not None else list(config["allowed_tools"]),
            input_prompt=input_prompt,
            parent_message_id=parent_message_id,
        )

    @staticmethod
    def get(session: Session, actor_id: str) -> AgentActor | None:
        return AgentActor.objects.filter(session=session, actor_id=actor_id).first()

    @staticmethod
    def mark_running(actor: AgentActor) -> AgentActor:
        actor.status = "running"
        actor.started_at = actor.started_at or timezone.now()
        actor.save(update_fields=["status", "started_at", "updated_at"])
        return actor

    @staticmethod
    def mark_completed(actor: AgentActor, output: str, duration_ms: int = 0, metadata: dict | None = None) -> AgentActor:
        actor.status = "idle"
        actor.last_outcome = "success"
        actor.output = output or ""
        actor.error = ""
        actor.completed_at = timezone.now()
        merged = dict(actor.metadata or {})
        if duration_ms:
            merged["duration_ms"] = duration_ms
        if metadata:
            merged.update(metadata)
        actor.metadata = merged
        actor.save(update_fields=["status", "last_outcome", "output", "error", "completed_at", "metadata", "updated_at"])
        return actor

    @staticmethod
    def mark_failed(actor: AgentActor, error: str, metadata: dict | None = None) -> AgentActor:
        actor.status = "idle"
        actor.last_outcome = "failure"
        actor.error = error or ""
        actor.completed_at = timezone.now()
        merged = dict(actor.metadata or {})
        if metadata:
            merged.update(metadata)
        actor.metadata = merged
        actor.save(update_fields=["status", "last_outcome", "error", "completed_at", "metadata", "updated_at"])
        return actor

    @staticmethod
    def cancel_actor(session: Session, actor_id: str) -> bool:
        actor = ActorRegistry.get(session, actor_id)
        if not actor:
            return False
        actor.status = "cancelled"
        actor.last_outcome = "cancelled"
        actor.completed_at = timezone.now()
        metadata = dict(actor.metadata or {})
        metadata["cancel_requested"] = True
        actor.metadata = metadata
        actor.save(update_fields=["status", "last_outcome", "completed_at", "metadata", "updated_at"])
        emit_actor_event(actor.parent_message_id, "actor_failed", actor, {"error": "cancelled"})
        return True

    @staticmethod
    def is_cancel_requested(actor: AgentActor) -> bool:
        fresh = AgentActor.objects.filter(id=actor.id).values("status", "metadata").first()
        if not fresh:
            return True
        return fresh["status"] == "cancelled" or bool((fresh["metadata"] or {}).get("cancel_requested"))

    @staticmethod
    def traces_for_message(message_id: str) -> list[dict]:
        if not message_id:
            return []
        actors = AgentActor.objects.filter(parent_message_id=message_id).order_by("created_at", "actor_id")
        return [actor_to_trace(actor) for actor in actors]


class ActorRunner:
    @staticmethod
    def _parent_actor(session: Session, actor_id: str | None = None) -> AgentActor:
        if actor_id:
            actor = ActorRegistry.get(session, actor_id)
            if actor:
                return actor
        return ActorRegistry.ensure_main_actor(session)

    @staticmethod
    def run_subagent(
        parent_actor: AgentActor,
        subagent_type: str,
        prompt: str,
        context: dict,
        timeout_ms: int = 120000,
    ) -> ActorResult:
        actor = ActorRegistry.create_subagent(
            session=parent_actor.session,
            parent_actor=parent_actor,
            agent_type=subagent_type,
            input_prompt=prompt,
            parent_message_id=context.get("parent_message_id", ""),
            background=False,
        )
        return ActorRunner._execute_actor(actor, context, timeout_ms=timeout_ms)

    @staticmethod
    def spawn_subagent(parent_actor: AgentActor, subagent_type: str, prompt: str, context: dict) -> AgentActor:
        actor = ActorRegistry.create_subagent(
            session=parent_actor.session,
            parent_actor=parent_actor,
            agent_type=subagent_type,
            input_prompt=prompt,
            parent_message_id=context.get("parent_message_id", ""),
            background=True,
        )

        def worker():
            # 后台线程不继承 contextvars：显式复制调用方上下文，
            # 让子代理的 LLM 用量/工具事件归属正确的 Langfuse trace 与会话轮次
            contextvars.copy_context().run(
                ActorRunner._execute_actor, actor, context, timeout_ms=int(context.get("actor_timeout_ms") or 120000)
            )

        if getattr(settings, "APP_TASKS_SYNC", False):
            contextvars.copy_context().run(
                ActorRunner._execute_actor, actor, context, timeout_ms=int(context.get("actor_timeout_ms") or 120000)
            )
        else:
            threading.Thread(target=worker, daemon=True).start()
        return actor

    @staticmethod
    def wait(session: Session, actor_id: str, timeout_ms: int = 120000) -> ActorResult:
        deadline = time.time() + max(timeout_ms, 0) / 1000
        actor = ActorRegistry.get(session, actor_id)
        while actor and actor.status not in TERMINAL_STATUSES and time.time() < deadline:
            time.sleep(0.05)
            actor = ActorRegistry.get(session, actor_id)
        if not actor:
            return ActorResult(actor_id=actor_id, status="missing", error=f"Unknown actor: {actor_id}")
        if actor.status not in TERMINAL_STATUSES:
            return ActorResult(actor_id=actor.actor_id, status=actor.status, error="wait timeout")
        return ActorResult(
            actor_id=actor.actor_id,
            status=actor.last_outcome or actor.status,
            output=actor.output,
            error=actor.error,
            duration_ms=int((actor.metadata or {}).get("duration_ms") or 0),
            metadata=actor.metadata,
        )

    @staticmethod
    def _execute_actor(actor: AgentActor, context: dict, timeout_ms: int = 120000) -> ActorResult:
        start = time.monotonic()
        ActorRegistry.mark_running(actor)
        emit_actor_event(actor.parent_message_id, "actor_started", actor, {"input_prompt": actor.input_prompt})

        try:
            if ActorRegistry.is_cancel_requested(actor):
                raise RuntimeError("cancelled")

            from .agent_engine import AgentEngine

            config = SUBAGENT_CONFIGS[actor.agent_type]
            tenant_id = context.get("tenant_id")
            tenant = context.get("tenant")
            if tenant is None:
                tenant = Tenant.objects.get(id=tenant_id)

            retry_on_db_lock(lambda: Message.objects.create(
                session=actor.session,
                request_id=f"actor-{actor.actor_id}",
                role="user",
                content=actor.input_prompt,
                is_completed=True,
                agent_id=actor.actor_id,
                visible_to_user=False,
            ))

            # 子代理轨迹归组键：复用父轮 request_id，事件带 actor_id 在 fold 里按 actor 分组
            parent_request_id = ""
            try:
                parent = Message.objects.filter(id=actor.parent_message_id).only("request_id").first()
                parent_request_id = (parent.request_id if parent else "") or ""
            except Exception:
                parent_request_id = ""

            def _trajectory_from_event(event_type: str, data: dict):
                """把子代理引擎事件镜像进会话轨迹（带 actor_id；失败静默）。"""
                if not parent_request_id:
                    return
                try:
                    from . import event_log
                    if event_type == "thinking":
                        event_log.append_event(actor.session, parent_request_id, event_log.AGENT_THINKING, {
                            "iteration": data.get("iteration"),
                            "content": data.get("content", ""),
                            "reasoning_content": data.get("reasoning_content", ""),
                            "duration_ms": data.get("duration_ms"),
                            "usage": data.get("usage") or {},
                            "model": data.get("model", ""),
                            "finish_reason": data.get("finish_reason", ""),
                            "actor_id": actor.actor_id,
                            "agent_type": actor.agent_type,
                        })
                    elif event_type == "tool_call":
                        event_log.append_event(actor.session, parent_request_id, event_log.TOOL_CALL, {
                            "iteration": data.get("iteration"),
                            "tool_call_id": data.get("tool_call_id", ""),
                            "name": data.get("name", ""),
                            "argument_keys": sorted((data.get("arguments") or {}).keys()),
                            "arguments": event_log.sanitize_tool_arguments(data.get("arguments")),
                            "actor_id": actor.actor_id,
                            "agent_type": actor.agent_type,
                        })
                    elif event_type == "tool_result":
                        event_log.append_event(actor.session, parent_request_id, event_log.TOOL_RESULT, {
                            "iteration": data.get("iteration"),
                            "tool_call_id": data.get("tool_call_id", ""),
                            "name": data.get("name", ""),
                            "output": data.get("output", ""),
                            "error": data.get("error", ""),
                            "duration_ms": data.get("duration_ms", 0),
                            "meta": data.get("meta") or {},
                            "actor_id": actor.actor_id,
                            "agent_type": actor.agent_type,
                        })
                except Exception:
                    pass

            def on_event(event_type, data):
                if event_type == "thinking":
                    emit_actor_event(actor.parent_message_id, "actor_update", actor, {"content": data.get("content", "")})
                elif event_type == "tool_call":
                    emit_actor_event(actor.parent_message_id, "actor_tool_call", actor, data)
                elif event_type == "tool_result":
                    emit_actor_event(actor.parent_message_id, "actor_tool_result", actor, data)
                _trajectory_from_event(event_type, data or {})

            engine = AgentEngine(
                tenant=tenant,
                session_id=actor.session_id,
                user_id=str(context.get("user_id") or ""),
                agent_config={
                    "agent_mode": f"subagent:{actor.agent_type}",
                    "system_prompt": config["system_prompt"],
                    "allowed_tools": list(actor.tool_whitelist or config["allowed_tools"]),
                    "max_rounds": config["max_rounds"],
                    "knowledge_base_ids": context.get("kb_ids") or [],
                    "model_id": context.get("model_id", ""),
                    "actor_id": actor.actor_id,
                    "parent_message_id": actor.parent_message_id,
                    "allow_actor_tool": False,
                    "cancel_check": lambda: ActorRegistry.is_cancel_requested(actor),
                },
            )
            result = engine.execute(actor.input_prompt, history=[], context_str="", on_event=on_event, request_id=parent_request_id)

            retry_on_db_lock(lambda: Message.objects.create(
                session=actor.session,
                request_id=f"actor-{actor.actor_id}",
                role="assistant",
                content=result.content,
                rendered_content=result.content,
                agent_steps=[s.to_dict() for s in result.steps],
                agent_duration_ms=result.duration_ms,
                is_completed=True,
                agent_id=actor.actor_id,
                visible_to_user=False,
            ))
            duration_ms = int((time.monotonic() - start) * 1000)
            ActorRegistry.mark_completed(actor, result.content, duration_ms=duration_ms)
            actor.refresh_from_db()
            emit_actor_event(actor.parent_message_id, "actor_completed", actor, {"output": actor.output})
            return ActorResult(
                actor.actor_id,
                "success",
                output=actor.output,
                duration_ms=duration_ms,
                references=getattr(result, "references", None),
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            if "cancelled" in str(exc).lower():
                ActorRegistry.cancel_actor(actor.session, actor.actor_id)
                return ActorResult(actor.actor_id, "cancelled", error="cancelled", duration_ms=duration_ms)
            logger.exception("Subagent actor failed: %s", actor.actor_id)
            ActorRegistry.mark_failed(actor, str(exc), metadata={"duration_ms": duration_ms})
            actor.refresh_from_db()
            emit_actor_event(actor.parent_message_id, "actor_failed", actor, {"error": actor.error})
            return ActorResult(actor.actor_id, "failure", error=actor.error, duration_ms=duration_ms)


def format_actor_status(actor: AgentActor | None) -> str:
    if not actor:
        return "Actor not found"
    payload = actor_to_trace(actor)
    return json.dumps(payload, ensure_ascii=False, indent=2)
