"""
可观测性模块：Langfuse v3 SDK 集成（可选依赖，旁路设计）。

设计原则：
- Langfuse 是旁路：任何上报失败都静默降级，绝不影响问答/解析/评估主流程；
- 未安装 SDK 或未配置 LANGFUSE_PUBLIC_KEY/SECRET_KEY 时，全部接口为无操作；
- 隐私默认关（LANGFUSE_LOG_CONTENT=false）：只上报模型、场景、token 数、耗时等
  元数据，不上传 prompt 与文档内容。

trace 层级与业务对齐：
- chat.message      聊天端点开启（session_id = 聊天会话）
- agent.run         Agent 循环（agent_engine）
- knowledge.parse   文档解析（SpanTracker 镜像）
generation 层由 model_usage.record_model_usage 统一上报，经 contextvar 自动嵌入
当前业务 trace；当前无 trace 时按 LANGFUSE_ORPHAN_MODE（skip/standalone）处理。

注意：当前 span 通过模块级 contextvar 显式传递，不依赖 SDK 的隐式 OTEL 上下文，
因此跨线程（如聊天流式生成线程）需要调用方用 contextvars.copy_context() 传播。
"""

from __future__ import annotations

import contextvars
import logging
import time
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
_current_span: contextvars.ContextVar = contextvars.ContextVar("langfuse_current_span", default=None)


def get_langfuse():
    """获取或创建 Langfuse v3 客户端；未安装/未配置/初始化失败时返回 None。"""
    global _client, _client_ready
    if _client_ready:
        return _client
    _client_ready = True
    if not LANGFUSE_AVAILABLE:
        return None
    public_key = str(getattr(settings, "LANGFUSE_PUBLIC_KEY", "") or "")
    secret_key = str(getattr(settings, "LANGFUSE_SECRET_KEY", "") or "")
    if not public_key or not secret_key:
        return None
    try:
        _client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=str(getattr(settings, "LANGFUSE_HOST", "") or "http://localhost:3000"),
        )
    except Exception:
        logger.warning("Langfuse client init failed; observability disabled")
        _client = None
    return _client


def langfuse_enabled() -> bool:
    return get_langfuse() is not None


def langfuse_log_content() -> bool:
    return bool(getattr(settings, "LANGFUSE_LOG_CONTENT", False))


def flush_langfuse():
    """尽力 flush 批量队列（长任务结束时调用；SDK 亦有周期性/退出时 flush）。"""
    if _client is not None:
        try:
            _client.flush()
        except Exception:
            pass


def _safe_metadata(metadata: dict | None) -> dict:
    """metadata 统一转成可序列化、截断后的扁平 dict。"""
    result = {}
    for key, value in (metadata or {}).items():
        try:
            if isinstance(value, (int, float, bool)) or value is None:
                result[str(key)] = value
            else:
                result[str(key)] = str(value)[:500]
        except Exception:
            continue
    return result


def start_business_trace(name: str, *, session_id: Any = "", user_id: Any = "", metadata: dict | None = None):
    """开启一条业务 trace 根 span 并设为当前上下文。

    返回 span 句柄（未启用时为 None）；调用方负责在结束时调用 close_business_trace。
    """
    client = get_langfuse()
    if not client:
        return None
    safe_metadata = _safe_metadata(metadata)
    payload = {"name": name, "metadata": safe_metadata}
    if session_id:
        payload["session_id"] = str(session_id)
    if user_id:
        payload["user_id"] = str(user_id)
    try:
        span = client.start_span(**payload)
    except TypeError:
        try:
            span = client.start_span(name=name, metadata=safe_metadata)
        except Exception:
            return None
    except Exception:
        return None
    if span is None:
        return None
    _current_span.set(span)
    return span


def close_business_trace(handle, output: dict | None = None):
    """结束 start_business_trace 开启的 trace，并清理上下文。"""
    if handle is None:
        return
    if output:
        try:
            handle.update(output=_safe_metadata(output))
        except Exception:
            pass
    try:
        handle.end()
    except Exception:
        pass
    _current_span.set(None)


def start_child_span(parent, name: str, metadata: dict | None = None):
    """在指定父 span（None 时用当前上下文）下开一个子 span；不可用时返回 None。"""
    if parent is None:
        parent = _current_span.get()
    if parent is None:
        return None
    try:
        return parent.start_span(name=name, metadata=_safe_metadata(metadata))
    except Exception:
        return None


def close_child_span(span, output: dict | None = None, error_message: str = ""):
    """结束 start_child_span 开启的子 span。"""
    if span is None:
        return
    try:
        if output:
            span.update(output=_safe_metadata(output))
        if error_message:
            span.update(level="ERROR", status_message=str(error_message)[:500])
    except Exception:
        pass
    try:
        span.end()
    except Exception:
        pass


@contextmanager
def child_span(name: str, metadata: dict | None = None):
    """以当前 trace 为父开一个子 span 的上下文管理器；无 trace 时为无操作。"""
    span = start_child_span(None, name, metadata)
    if span is None:
        yield None
        return
    previous = _current_span.set(span)
    start = time.monotonic()
    try:
        yield span
    except Exception as exc:
        close_child_span(span, error_message=exc)
        _current_span.reset(previous)
        raise
    close_child_span(span, output={"duration_ms": int((time.monotonic() - start) * 1000)})
    _current_span.reset(previous)


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
):
    """上报一次模型调用（generation），由 record_model_usage 统一调用。

    自动嵌入 contextvar 指向的当前业务 trace；无 trace 时按 LANGFUSE_ORPHAN_MODE
    处理（skip 默认 / standalone）。任何异常只记 debug 日志。
    """
    client = get_langfuse()
    if not client:
        return
    parent = _current_span.get()
    if parent is None and str(getattr(settings, "LANGFUSE_ORPHAN_MODE", "skip")).lower() != "standalone":
        return
    safe_metadata = _safe_metadata(metadata)
    payload = {
        "name": name or f"llm.{scenario or 'call'}",
        "model": model or None,
        "metadata": safe_metadata,
        "level": "DEFAULT" if success else "ERROR",
    }
    if error_message:
        payload["status_message"] = str(error_message)[:500]
    if total_tokens or prompt_tokens or completion_tokens:
        payload["usage"] = {
            "input": max(int(prompt_tokens or 0), 0),
            "output": max(int(completion_tokens or 0), 0),
            "total": max(int(total_tokens or 0), 0),
            "unit": "TOKENS",
        }
        if cached_tokens:
            payload["usage"]["input_details"] = {"cached": max(int(cached_tokens or 0), 0)}
    try:
        if parent is not None and hasattr(parent, "start_generation"):
            generation = parent.start_generation(**payload)
        else:
            generation = client.start_generation(**payload)
        generation.end()
    except Exception:
        logger.debug("langfuse generation report failed", exc_info=True)


def report_evaluation_run(
    *,
    name: str,
    task_run_id: str,
    metrics: dict | None = None,
    dataset_name: str = "",
    entries: list | None = None,
    metadata: dict | None = None,
):
    """把一次评估运行上报为 Langfuse trace（每次评估一条，指标进 output）。

    LANGFUSE_UPLOAD_EVAL_DATASETS=true 时，同时把题目/参考答案 upsert 成 Langfuse
    Dataset（按名称创建；重复运行会产生重复 item，因此默认关闭）。
    """
    client = get_langfuse()
    if not client:
        return
    trace_metadata = {**(metadata or {}), "task_run_id": task_run_id}
    handle = start_business_trace(name, metadata=trace_metadata)
    if handle is not None:
        close_business_trace(handle, output=metrics or {"status": "completed"})
    if not getattr(settings, "LANGFUSE_UPLOAD_EVAL_DATASETS", False) or not entries:
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
                client.create_dataset_item(
                    dataset_name=dataset_label,
                    input={"question": str((entry or {}).get("question") or "")},
                    expected_output={
                        "answer": str(
                            (entry or {}).get("reference_answer")
                            or (entry or {}).get("ground_truth")
                            or (entry or {}).get("answer")
                            or ""
                        )
                    },
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
    """追踪上下文，贯穿一次完整的 Agent 执行。"""

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
            try:
                ctx.trace_id = getattr(handle, "id", "") or ""
            except Exception:
                pass
    try:
        yield ctx
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        if handle is not None:
            output = {"total_iterations": len(ctx._spans), "duration_ms": duration_ms}
            output.update(_safe_metadata(ctx.metadata))
            close_business_trace(handle, output=output)


@contextmanager
def trace_llm_call(trace_ctx: TraceContext, model: str, messages: list[dict], tools: list = None):
    """追踪一次 LLM 调用（嵌在业务 trace 下的 span）。

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
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        if span is not None:
            close_child_span(span, output={
                "content_length": len(result.get("content") or ""),
                "has_tool_calls": bool(result.get("tool_calls")),
                "error": result.get("error"),
                "duration_ms": duration_ms,
            })
            _current_span.reset(previous)


@contextmanager
def trace_tool_execution(trace_ctx: TraceContext, tool_name: str, args: dict):
    """追踪一次工具执行。"""
    start = time.monotonic()
    parent = _current_span.get()
    span = None
    if parent is not None and trace_ctx is not None and trace_ctx.trace_id:
        span = start_child_span(parent, f"tool.{tool_name}", metadata={
            "args": {key: str(value)[:120] for key, value in (args or {}).items()},
        })
    previous = _current_span.set(span) if span is not None else None
    result = {"output": "", "error": None}
    try:
        yield result
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        if span is not None:
            # 脱敏：只保留前 500 字符或错误信息
            safe_output = result["output"][:500] if not result.get("error") else result["error"]
            close_child_span(span, output={
                "output": safe_output,
                "duration_ms": duration_ms,
                "error": result.get("error"),
            })
            _current_span.reset(previous)
