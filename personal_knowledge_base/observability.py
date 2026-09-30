"""可观测性模块：Langfuse v3 SDK 集成（可选依赖，旁路设计）。

设计原则：
- Langfuse 是旁路：任何上报失败都静默降级，绝不影响问答/解析/评估主流程，
  也不得导致模型被重复调用；
- LANGFUSE_ENABLED=false、未安装 SDK 或未配置密钥时，全部接口为无操作；
- 隐私默认关（LANGFUSE_LOG_CONTENT=false）：只上报模型、场景、token 数、耗时等
  元数据，不上传 prompt 与文档内容；metadata 出口统一经 _safe_metadata 脱敏。

trace 层级与业务对齐：
- chat.turn        一轮问答根（chat/views）
- agent.run        Agent 循环（agent_engine）
- knowledge.parse  文档解析尝试根（SpanTracker 镜像）
- evaluation.run   评估任务（tasks）
generation 生命周期由 start_model_call/finish_model_call 表达（请求前创建、
消费结束后关闭，带真实起止时间）；兼容入口 report_model_call 保留事后上报语义。

线程约定：
- 句柄与 scope 分离：TraceHandle 记录创建时的 contextvar token，关闭时恢复父级
  而不是清空；跨线程不使用 reset token，由调用方 copy_context() 传播；
- _call_context 更新为 copy-on-write，不原地修改共享字典。
"""

from __future__ import annotations

import contextvars
import logging
import hashlib
import json
import math
import random
import re
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field

from django.conf import settings

logger = logging.getLogger(__name__)

try:
    from langfuse import Langfuse  # noqa: F401
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False

_client = None
_client_ready = False
_client_lock = threading.Lock()
# 当前活动业务节点（TraceHandle 或 SDK 原始 span）；嵌套/父级判定走鸭子类型。
_current_span: contextvars.ContextVar = contextvars.ContextVar("langfuse_current_span", default=None)

# 当前 LLM 调用归属的会话轮次上下文（session/request/actor/iteration）。
# 由 agent 引擎、RAG 生成线程、维护线程显式 set；线程池 worker 不传播 contextvar，
# 必须在使用方 copy_context() 或线程内重新 set，否则 record_model_usage 不发射 llm/call 轨迹事件。
_call_context: contextvars.ContextVar = contextvars.ContextVar("llm_call_context", default=None)


# ── LLM 调用归属上下文（copy-on-write）───────────────────────────────


def set_llm_call_context(
    *,
    session_id: str = "",
    request_id: str = "",
    actor_id: str = "",
    agent_type: str = "",
    iteration: int | None = None,
):
    """设置当前线程后续 LLM 调用的轨迹归属；返回 token 供 reset_llm_call_context 恢复。"""
    return _call_context.set({
        "session_id": str(session_id or ""),
        "request_id": str(request_id or ""),
        "actor_id": str(actor_id or ""),
        "agent_type": str(agent_type or ""),
        "iteration": iteration,
    })


def reset_llm_call_context(token) -> None:
    try:
        _call_context.reset(token)
    except Exception:
        pass


def update_llm_call_context(**fields) -> None:
    """局部更新当前上下文（如引擎每轮更新 iteration）。

    copy-on-write：构造新 dict 替换，不原地修改——并发线程从 copy_context()
    继承的同一 dict 不会被相互污染。未设置时忽略。
    """
    current = _call_context.get()
    if not current:
        return
    _call_context.set({**current, **{key: value for key, value in fields.items()}})


def get_llm_call_context() -> dict | None:
    return _call_context.get()


# ── 客户端与开关 ──────────────────────────────────────────────────


def get_langfuse():
    """获取或创建 Langfuse v3 客户端；总开关关闭/未安装/未配置/初始化失败时返回 None。"""
    global _client, _client_ready
    # The kill switch must win over an already-initialized singleton.
    if not getattr(settings, "LANGFUSE_ENABLED", False) or not LANGFUSE_AVAILABLE:
        return None
    with _client_lock:
        if _client_ready:
            return _client
        public_key = str(getattr(settings, "LANGFUSE_PUBLIC_KEY", "") or "")
        secret_key = str(getattr(settings, "LANGFUSE_SECRET_KEY", "") or "")
        if not public_key or not secret_key:
            return None
        _client_ready = True
        try:
            _client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=str(getattr(settings, "LANGFUSE_BASE_URL", "") or "http://localhost:3000"),
                environment=str(getattr(settings, "LANGFUSE_TRACING_ENVIRONMENT", "") or "") or None,
                # Business roots already sample; the SDK must retain the whole admitted tree.
                sample_rate=1.0,
            )
        except Exception:
            logger.warning("Langfuse client init failed; observability disabled")
            _client = None
        return _client


def langfuse_enabled() -> bool:
    return get_langfuse() is not None


def langfuse_log_content() -> bool:
    return bool(getattr(settings, "LANGFUSE_LOG_CONTENT", False))


def _root_sampled() -> bool:
    """根级采样判定；子节点随根存在与否自然继承，不与 SDK 内部采样叠加。"""
    raw = getattr(settings, "LANGFUSE_SAMPLE_RATE", 1.0)
    try:
        rate = float(raw)
    except (TypeError, ValueError):
        rate = 1.0
    # 注意 0.0 是合法值（全关），不能写 `raw or 1.0`
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    return random.random() < rate


def flush_langfuse():
    """尽力 flush 批量队列（长任务结束/诊断命令使用；不在每个请求或 token 上调用）。"""
    if _client is not None:
        try:
            _client.flush()
        except Exception:
            pass


# ── 隐私：metadata 统一脱敏 ────────────────────────────────────────

# 命中键名的敏感词：值替换为占位符（对 input/output/error/自动埋点之外的自定义
# metadata 生效；异常文本也经 _mask_secrets 处理）
_SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api_?key|authorization|auth|cookie|session_key|credential)",
    re.IGNORECASE,
)
# 异常/URL 文本中的内联凭证：scheme://user:pass@ 与 key=value 形态
_INLINE_SECRET_RE = re.compile(
    r"(?://[^/@\s:]+:[^/@\s]+@)|"
    r"((?:api_?key|access_?key|secret|token|password|key)\s*[=:]\s*[^\s&\"']+)",
    re.IGNORECASE,
)


_CONTENT_KEY_RE = re.compile(
    r"(^|_)(query|question|answer|prompt|content|text|title|body|input|output|"
    r"error|message|reasoning|filename|path|email|username|preview)(_|$)", re.I
)
_NUMERIC_TOKEN_KEYS = frozenset({
    "prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens",
    "reasoning_tokens", "input_tokens", "output_tokens",
})
_BEARER_RE = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+")
_JSON_SECRET_RE = re.compile(
    r"""(?i)(["'](?:api_?key|access_?key|secret|token|password|authorization|cookie)["']\s*:\s*)(["'])(.*?)\2"""
)


def _mask_secrets(text: str) -> str:
    text = str(text)
    text = _BEARER_RE.sub(lambda m: m.group(1) + " ***", text)
    text = _JSON_SECRET_RE.sub(lambda m: m.group(1) + m.group(2) + "***" + m.group(2), text)
    return _INLINE_SECRET_RE.sub("***", text)


def _safe_error(error) -> str:
    if not langfuse_log_content():
        return type(error).__name__ if isinstance(error, BaseException) else "operation failed (details hidden)"
    return _mask_secrets(str(error))[:500]


def _safe_value(value, limit: int = 500, _depth: int = 0) -> object:
    if _depth >= 6:
        return "<truncated>"
    if isinstance(value, (int, float, bool)) or value is None:
        return value if not isinstance(value, float) or math.isfinite(value) else None
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, limit, _depth + 1) for item in value[:50]]
    if isinstance(value, dict):
        return _safe_metadata(value, limit=limit, _depth=_depth + 1)
    return _mask_secrets(str(value))[:limit]


def _safe_metadata(metadata: dict | None, limit: int = 500, _depth: int = 0) -> dict:
    result = {}
    for index, (key, value) in enumerate((metadata or {}).items()):
        if index >= 50:
            result["_truncated"] = True
            break
        try:
            key = str(key)[:120]
            numeric = key in _NUMERIC_TOKEN_KEYS and isinstance(value, (int, float))
            if not numeric and _SENSITIVE_KEY_RE.search(key) and value not in (None, "", True, False):
                result[key] = "<redacted>"
            elif (not langfuse_log_content() and _CONTENT_KEY_RE.search(key)
                  and key not in {"message_id", "user_message_id", "assistant_message_id"}
                  and value is not None and not isinstance(value, (int, float, bool))):
                result[key] = "<content omitted>"
            else:
                result[key] = _safe_value(value, limit, _depth)
        except Exception:
            continue
    return result


# ── 句柄：SDK span 包装，idempotent 结束，scope 分离 ─────────────────

_STATUS_LEVEL = {
    "completed": "DEFAULT",
    "failed": "ERROR",
    "error": "ERROR",
    "cancelled": "WARNING",
    "canceled": "WARNING",
    "timeout": "WARNING",
    "degraded": "WARNING",
}


def _level_for(status: str) -> str:
    return _STATUS_LEVEL.get(str(status or "completed").lower(), "DEFAULT")


@dataclass
class TraceHandle:
    """业务 trace/子树句柄：持有 SDK span、远端 ID 与 scope 恢复信息。

    - trace_id 是远端 trace ID（32 hex），observation_id 是本节点 ID——二者不可混用；
    - close 幂等，可在终结竞争（取消/超时/晚到成功）下并发调用；
    - token 用于关闭时恢复父级 contextvar；跨线程关闭时 reset 会失败并被吞掉，
      此时保留当前值（由外层 scope 负责最终恢复）。
    """

    span: object | None = None
    trace_id: str = ""
    observation_id: str = ""
    token: object = None
    _ended: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # 委托：让句柄可以直接当父节点使用（嵌套子 span / generation）
    def start_span(self, name: str, metadata: dict | None = None, **kwargs):
        return self.span.start_span(name=name, metadata=metadata, **kwargs)

    def start_generation(self, name: str, metadata: dict | None = None, **kwargs):
        return self.span.start_generation(name=name, metadata=metadata, **kwargs)

    def start_observation(self, name: str, metadata: dict | None = None, **kwargs):
        return self.span.start_observation(name=name, metadata=metadata, **kwargs)

    def update(self, **kwargs):
        if self.span is not None:
            try:
                self.span.update(**kwargs)
            except Exception:
                pass

    def close(self, *, output: dict | None = None, status: str = "completed", error=None) -> bool:
        """幂等关闭；首个调用生效，后续并发调用为 no-op。返回是否由本次调用关闭。"""
        with self._lock:
            if self._ended:
                return False
            self._ended = True
        if self.span is not None:
            try:
                payload = {}
                if output:
                    payload["output"] = _safe_metadata(output)
                level = _level_for(status)
                if level != "DEFAULT":
                    payload["level"] = level
                if error:
                    payload["status_message"] = _safe_error(error)
                if payload:
                    self.span.update(**payload)
            except Exception:
                pass
            try:
                self.span.end()
            except Exception:
                pass
        # 恢复外层父级（而非清空）；跨线程 reset 失败时忽略
        if self.token is not None:
            try:
                _current_span.reset(self.token)
            except Exception:
                pass
        return True


def _wrap_handle(span) -> TraceHandle | None:
    """把 SDK span 包装为 TraceHandle，提取 trace_id/observation_id 并登记 scope。"""
    try:
        trace_id = str(getattr(span, "trace_id", "") or "")
        observation_id = str(getattr(span, "id", "") or "")
    except Exception:
        trace_id, observation_id = "", ""
    handle = TraceHandle(span=span, trace_id=trace_id, observation_id=observation_id)
    handle.token = _current_span.set(handle)
    return handle


def _as_parent(parent):
    """归一化父节点：TraceHandle → 其底层 span；None → 当前上下文。"""
    if isinstance(parent, TraceHandle):
        return parent.span
    if parent is None:
        current = _current_span.get()
        if isinstance(current, TraceHandle):
            return current.span
        return current
    return parent


def current_trace_id() -> str:
    """当前上下文关联的远端 trace ID（无活动 trace 时为空串）。

    detached 子代理用它记录 parent_trace_id；本地取得，不等待网络上传。
    """
    current = _current_span.get()
    if isinstance(current, TraceHandle):
        return current.trace_id
    return str(getattr(current, "trace_id", "") or "")


@contextmanager
def detached_trace_scope():
    """临时清空当前 trace scope（detached 子代理建新根用，计划 §3.5）。

    同步模式（APP_TASKS_SYNC）下 worker 在父线程执行，也会继承父 scope——
    此处显式清空，保证 detached 语义与线程模式一致。
    """
    token = _current_span.set(None)
    try:
        yield
    finally:
        try:
            _current_span.reset(token)
        except Exception:
            pass


@contextmanager
def request_trace_scope():
    """A request owns its Context tokens; a worker owns the transferred span lifetime."""
    span_token = _current_span.set(None)
    call_token = _call_context.set(None)
    try:
        yield
    except BaseException as exc:
        current = _current_span.get()
        if isinstance(current, TraceHandle):
            close_business_trace(current, status="failed", error=exc)
        raise
    finally:
        _call_context.reset(call_token)
        _current_span.reset(span_token)


# ── 业务 trace 根与子 span ─────────────────────────────────────────


def start_business_trace(name: str, *, session_id="", user_id="", metadata: dict | None = None):
    """开启一条业务 trace 节点并设为当前上下文；返回 TraceHandle（未启用时为 None；未采样时为空句柄）。

    已有活动节点时嵌套为子树，无活动节点时作为业务 trace 根。
    session_id/user_id 经 SDK update_trace 设置（v3 的 start_span 不接受这些参数，
    直接传参会 TypeError 静默丢失——真实 SDK 契约，勿改回 payload 传参）。
    """
    client = get_langfuse()
    if not client:
        return None
    parent = _current_span.get()
    if (isinstance(parent, TraceHandle) and parent.span is None) or (parent is None and not _root_sampled()):
        return _wrap_handle(None)
    try:
        if parent is not None:
            parent_span = parent.span if isinstance(parent, TraceHandle) else parent
            span = parent_span.start_span(name=name, metadata=_safe_metadata(metadata))
        else:
            span = client.start_span(name=name, metadata=_safe_metadata(metadata))
            if session_id or user_id:
                try:
                    span.update_trace(
                        session_id=str(session_id) if session_id else None,
                        user_id=str(user_id) if user_id else None,
                    )
                except Exception:
                    pass
    except Exception:
        logger.debug("langfuse start_business_trace failed", exc_info=True)
        return None
    return _wrap_handle(span)


def close_business_trace(handle, output: dict | None = None, *, status: str = "completed", error=None):
    """结束 start_business_trace 开启的节点；幂等并恢复外层父级。

    status: completed/failed/cancelled/timeout/degraded；error 为业务错误对象或消息，
    经脱敏截断后进 status_message，不吞业务异常（本函数不抛出，异常只记日志）。
    """
    if handle is None:
        return
    try:
        handle.close(output=output, status=status, error=error)
    except Exception:
        logger.debug("langfuse close_business_trace failed", exc_info=True)


def start_child_span(parent, name: str, metadata: dict | None = None):
    """在指定父节点（None 时用当前上下文）下开一个子 span；不可用时返回 None。

    返回 SDK 原始 span（不带 scope）；需要 scope 用 child_span 上下文管理器。
    """
    parent = _as_parent(parent)
    if parent is None:
        return None
    try:
        return parent.start_span(name=name, metadata=_safe_metadata(metadata))
    except Exception:
        return None


def close_child_span(span, output: dict | None = None, error_message: str = ""):
    """结束 start_child_span 开启的子 span（不触碰 contextvar scope）。"""
    if span is None:
        return
    try:
        payload = {}
        if output:
            payload["output"] = _safe_metadata(output)
        if error_message:
            payload["level"] = "ERROR"
            payload["status_message"] = _safe_error(error_message)
        if payload:
            span.update(**payload)
    except Exception:
        pass
    try:
        span.end()
    except Exception:
        pass


@contextmanager
def child_span(name: str, metadata: dict | None = None):
    span = start_child_span(None, name, metadata)
    if span is None:
        yield None
        return
    previous = _current_span.set(span)
    start = time.monotonic()
    error = None
    try:
        yield span
    except BaseException as exc:
        error = exc
        raise
    finally:
        try:
            close_child_span(span, output={"duration_ms": int((time.monotonic() - start) * 1000)},
                             error_message=error)
        finally:
            _current_span.reset(previous)


# ── 模型调用生命周期：请求前创建 generation，消费结束后关闭 ───────────


@dataclass
class ModelCallHandle:
    """一次真实模型调用的远端 generation 句柄（一个 model_call_id 对应一个 generation）。"""

    generation: object | None = None
    model_call_id: str = ""
    as_type: str = "generation"
    started_mono: float = field(default_factory=time.monotonic)
    started_wall: float = field(default_factory=time.time)
    _ended: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def close(self) -> bool:
        with self._lock:
            if self._ended:
                return False
            self._ended = True
        return True


def _usage_details_from(usage: dict | None) -> dict | None:
    """Langfuse flat usage buckets are non-overlapping, unlike inclusive provider totals."""
    if not usage:
        return None
    prompt = max(int(usage.get("prompt_tokens") or 0), 0)
    completion = max(int(usage.get("completion_tokens") or 0), 0)
    cached = min(max(int(usage.get("cached_tokens") or 0), 0), prompt)
    reasoning = min(max(int(usage.get("reasoning_tokens") or 0), 0), completion)
    details = {"input": prompt - cached, "output": completion - reasoning,
               "total": prompt + completion}
    if cached:
        details["input_cached_tokens"] = cached
    if reasoning:
        details["output_reasoning_tokens"] = reasoning
    return details


def start_model_call(*, model_call_id: str, model: str, provider: str = "", scenario: str = "",
                     metadata: dict | None = None, as_type: str = "generation") -> ModelCallHandle | None:
    """在实际供应商请求前创建远端观测节点；无 trace 上下文时按 LANGFUSE_ORPHAN_MODE 处理。

    as_type 按真实业务分类：chat/VLM 等生成调用用 "generation"，embedding 用
    "embedding"，rerank 无 token 生成语义用 "span"——不伪造 Chat 响应。
    usage 此时未知，不冒充零；finish_model_call 时更新同一节点。
    """
    client = get_langfuse()
    if not client or not model_call_id:
        return None
    parent = _current_span.get()
    if parent is None and str(getattr(settings, "LANGFUSE_ORPHAN_MODE", "skip")).lower() != "standalone":
        return None
    if isinstance(parent, TraceHandle) and parent.span is None:
        return None
    safe_metadata = _safe_metadata({
        **(get_llm_call_context() or {}),
        "model_call_id": model_call_id,
        "provider": provider,
        "scenario": scenario,
        **(metadata or {}),
    })
    try:
        parent_span = _as_parent(parent) or client
        if hasattr(parent_span, "start_observation"):
            generation = parent_span.start_observation(
                as_type=as_type if as_type in {"generation", "embedding", "span", "chain",
                                               "retriever", "agent", "tool"} else "generation",
                name=f"llm.{scenario or 'call'}",
                model=model or None,
                metadata=safe_metadata,
            )
        else:  # 旧 Fake/降级路径：start_generation 无 as_type
            generation = parent_span.start_generation(
                name=f"llm.{scenario or 'call'}",
                model=model or None,
                metadata=safe_metadata,
            )
    except Exception:
        logger.debug("langfuse start_model_call failed", exc_info=True)
        return None
    return ModelCallHandle(generation=generation, model_call_id=str(model_call_id), as_type=as_type)


def finish_model_call(handle: ModelCallHandle | None, *, usage: dict | None = None,
                      status: str = "completed", output_preview: str = "", error=None) -> None:
    """结束 start_model_call 创建的 generation；幂等（取消/超时/晚到成功只终结一次）。"""
    if handle is None or handle.generation is None:
        return
    if not handle.close():
        return
    duration_ms = int((time.monotonic() - handle.started_mono) * 1000)
    try:
        payload: dict = {"metadata": _safe_metadata({"duration_ms": duration_ms, "status": status})}
        details = _usage_details_from(usage)
        if details and handle.as_type in {"generation", "embedding"}:
            payload["usage_details"] = details
        level = _level_for(status)
        if level != "DEFAULT":
            payload["level"] = level
        if error:
            payload["status_message"] = _safe_error(error)
        elif output_preview and langfuse_log_content():
            payload["output"] = {"preview": _mask_secrets(str(output_preview))[:2000]}
        handle.generation.update(**payload)
    except Exception:
        logger.debug("langfuse finish_model_call failed", exc_info=True)
    try:
        handle.generation.end()
    except Exception:
        pass


def report_model_call(
    *,
    name: str = "",
    model: str = "",
    scenario: str = "",
    success: bool = True,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    cached_tokens: int = 0,
    duration_ms: int = 0,
    error_message: str = "",
    metadata: dict | None = None,
    input_preview: str = "",
    output_preview: str = "",
):
    """事后上报一次模型调用（兼容入口；record_model_usage 调用）。

    注意：本入口在调用结束后创建并立即结束 generation，起止时间为上报时刻近似值；
    需要真实时间范围的生命周期用 start_model_call/finish_model_call（P3 起）。
    自动嵌入 contextvar 指向的当前业务 trace；无 trace 时按 LANGFUSE_ORPHAN_MODE 处理。
    input/output 预览仅在 LANGFUSE_LOG_CONTENT 开启时上报（隐私默认关）。
    """
    client = get_langfuse()
    if not client:
        return
    parent = _current_span.get()
    if parent is None and str(getattr(settings, "LANGFUSE_ORPHAN_MODE", "skip")).lower() != "standalone":
        return
    if isinstance(parent, TraceHandle) and parent.span is None:
        return
    safe_metadata = _safe_metadata(metadata)
    payload = {
        "name": name or f"llm.{scenario or 'call'}",
        "model": model or None,
        "metadata": safe_metadata,
        "level": "DEFAULT" if success else "ERROR",
    }
    if error_message:
        payload["status_message"] = _safe_error(error_message)
    details = _usage_details_from({
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cached_tokens": cached_tokens,
    })
    if details and (prompt_tokens or completion_tokens or total_tokens):
        payload["usage_details"] = details
    if langfuse_log_content():
        # 内容预览默认不上报；显式开启 LANGFUSE_LOG_CONTENT 时携带脱敏截断预览用于调试
        if input_preview:
            payload["input"] = {"preview": _mask_secrets(str(input_preview))[:2000]}
        if output_preview or error_message:
            payload["output"] = {"preview": _mask_secrets(str(output_preview) or f"ERROR: {error_message}")[:2000]}
    try:
        parent_span = _as_parent(parent)
        if parent_span is not None and hasattr(parent_span, "start_generation"):
            generation = parent_span.start_generation(**payload)
        else:
            generation = client.start_generation(**payload)
        generation.end()
    except Exception:
        logger.debug("langfuse generation report failed", exc_info=True)


# ── 评估上报 ──────────────────────────────────────────────────────


def report_evaluation_run(
    *,
    name: str,
    task_run_id: str,
    metrics: dict | None = None,
    dataset_name: str = "",
    entries: list | None = None,
    metadata: dict | None = None,
    examples: list | None = None,
):
    """把一次评估运行上报为 Langfuse trace（每次评估一条，指标进 output）。

    examples：真实逐样例评分（与数据行对齐的 dict 列表），存在时为每样例建
    evaluation.example 子 span 并挂分数（score_id 由 task_run_id+example_id+指标名
    确定性生成；不代表 trace/observation 同步整体幂等）。没有逐样例值的旧任务只报汇总，不伪造。
    LANGFUSE_UPLOAD_EVAL_DATASETS 与 LANGFUSE_LOG_CONTENT 同时开启时，才把题目/参考答案
    upsert 成 Dataset；同数据集/版本/脱敏内容使用稳定 item ID。此入口是事后结果桥接。
    """
    client = get_langfuse()
    if not client:
        return
    trace_metadata = {**(metadata or {}), "task_run_id": task_run_id}
    handle = start_business_trace(name, metadata=trace_metadata)
    if handle is not None:
        for index, example in enumerate((examples or [])[:500]):
            example = example or {}
            valid = bool(example.get("valid", True))
            scores = {k: v for k, v in example.items() if k not in {"valid", "error", "example_id", "row_index"}} if valid else {}
            example_id = str(example.get("example_id") or f"row-{index}")
            example_meta = {
                "task_run_id": task_run_id,
                "example_id": example_id,
                "row_index": example.get("row_index", index),
                "valid": valid,
            }
            ex_span = start_child_span(handle, "evaluation.example", metadata=example_meta)
            if ex_span is not None:
                for score_name, value in scores.items():
                    try:
                        numeric = float(value)
                        if isinstance(value, bool) or not math.isfinite(numeric):
                            continue
                    except (TypeError, ValueError):
                        continue
                    try:
                        # 确定性 score_id：同一任务/样例/指标重复同步幂等
                        stable = uuid.uuid5(uuid.NAMESPACE_URL, f"{task_run_id}:{example_id}:{score_name}")
                        ex_span.score(name=str(score_name), value=numeric, score_id=str(stable))
                    except Exception:
                        continue
            close_child_span(ex_span, output={"scores_count": len(scores), "valid": valid},
                             error_message=(example.get("error") or "evaluation example invalid") if not valid else "")
        close_business_trace(handle, output=metrics or {"status": "completed"})
    if not getattr(settings, "LANGFUSE_UPLOAD_EVAL_DATASETS", False) or not langfuse_log_content() or not entries:
        flush_langfuse()
        return
    try:
        dataset_label = dataset_name or name
        try:
            client.create_dataset(name=dataset_label)
        except Exception:
            pass  # 已存在
        for entry in entries[:500]:
            try:
                question = _mask_secrets(str((entry or {}).get("question") or ""))[:2000]
                answer = _mask_secrets(str((entry or {}).get("reference_answer") or
                    (entry or {}).get("ground_truth") or (entry or {}).get("answer") or ""))[:2000]
                version = str((metadata or {}).get("dataset_version") or "")
                fingerprint = hashlib.sha256(json.dumps([dataset_label, version, question, answer],
                    ensure_ascii=False).encode()).hexdigest()
                client.create_dataset_item(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, fingerprint)),
                    dataset_name=dataset_label,
                    input={"question": question},
                    expected_output={"answer": answer},
                    metadata={"task_run_id": task_run_id},
                )
            except Exception:
                continue
    except Exception:
        logger.debug("langfuse eval dataset upload failed", exc_info=True)
    flush_langfuse()


# ── 兼容接口：agent_engine / chat 流式协议测试依赖以下签名 ──────────────


@dataclass
class TraceContext:
    """追踪上下文，贯穿一次完整的 Agent 执行。

    trace_id 为远端 trace ID（TraceHandle.trace_id），不是 observation ID。
    query 仅本地留存用于业务逻辑，不直接进 metadata（由各上报点按隐私开关决定）。
    """

    trace_id: str = ""
    session_id: str = ""
    user_id: str = ""
    query: str = ""
    metadata: dict = field(default_factory=dict)
    _spans: list = field(default_factory=list)

    def add_span(self, name: str, metadata: dict = None):
        self._spans.append({"name": name, "metadata": metadata or {}, "start_time": time.time()})


@contextmanager
def trace_agent_execution(session_id: str, user_id: str, query: str, agent_mode: str = ""):
    """追踪一次 Agent 执行（业务 trace：agent.run）。"""
    ctx = TraceContext(
        session_id=session_id,
        user_id=user_id,
        query=query[:2000],
        metadata={"agent_mode": agent_mode},
    )
    start = time.monotonic()
    handle = None
    if get_langfuse():
        trace_metadata = {"agent_mode": agent_mode, "query_length": len(query or "")}
        if langfuse_log_content():
            trace_metadata["query"] = (query or "")[:500]
        handle = start_business_trace("agent.run", session_id=session_id, user_id=user_id, metadata=trace_metadata)
        if handle is not None:
            ctx.trace_id = handle.trace_id
    error = None
    try:
        yield ctx
    except BaseException as exc:
        error = exc
        raise
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        if handle is not None:
            output = {"total_iterations": len(ctx._spans), "duration_ms": duration_ms}
            output.update(_safe_metadata(ctx.metadata))
            close_business_trace(handle, output=output, status="failed" if error else "completed", error=error)


@contextmanager
def trace_llm_call(trace_ctx: TraceContext, model: str, messages: list[dict], tools: list = None):
    """追踪一次 LLM 调用（嵌在业务 trace 下的业务 span，不计费用量）。

    兼容契约：yield 出的 dict 由调用方写入 content/tool_calls/error；
    token 用量由 model_providers 的 record_model_usage 统一上报 generation，
    此处不重复记录，避免零 token 用量记录（见 tests.py 回归用例）。
    """
    result = {"content": "", "tool_calls": None, "error": None}
    parent = _current_span.get()
    span = None
    if parent is not None and trace_ctx is not None and trace_ctx.trace_id:
        span = start_child_span(parent, f"llm.call.{model}", metadata={
            "model": model,
            "messages_count": len(messages or []),
            "has_tools": bool(tools),
        })
    previous = _current_span.set(span) if span is not None else None
    start = time.monotonic()
    try:
        yield result
    except BaseException as exc:
        result["error"] = exc
        raise
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        if span is not None:
            close_child_span(span, output={
                "content_length": len(result.get("content") or ""),
                "has_tool_calls": bool(result.get("tool_calls")),
                "error": result.get("error"),
                "duration_ms": duration_ms,
            }, error_message=result.get("error"))
            if previous is not None:
                _current_span.reset(previous)


@contextmanager
def trace_tool_execution(trace_ctx: TraceContext, tool_name: str, args: dict):
    """追踪一次工具执行（span 包围真实执行时间）。

    隐私默认关：metadata 只含参数名与个数；开启 LANGFUSE_LOG_CONTENT 后记入
    脱敏截断的参数值。output 同样受开关控制；error 恒脱敏后上报。
    """
    start = time.monotonic()
    parent = _current_span.get()
    span = None
    if parent is not None and trace_ctx is not None and trace_ctx.trace_id:
        args_meta: dict = {"arg_names": sorted((args or {}).keys()), "arg_count": len(args or {})}
        if langfuse_log_content():
            args_meta["args"] = _safe_metadata(args or {}, limit=120)
        span = start_child_span(parent, f"tool.{tool_name}", metadata=args_meta)
    previous = _current_span.set(span) if span is not None else None
    result = {"output": "", "error": None}
    try:
        yield result
    except BaseException as exc:
        result["error"] = exc
        raise
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        if span is not None:
            output_payload: dict = {"duration_ms": duration_ms}
            if result.get("error"):
                output_payload["error"] = result["error"]
            elif langfuse_log_content():
                # 脱敏：只保留前 500 字符
                output_payload["output"] = _mask_secrets(str(result.get("output") or ""))[:500]
            close_child_span(span, output=output_payload, error_message=result.get("error"))
            if previous is not None:
                _current_span.reset(previous)
