"""会话事件溯源：轨迹事实的 append-only 存储、折叠与投影重建。

设计见 docs/trajectory-event-sourcing.md。三个职责：

1. append_event    —— 唯一写入入口：原子分配会话内 seq、冻结 data、失败静默降级；
2. fold_trajectory —— 服务端把事件折叠成前端直接渲染的轨迹台账；
3. rebuild_projection —— 从事件重建 Message 投影，校验"事件 > 投影"不变量。

事件不可变纪律：本模块不提供 update/delete；data 在写入时深拷贝为 JSON 原生类型，
调用方事后再改传入的 dict 不会影响已存事件。
"""

from __future__ import annotations

import copy
import logging
import time
from collections import defaultdict

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Message, Session, SessionEvent

logger = logging.getLogger(__name__)

# 事件类型词汇表（域/名称）。新增类型必须登记在此，写入层拒绝未登记类型，
# 防止调用点随手发明事件导致词汇表漂移。
SESSION_STARTED = "session/started"
TURN_USER_MESSAGE = "turn/user-message"
TURN_ASSISTANT_CREATED = "turn/assistant-created"
TURN_COMPLETED = "turn/completed"
TURN_ERROR = "turn/error"
RETRIEVAL_SEARCH = "retrieval/search"
RETRIEVAL_RESULT = "retrieval/result"
AGENT_ITERATION = "agent/iteration"
AGENT_THINKING = "agent/thinking"
AGENT_ACTOR = "agent/actor"
TOOL_CALL = "tool/call"
TOOL_RESULT = "tool/result"
LLM_CALL = "llm/call"
LLM_RETRY = "llm/retry"
CONTEXT_COMPACTED = "context/compacted"
REQUEST_HEADER = "request/header"

KNOWN_EVENT_TYPES = frozenset({
    SESSION_STARTED, TURN_USER_MESSAGE, TURN_ASSISTANT_CREATED, TURN_COMPLETED,
    TURN_ERROR, RETRIEVAL_SEARCH, RETRIEVAL_RESULT, AGENT_ITERATION, AGENT_THINKING,
    AGENT_ACTOR, TOOL_CALL, TOOL_RESULT, LLM_CALL, LLM_RETRY, CONTEXT_COMPACTED,
    REQUEST_HEADER,
})

OUTPUT_EXCERPT_LIMIT = 500
_SEQ_COLLISION_RETRIES = 4


def _freeze(value):
    """递归转为 JSON 原生类型的深拷贝；无法序列化的值降级为截断字符串。"""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return {str(k): _freeze(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_freeze(v) for v in value]
    return str(value)[:OUTPUT_EXCERPT_LIMIT]


def append_event(session, request_id: str, event_type: str, data: dict | None) -> SessionEvent | None:
    """追加一条事件；返回事件实例，失败返回 None（轨迹是增强，绝不打断主流程）。

    seq 以 Session.event_seq 计数器 + 唯一约束兜底：SQLite 下 F() 更新是原子的，
    回读到的值若撞唯一约束（多线程同会话并发）则重读计数器重试。
    """
    if event_type not in KNOWN_EVENT_TYPES:
        logger.warning("event_log: unknown event type rejected: %s", event_type)
        return None
    try:
        for _ in range(_SEQ_COLLISION_RETRIES):
            with transaction.atomic():
                counter = Session.objects.filter(pk=session.pk).values_list("event_seq", flat=True).first()
                if counter is None:
                    return None
                next_seq = int(counter) + 1
                updated = Session.objects.filter(pk=session.pk, event_seq=counter).update(event_seq=next_seq)
                if not updated:
                    continue
                event = SessionEvent.objects.create(
                    tenant_id=session.tenant_id,
                    session=session,
                    seq=next_seq,
                    request_id=str(request_id or ""),
                    type=event_type,
                    data=_freeze(data or {}),
                )
                return event
        logger.warning("event_log: seq collision retries exhausted for session %s", session.pk)
    except Exception:
        logger.warning("event_log: append %s failed for session %s", event_type, session.pk, exc_info=True)
    return None


def events_for_session(session_id: str, after_seq: int = 0, limit: int = 500) -> list[SessionEvent]:
    return list(
        SessionEvent.objects
        .filter(session_id=session_id, seq__gt=max(0, int(after_seq)))
        .order_by("seq")[: max(1, min(int(limit), 2000))]
    )


def _excerpt(text, limit: int = OUTPUT_EXCERPT_LIMIT) -> str:
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    return text[:limit]


def _ref_title(ref) -> dict:
    if not isinstance(ref, dict):
        return {}
    return {
        "chunk_id": _excerpt(ref.get("chunk_id") or ref.get("id"), 64),
        "title": _excerpt(ref.get("knowledge_title") or ref.get("title"), 200),
    }


def _iso(value) -> str | None:
    if value is None:
        return None
    try:
        return value.isoformat()
    except AttributeError:
        return str(value)


def fold_trajectory(events: list[SessionEvent]) -> dict:
    """把事件序列折叠成轨迹台账：轮次分组，步骤内聚思考/工具/模型用量。

    折叠是纯函数：同一事件序列永远产出同一台账（测试断言）。
    """
    turns: dict[str, dict] = {}
    order: list[str] = []

    def turn_for(event: SessionEvent) -> dict:
        key = event.request_id or f"__seq_{event.seq}"
        turn = turns.get(key)
        if turn is None:
            turn = {
                "request_id": event.request_id,
                "seq_range": [event.seq, event.seq],
                "started_at": _iso(event.created_at),
                "completed_at": None,
                "mode": "",
                "model_id": "",
                "stopped_reason": "",
                "duration_ms": None,
                "error": "",
                "user": None,
                "assistant": {"content": ""},
                "retrievals": [],
                "steps": {},
                "step_order": [],
                "actors": [],
                "request": None,
                "provider": "",
                "retries": [],
                "compactions": [],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "llm_calls": 0},
            }
            turns[key] = turn
            order.append(key)
        turn["seq_range"][1] = max(turn["seq_range"][1], event.seq)
        return turn

    def step_for(turn: dict, iteration) -> dict:
        key = str(iteration if iteration is not None else 0)
        step = turn["steps"].get(key)
        if step is None:
            step = {"iteration": iteration, "thought": "", "tools": [], "llm": {}, "started_at": None, "ended_at": None}
            turn["steps"][key] = step
            turn["step_order"].append(key)
        return step

    for event in events:
        data = event.data if isinstance(event.data, dict) else {}
        etype = event.type
        # 轮次外的孤立事件（如 session/started）不构成轮次
        needs_turn = etype != SESSION_STARTED
        turn = turn_for(event) if needs_turn else None
        if turn is not None:
            turn["seq_range"][1] = event.seq
        if etype == SESSION_STARTED:
            continue

        if etype == TURN_USER_MESSAGE:
            turn["user"] = {
                "content": data.get("content", ""),
                "images": len(data.get("images") or []),
                "attachments": data.get("attachments") or [],
                "mentioned_items": len(data.get("mentioned_items") or []),
                "channel": data.get("channel", ""),
            }
        elif etype == TURN_ASSISTANT_CREATED:
            turn["mode"] = data.get("mode", "")
            turn["model_id"] = data.get("model_id", "")
        elif etype == TURN_COMPLETED:
            turn["stopped_reason"] = data.get("stopped_reason", "completed")
            turn["duration_ms"] = data.get("duration_ms")
            turn["completed_at"] = _iso(event.created_at)
            content = data.get("content")
            if content:
                turn["assistant"]["content"] = content
        elif etype == TURN_ERROR:
            turn["stopped_reason"] = "error"
            turn["error"] = _excerpt(data.get("message", ""), 300)
            turn["completed_at"] = _iso(event.created_at)
        elif etype == RETRIEVAL_SEARCH:
            turn["retrievals"].append({
                "query": _excerpt(data.get("query", ""), 200),
                "kb_count": len(data.get("kb_ids") or []),
                "top_k": data.get("top_k"),
                "count": None,
                "intent": "",
                "degradations": [],
                "refs": [],
            })
        elif etype == RETRIEVAL_RESULT:
            target = turn["retrievals"][-1] if turn["retrievals"] else None
            if target is not None:
                target["count"] = data.get("count")
                target["intent"] = _excerpt(data.get("intent", ""), 50)
                target["degradations"] = data.get("degradations") or []
                target["refs"] = [_ref_title(r) for r in (data.get("refs") or [])[:8]]
        elif etype == AGENT_ITERATION:
            step = step_for(turn, data.get("iteration"))
            if step["started_at"] is None:
                step["started_at"] = _iso(event.created_at)
        elif etype == REQUEST_HEADER:
            turn["request"] = {
                "model": data.get("model", ""),
                "temperature": data.get("temperature"),
                "tools": data.get("allowed_tools") or [],
                "tool_schemas": {s.get("name"): s for s in (data.get("tool_schemas") or []) if s.get("name")},
                "max_iterations": data.get("max_iterations"),
                "history_messages": data.get("history_messages"),
                "agent_mode": data.get("agent_mode", ""),
            }
        elif etype == LLM_RETRY:
            turn["retries"].append({
                "attempt": data.get("attempt"),
                "reason": _excerpt(data.get("reason", ""), 200),
                "wait_seconds": data.get("wait_seconds"),
            })
        elif etype == CONTEXT_COMPACTED:
            turn["compactions"].append({
                "before_tokens": data.get("before_tokens"),
                "after_tokens": data.get("after_tokens"),
                "iteration": data.get("iteration"),
            })
        elif etype == AGENT_THINKING:
            step = step_for(turn, data.get("iteration"))
            step["thought"] = data.get("content", "")
            step["ended_at"] = _iso(event.created_at)
            if data.get("duration_ms") is not None:
                step["llm"]["duration_ms"] = data.get("duration_ms")
            if data.get("model"):
                step["llm"]["model"] = data.get("model")
                if not turn["model_id"]:
                    turn["model_id"] = data.get("model")
            # thinking 事件内嵌当次 LLM 用量（agent 路径的 usage 来源）
            usage = data.get("usage") or {}
            if usage.get("total_tokens") or usage.get("prompt_tokens") or usage.get("completion_tokens"):
                step["llm"]["usage"] = {
                    "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                    "completion_tokens": int(usage.get("completion_tokens") or 0),
                    "cached_tokens": int(usage.get("cached_tokens") or 0),
                    "reasoning_tokens": int(usage.get("reasoning_tokens") or 0),
                }
                turn["usage"]["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
                turn["usage"]["completion_tokens"] += int(usage.get("completion_tokens") or 0)
                turn["usage"]["llm_calls"] += 1
                turn["usage"]["cached_tokens"] = turn["usage"].get("cached_tokens", 0) + int(usage.get("cached_tokens") or 0)
                if data.get("provider") and not turn.get("provider"):
                    turn["provider"] = data.get("provider")
        elif etype == TOOL_CALL:
            tool = {
                "tool_call_id": data.get("tool_call_id", ""),
                "name": data.get("name", ""),
                "argument_keys": sorted((data.get("argument_keys") or [])),
                "output_excerpt": "",
                "error": "",
                "duration_ms": None,
                "started_at": _iso(event.created_at),
                "ended_at": None,
                "schema": (turn.get("request") or {}).get("tool_schemas", {}).get(data.get("name", "")),
            }
            step_for(turn, data.get("iteration"))["tools"].append(tool)
        elif etype == TOOL_RESULT:
            call_id = data.get("tool_call_id", "")
            step = step_for(turn, data.get("iteration"))
            target = next((t for t in reversed(step["tools"]) if t.get("tool_call_id") == call_id), None)
            if target is None:
                target = {"tool_call_id": call_id, "name": data.get("name", ""), "argument_keys": []}
                step["tools"].append(target)
            target["output_excerpt"] = _excerpt(data.get("output", ""))
            target["error"] = _excerpt(data.get("error", ""), 200)
            target["duration_ms"] = data.get("duration_ms")
            target["ended_at"] = _iso(event.created_at)
            if not target.get("schema"):
                target["schema"] = (turn.get("request") or {}).get("tool_schemas", {}).get(data.get("name", ""))
        elif etype == AGENT_ACTOR:
            turn["actors"].append({
                "actor_id": data.get("actor_id", ""),
                "agent_type": data.get("agent_type", ""),
                "event": data.get("event", ""),
                "status": data.get("status", ""),
            })
        elif etype == LLM_CALL:
            turn["usage"]["prompt_tokens"] += int(data.get("prompt_tokens") or 0)
            turn["usage"]["completion_tokens"] += int(data.get("completion_tokens") or 0)
            turn["usage"]["llm_calls"] += 1
            if not turn["model_id"] and data.get("model"):
                turn["model_id"] = data.get("model")

    result = []
    for key in order:
        turn = turns[key]
        steps = []
        for step_key in turn.pop("step_order"):
            step = turn["steps"][step_key]
            if step["thought"] or step["tools"] or step["llm"]:
                steps.append(step)
        turn.pop("steps")
        turn["steps"] = steps
        turn["usage"]["total_tokens"] = turn["usage"]["prompt_tokens"] + turn["usage"]["completion_tokens"]
        result.append(turn)
    return {"turns": result}


# ── 投影：从事件重建 Message ─────────────────────────────────────────

def _projection_fields_for_turn(turn_events: list[SessionEvent]) -> dict | None:
    """把一个 request 的事件组折叠成 Message 字段；无用户消息的组不投影。"""
    fields: dict | None = None
    assistant: dict = {}

    for event in turn_events:
        data = event.data if isinstance(event.data, dict) else {}
        if event.type == TURN_USER_MESSAGE:
            fields = {
                "session_id": event.session_id,
                "request_id": event.request_id or "",
                "role": "user",
                "content": data.get("content", ""),
                "rendered_content": "",
                "mentioned_items": data.get("mentioned_items") or [],
                "images": data.get("images") or [],
                "attachments": data.get("attachments") or [],
                "is_completed": True,
                "is_fallback": False,
                "channel": data.get("channel", "web"),
                "agent_steps": None,
                "agent_duration_ms": 0,
                "knowledge_references": [],
            }
        elif event.type == TURN_ASSISTANT_CREATED:
            assistant["channel"] = data.get("channel", "web")
        elif event.type == AGENT_THINKING:
            assistant["content"] = data.get("content", "")
        elif event.type == TOOL_RESULT:
            assistant.setdefault("steps", []).append({
                "type": "tool_result",
                "name": data.get("name", ""),
                "output": data.get("output", ""),
                "error": data.get("error", ""),
                "duration_ms": data.get("duration_ms", 0),
            })
        elif event.type == RETRIEVAL_RESULT:
            assistant["knowledge_references"] = [
                ref for ref in (_ref_title(r) for r in (data.get("refs") or [])) if ref
            ]
        elif event.type == TURN_COMPLETED:
            if data.get("content"):
                assistant["content"] = data.get("content")
            assistant["agent_duration_ms"] = int(data.get("duration_ms") or 0)
            assistant["stopped_reason"] = data.get("stopped_reason", "completed")
            assistant["is_completed"] = True
            assistant["is_fallback"] = data.get("stopped_reason") == "error"
        elif event.type == TURN_ERROR:
            assistant["content"] = data.get("message", "")
            assistant["is_completed"] = True
            assistant["is_fallback"] = True

    if fields is None:
        return None
    return fields


def rebuild_projection(session_id: str) -> dict:
    """删除该会话由事件派生的消息并从事件重建，返回统计。

    纪律：只重建由轨迹产生的轮次（有 turn/user-message 事件的 request_id），
    不触碰会话里无法溯源的存量消息。
    """
    events = SessionEvent.objects.filter(session_id=session_id).order_by("seq")
    grouped: dict[str, list[SessionEvent]] = defaultdict(list)
    for event in events:
        if event.request_id:
            grouped[event.request_id].append(event)

    rebuilt = 0
    for request_id, turn_events in grouped.items():
        fields = _projection_fields_for_turn(turn_events)
        if fields is None:
            continue
        Message.objects.filter(session_id=session_id, request_id=request_id).delete()
        fields.pop("agent_steps")
        Message.objects.create(**fields)
        steps = _assistant_steps_from_events(turn_events)
        assistant_fields = _assistant_fields_from_events(turn_events, steps)
        if assistant_fields is not None:
            Message.objects.create(session_id=session_id, **assistant_fields)
        rebuilt += 1
    return {"session_id": session_id, "turns_rebuilt": rebuilt, "events_folded": sum(len(v) for v in grouped.values())}


def _assistant_steps_from_events(turn_events: list[SessionEvent]) -> list[dict]:
    steps: list[dict] = []
    for event in turn_events:
        if event.type != TOOL_RESULT:
            continue
        data = event.data if isinstance(event.data, dict) else {}
        steps.append({
            "name": data.get("name", ""),
            "arguments": {},
            "output": data.get("output", ""),
            "error": data.get("error", ""),
            "duration_ms": data.get("duration_ms", 0),
        })
    return steps


def _assistant_fields_from_events(turn_events: list[SessionEvent], steps: list[dict]) -> dict | None:
    content = ""
    refs: list = []
    duration_ms = 0
    completed = False
    is_fallback = False
    channel = "web"
    request_id = turn_events[0].request_id if turn_events else ""
    saw_assistant_turn = False
    for event in turn_events:
        data = event.data if isinstance(event.data, dict) else {}
        if event.type == TURN_ASSISTANT_CREATED:
            saw_assistant_turn = True
            channel = data.get("channel", "web")
        elif event.type == AGENT_THINKING and not content:
            content = data.get("content", "")
        elif event.type == RETRIEVAL_RESULT and not refs:
            refs = [ref for ref in (_ref_title(r) for r in (data.get("refs") or [])) if ref]
        elif event.type == TURN_COMPLETED:
            saw_assistant_turn = True
            content = data.get("content") or content
            duration_ms = int(data.get("duration_ms") or 0)
            completed = True
            is_fallback = data.get("stopped_reason") == "error"
        elif event.type == TURN_ERROR:
            saw_assistant_turn = True
            content = data.get("message", content)
            completed = True
            is_fallback = True
    if not saw_assistant_turn:
        return None
    return {
        "request_id": request_id,
        "role": "assistant",
        "content": content,
        "rendered_content": content,
        "knowledge_references": refs,
        "agent_steps": steps or None,
        "agent_duration_ms": duration_ms,
        "is_completed": completed,
        "is_fallback": is_fallback,
        "channel": channel,
    }
