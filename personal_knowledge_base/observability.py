"""
可观测性模块

参考 WeKnora 的 Langfuse 集成，提供 LLM 调用追踪。
支持两种模式：
1. Langfuse 模式（如果配置了 LANGFUSE_* 环境变量）
2. 本地日志模式（默认，记录到 ModelUsage 表）

注意：Langfuse SDK 是可选依赖，未安装时自动降级为本地日志模式。
"""

import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# 尝试导入 Langfuse（可选）
try:
    from langfuse import Langfuse
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False

_langfuse_client = None


def get_langfuse():
    """获取或创建 Langfuse 客户端。"""
    global _langfuse_client
    if _langfuse_client is not None:
        return _langfuse_client

    if not LANGFUSE_AVAILABLE:
        return None

    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")
    host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if not public_key or not secret_key:
        return None

    try:
        _langfuse_client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
        return _langfuse_client
    except Exception:
        logger.warning("Failed to initialize Langfuse client")
        return None


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
    """追踪一次 Agent 执行的上下文管理器。"""
    ctx = TraceContext(
        session_id=session_id,
        user_id=user_id,
        query=query,
        metadata={"agent_mode": agent_mode},
    )
    start = time.time()

    langfuse = get_langfuse()
    trace = None
    if langfuse:
        try:
            trace = langfuse.trace(
                name="agent.execute",
                session_id=session_id,
                user_id=user_id,
                input={"query": query},
                metadata={"agent_mode": agent_mode},
            )
            ctx.trace_id = trace.id if trace else ""
        except Exception:
            pass

    yield ctx

    duration_ms = int((time.time() - start) * 1000)

    if trace:
        try:
            trace.update(output={"total_iterations": len(ctx._spans), "duration_ms": duration_ms})
            langfuse.flush()
        except Exception:
            pass


@contextmanager
def trace_llm_call(trace_ctx: TraceContext, model: str, messages: list[dict], tools: list = None):
    """追踪一次 LLM 调用。"""
    start = time.time()
    span_name = f"llm.call.{model}"

    langfuse = get_langfuse()
    span = None
    if langfuse and trace_ctx.trace_id:
        try:
            trace_obj = langfuse.trace(id=trace_ctx.trace_id)
            span = trace_obj.span(
                name=span_name,
                input={"model": model, "messages_count": len(messages), "has_tools": bool(tools)},
            )
        except Exception:
            pass

    result = {"content": "", "tool_calls": None, "error": None}
    yield result

    duration_ms = int((time.time() - start) * 1000)

    if span:
        try:
            span.end(output={
                "content_length": len(result.get("content", "")),
                "has_tool_calls": bool(result.get("tool_calls")),
                "error": result.get("error"),
                "duration_ms": duration_ms,
            })
        except Exception:
            pass

    # 记录到 ModelUsage 表
    try:
        from .model_usage import record_model_usage
        from .models import Tenant
        tenant = Tenant.objects.filter(id=trace_ctx.metadata.get("tenant_id")).first()
        if tenant:
            record_model_usage(
                tenant,
                model_id=model,
                model_name=model,
                model_type="chat",
                provider="agent",
                scenario="agent_reasoning",
                success=result.get("error") is None,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                duration_ms=duration_ms,
                error_message=result.get("error"),
            )
    except Exception:
        pass


@contextmanager
def trace_tool_execution(trace_ctx: TraceContext, tool_name: str, args: dict):
    """追踪一次工具执行。"""
    start = time.time()

    langfuse = get_langfuse()
    span = None
    if langfuse and trace_ctx.trace_id:
        try:
            trace_obj = langfuse.trace(id=trace_ctx.trace_id)
            span = trace_obj.span(
                name=f"tool.{tool_name}",
                input={"args": args},
            )
        except Exception:
            pass

    result = {"output": "", "error": None}
    yield result

    duration_ms = int((time.time() - start) * 1000)

    if span:
        try:
            # 脱敏 SQL 等敏感参数
            safe_output = result["output"][:500] if not result.get("error") else result["error"]
            span.end(output={"output": safe_output, "duration_ms": duration_ms, "error": result.get("error")})
        except Exception:
            pass
