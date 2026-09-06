"""
Agent ReAct 引擎

参考同类知识库系统的 internal/agent/engine.go，实现 Think → Analyze → Act → Observe 循环。

核心流程：
1. 构建系统 prompt（含工具说明）
2. 循环调用 LLM（带 function calling）
3. 如果 LLM 返回 tool_calls → 执行工具（支持并行） → 结果追加到上下文 → 继续循环
4. 如果 LLM 返回纯文本 → 作为最终回答
5. 达到 max_iterations 或卡死检测 → 强制结束
6. 上下文窗口管理：Consolidator（LLM 摘要）+ CompressContext（滑动窗口）
"""

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from .agent_tools import DEFAULT_ALLOWED_TOOLS, ToolResult, ToolRegistry, get_tool_registry
from .context_manager import estimate_tokens, estimate_messages_tokens, manage_context_window, sort_tools_for_cache, compact_threshold

logger = logging.getLogger(__name__)

MAX_REPEATED_RESPONSES = 2
MAX_TOOL_OUTPUT = 16 * 1024
PARALLEL_TOOL_WORKERS = 4


def _tool_result_meta(result: "ToolResult | None") -> dict:
    """工具结果的结构化摘要（仅元数据，不含文档原文），供轨迹结果卡片展示。"""
    if result is None:
        return {}
    meta: dict = {}
    refs = result.references or []
    if refs:
        meta["count"] = len(refs)
        chunk_ids = [str(r.get("chunk_id") or r.get("id") or "") for r in refs if isinstance(r, dict)]
        meta["chunk_ids"] = [cid for cid in chunk_ids if cid][:8]
    if result.error:
        meta["is_error"] = True
        # 结构化错误分类（error_type/retryable/failed_fields）进轨迹，调试时可见失败性质
        meta.update(result.error_meta())
    return meta


def _light_tool_schemas(tools: list[dict]) -> list[dict]:
    """把 OpenAI 工具定义压缩为轨迹可存的轻量契约快照。

    保留 name、截断后的 description、参数的名称/类型/必填集合——足以在轨迹中
    还原"调用时刻工具长什么样"，又不至于把完整的 prompt 级描述写进每轮事件。
    """
    light = []
    for tool in tools or []:
        fn = tool.get("function") or {}
        params = fn.get("parameters") or {}
        props = params.get("properties") or {}
        light.append({
            "name": fn.get("name", ""),
            "description": str(fn.get("description", ""))[:400],
            "required": list(params.get("required") or []),
            "properties": {str(k): str((v or {}).get("type", "any")) for k, v in props.items()},
        })
    return light


# ── 数据结构 ─────────────────────────────────────────────────────────
@dataclass
class ToolCallRecord:
    id: str
    name: str
    arguments: dict
    result: ToolResult | None = None

    def to_dict(self) -> dict:
        d = {"id": self.id, "name": self.name, "arguments": self.arguments}
        if self.result:
            d["result"] = self.result.to_dict()
        return d


@dataclass
class AgentStep:
    iteration: int
    thought: str = ""
    # 思考模型返回的推理文本（reasoning_content）；非思考模型为空。
    # 与 thought（可见文本）分开保存：thought 在最终轮是回答正文本身
    reasoning: str = ""
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        d = {"iteration": self.iteration, "thought": self.thought}
        if self.reasoning:
            d["reasoning"] = self.reasoning
        if self.tool_calls:
            d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        d["timestamp"] = self.timestamp
        return d


@dataclass
class AgentResult:
    content: str
    steps: list[AgentStep]
    total_iterations: int
    duration_ms: int
    stopped_reason: str = "completed"
    # 工具链检索到的结构化引用，最终回填到 assistant 消息的 knowledge_references
    references: list = field(default_factory=list)
    # 本次执行的 Langfuse trace id，随 turn/completed 事件落轨迹，实现轨迹↔Langfuse 互查
    trace_id: str = ""

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "steps": [s.to_dict() for s in self.steps],
            "total_iterations": self.total_iterations,
            "duration_ms": self.duration_ms,
            "stopped_reason": self.stopped_reason,
        }


def _collect_tool_references(record: "ToolCallRecord", bucket: list) -> None:
    """从工具结果的 references 字段收集引用，按 chunk id 去重。"""
    result = record.result
    refs = getattr(result, "references", None) if result else None
    if not refs:
        return
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        key = ref.get("chunk_id") or ref.get("id")
        if key and any((r.get("chunk_id") or r.get("id")) == key for r in bucket):
            continue
        bucket.append(ref)


# ── 优雅降级：从工具结果综合答案 ────────────────────────────────────
# 参考同类知识库系统的 finalize.go：LLM 失败但有工具结果时综合生成

def _synthesize_from_tool_results(steps: list, query: str) -> str:
    """
    从工具结果中综合答案。
    当 LLM 调用失败但已有工具结果时使用。
    """
    # 收集所有工具结果
    tool_outputs = []
    for step in steps:
        for tc in step.tool_calls:
            if tc.result and tc.result.output:
                tool_outputs.append(f"[{tc.name}] {tc.result.output[:500]}")

    if not tool_outputs:
        return "抱歉，无法生成回答。请稍后重试。"

    # 构建简单的综合答案
    context = "\n\n".join(tool_outputs[:5])  # 最多取 5 个结果
    return f"根据检索到的信息：\n\n{context}\n\n以上是与您的问题相关的内容。"


# ── 系统 Prompt 模板 ─────────────────────────────────────────────────
# 设计原则：共享不可变前缀，兼容 DeepSeek V4 自动前缀缓存
# 静态前缀（所有 Agent 共享，可缓存）+ 动态上下文（每个会话不同）
# 共享层只放"对所有角色都为真"的内容（身份/回答要求/工具使用原则）；
# 角色相关的检索策略放在各自的岗位说明（custom_prompt）里，避免
# "Wiki 优先"这类策略与主 Agent 调度规则、子 Agent 角色约束冲突。

SYSTEM_PROMPT_STATIC_PREFIX = """你是一个知识库问答助手，能够使用工具来帮助回答问题。

## 回答要求
- 使用与用户问题一致的语言回答（默认中文）
- **结构化**：使用标题、列表、表格组织信息
- **有深度**：不仅列出内容，还要分析关系、对比、演进
- **有引用**：引用具体文档标题和 Wiki 页面
- **有综合**：将多个来源的信息整合成连贯的分析
- **诚实**：检索不到相关内容时，如实说明并建议用户调整问题，不要编造

## 工具使用原则
- **并行调用**：同一轮内多个独立、无依赖的检索可以同时发起
- **合并模式**：关键词检索支持用 `|` 合并多个模式，一次调用完成，不要拆成多次
- **深度阅读**：搜索到结果后，必须读取完整内容再回答，不要仅凭摘要作答
- **见好就收**：已有足够信息就直接回答；检索不到就如实说明，不要反复空搜
- **按能力行动**：只使用工具清单中实际提供的工具，不要尝试清单之外的操作"""

SYSTEM_PROMPT_WITH_TOOLS = SYSTEM_PROMPT_STATIC_PREFIX + """

## 可用工具
{tools_desc}

{custom_prompt}"""

SYSTEM_PROMPT_NO_TOOLS = """你是一个知识库问答助手。请根据提供的知识库上下文回答用户问题。
- 优先使用上下文中的信息回答
- 引用具体来源时注明文档标题
- 如果上下文中没有相关信息，如实说明

{custom_prompt}"""


# ── ReAct 引擎 ───────────────────────────────────────────────────────
class AgentEngine:
    def __init__(
        self,
        tenant,
        session_id: str,
        user_id: str = "",
        agent_config: dict | None = None,
    ):
        self.tenant = tenant
        self.session_id = session_id
        self.user_id = user_id
        self.config = agent_config or {}
        self.registry = get_tool_registry()

        self.max_iterations = self.config.get("max_rounds", 20)  # 默认 20 轮，参考同类知识库系统
        self.temperature = self.config.get("temperature", 0.7)
        self.custom_system_prompt = self.config.get("system_prompt", "")
        self.allowed_tools = self.config.get("allowed_tools", DEFAULT_ALLOWED_TOOLS)
        if not self.config.get("allow_actor_tool", True):
            self.allowed_tools = [tool for tool in self.allowed_tools if tool != "actor"]
        self.model_id = self.config.get("model_id", "")
        # 上下文窗口解析：显式配置 > 按模型解析（ModelConfig 覆盖 → 全局默认）。
        # 参考 deepseek-harness 的三级 fallback；压缩阈值 = 窗口 - 预留。
        if self.config.get("context_window"):
            self.context_window = int(self.config["context_window"])
        else:
            from .model_providers import resolve_model_context_window

            self.context_window = resolve_model_context_window(self.tenant, self.model_id)
        self.parallel_tools = self.config.get("parallel_tool_calls", True)
        self.actor_id = self.config.get("actor_id", "main")
        self.parent_message_id = self.config.get("parent_message_id", "")
        self.cancel_check = self.config.get("cancel_check")

    def _build_system_prompt(self) -> str:
        tools = self.registry.to_openai_tools(self.allowed_tools)
        if not tools:
            return SYSTEM_PROMPT_NO_TOOLS.format(custom_prompt=self.custom_system_prompt)

        tools_desc_lines = []
        for t in tools:
            fn = t["function"]
            tools_desc_lines.append(f"- **{fn['name']}**: {fn['description']}")
        tools_desc = "\n".join(tools_desc_lines)

        return SYSTEM_PROMPT_WITH_TOOLS.format(
            tools_desc=tools_desc,
            custom_prompt=self.custom_system_prompt,
        )

    def _build_context(self) -> dict:
        from .models import KnowledgeBase
        kb_ids = self.config.get("knowledge_base_ids", [])
        if not kb_ids:
            # 参考同类知识库系统：过滤系统内部知识库（is_temporary=True），避免 __chat_history__ 暴露给用户
            kb_ids = list(KnowledgeBase.objects.filter(tenant=self.tenant, deleted_at__isnull=True, is_temporary=False).values_list("id", flat=True))
        return {
            "tenant": self.tenant,
            "tenant_id": self.tenant.id,
            "kb_ids": kb_ids,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "actor_id": self.actor_id,
            "parent_message_id": self.parent_message_id,
            "allow_actor_tool": bool(self.config.get("allow_actor_tool", True)),
            "model_id": self.model_id,
        }

    def _call_llm_with_tools(self, messages: list[dict], max_retries: int = 3) -> dict:
        """
        调用 LLM，支持重试。
        参考同类知识库系统的 callLLMWithRetry：对瞬态错误（timeout、rate limit、server error）进行重试。
        工具定义按字母排序，确保字节级稳定性（兼容 DeepSeek V4 自动前缀缓存）。
        """
        from .model_providers import chat_completion_raw
        tools = sort_tools_for_cache(self.registry.to_openai_tools(self.allowed_tools))

        last_error = None
        for attempt in range(max_retries):
            try:
                return chat_completion_raw(self.tenant, messages, model_id=self.model_id, tools=tools if tools else None, temperature=self.temperature)
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                # 只对瞬态错误重试
                is_transient = any(keyword in error_str for keyword in [
                    "timeout", "timed out", "rate limit", "429", "500", "502", "503", "504",
                    "connection", "reset", "broken pipe",
                ])
                if is_transient and attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2  # 递增等待：2s, 4s
                    logger.warning(f"Agent LLM call failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {e}")
                    emit = getattr(self, "_event_emit", None)
                    if callable(emit):
                        try:
                            from . import event_log as _event_log
                            emit(_event_log.LLM_RETRY, {
                                "attempt": attempt + 1,
                                "max_retries": max_retries,
                                "reason": str(e)[:200],
                                "wait_seconds": wait_time,
                                "stage": "llm_transient",
                                "model": self.model_id or "",
                                **getattr(self, "_trace_fields", {}),
                            })
                        except Exception:
                            pass
                    time.sleep(wait_time)
                else:
                    raise
        raise last_error

    def _call_llm_simple(self, messages: list[dict]) -> str:
        from .model_providers import chat_completion
        return chat_completion(self.tenant, messages, model_id=self.model_id)

    def _execute_single_tool(self, tc: dict, context: dict) -> tuple[str, ToolCallRecord]:
        """执行单个工具调用。"""
        tc_id = tc.get("id", "")
        fn = tc.get("function", {})
        tool_name = fn.get("name", "")
        raw_args = fn.get("arguments", "{}")

        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError:
            args = {}

        tool_result = self.registry.execute_tool(tool_name, args, context)
        record = ToolCallRecord(id=tc_id, name=tool_name, arguments=args, result=tool_result)
        return tc_id, record

    def execute(
        self,
        query: str,
        history: list[dict] | None = None,
        context_str: str = "",
        on_event: callable = None,
        request_id: str = "",
    ) -> AgentResult:
        from .observability import trace_agent_execution, trace_llm_call, trace_tool_execution
        from .agent_tools import clear_seen_cache

        # 清除已见内容缓存（每次 Agent 执行开始时）
        clear_seen_cache()

        start_time = time.monotonic()
        steps: list[AgentStep] = []
        context = self._build_context()
        system_prompt = self._build_system_prompt()

        # 轨迹事件：惰性解析会话对象，解析失败则整个事件链静默关闭
        from .models import Session as _Session
        from . import event_log as _event_log
        event_session = None
        if request_id:
            try:
                event_session = _Session.objects.filter(pk=self.session_id).first()
            except Exception:
                event_session = None

        # LLM 调用归属上下文：record_model_usage 据此发射 llm/call 轨迹事件并归档 request_id。
        # 主 Agent 归组键为空串；子代理（actor_id 非 main）的事件在 fold 里按 actor 分组。
        from .observability import set_llm_call_context as _set_call_ctx, reset_llm_call_context as _reset_call_ctx
        _agent_type = self.config.get("agent_mode", "")
        if _agent_type.startswith("subagent:"):
            _agent_type = _agent_type.split(":", 1)[1]
        _ctx_actor_id = self.actor_id if self.actor_id and self.actor_id != "main" else ""

        from contextlib import contextmanager as _cm

        @_cm
        def _call_ctx_scope():
            token = _set_call_ctx(
                session_id=self.session_id,
                request_id=request_id,
                actor_id=_ctx_actor_id,
                agent_type=_agent_type,
            )
            try:
                yield
            finally:
                _reset_call_ctx(token)

        # 每轮迭代更新归属上下文的 iteration，llm/call 事件据此对齐轨迹步骤
        def _mark_iteration(it: int):
            from .observability import update_llm_call_context
            update_llm_call_context(iteration=it)

        def _emit(event_type: str, data: dict):
            if event_session is None:
                return
            try:
                _event_log.append_event(event_session, request_id, event_type, data)
            except Exception:
                pass

        # 供 _call_llm_with_tools 等方法发射重试等事件；未开启轨迹时为 no-op
        self._event_emit = _emit
        self._trace_fields = {"actor_id": _ctx_actor_id, "agent_type": _agent_type}
        _emit(_event_log.REQUEST_HEADER, {
            "model": self.model_id or "",
            "temperature": self.temperature,
            "allowed_tools": list(self.allowed_tools or []),
            # 调用时刻的工具契约快照（轻量）：名称 + 截断描述 + 参数名与类型
            "tool_schemas": _light_tool_schemas(self.registry.to_openai_tools(self.allowed_tools)),
            "max_iterations": self.max_iterations,
            "history_messages": len(history or []),
            "agent_mode": self.config.get("agent_mode", ""),
            "actor_id": _ctx_actor_id,
            "agent_type": _agent_type,
        })

        if context_str:
            user_content = f"{context_str}\n\n<user_question>\n{query}\n</user_question>"
        else:
            user_content = query

        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_content})

        tools_available = bool(self.registry.to_openai_tools(self.allowed_tools))
        last_contents: list[str] = []
        final_content = ""
        collected_refs: list = []
        _trace_id = {"id": ""}

        # 顶层 Agent 追踪；调用上下文作用域与 trace 同生命周期（退出时确定性 reset）
        with _call_ctx_scope(), trace_agent_execution(
            session_id=self.session_id,
            user_id=self.user_id,
            query=query[:2000],
            agent_mode=self.config.get("agent_mode", ""),
        ) as agent_trace:
            # 兼容测试用 SimpleNamespace 替身：无 trace_id 属性时静默降级
            _trace_id["id"] = getattr(agent_trace, "trace_id", "") or ""
            agent_trace.metadata["tenant_id"] = self.tenant.id
            agent_trace.metadata["max_iterations"] = self.max_iterations
            agent_trace.metadata["allowed_tools"] = self.allowed_tools

            for iteration in range(1, self.max_iterations + 1):
                _mark_iteration(iteration)
                if callable(self.cancel_check) and self.cancel_check():
                    return AgentResult(
                        content=final_content or "生成已取消。",
                        steps=steps,
                        total_iterations=iteration - 1,
                        duration_ms=int((time.monotonic() - start_time) * 1000),
                        stopped_reason="cancelled",
                        references=collected_refs,
                        trace_id=_trace_id["id"],
                    )
                step = AgentStep(iteration=iteration, timestamp=time.time())
                _emit(_event_log.AGENT_ITERATION, {
                    "iteration": iteration,
                    "model": self.model_id or "",
                    "actor_id": _ctx_actor_id,
                    "agent_type": _agent_type,
                })

                # 上下文窗口管理（参考同类知识库系统的 manageContextWindow）
                # 1. 脱敏历史 KB 结果
                # 2. Consolidator（LLM 摘要压缩，token > 50% 时触发）
                # 3. 滑动窗口截断（token > 80% 时触发）
                try:
                    from .context_manager import estimate_messages_tokens as _est_tokens
                    _tokens_before = _est_tokens(messages)
                except Exception:
                    _tokens_before = 0
                messages = manage_context_window(
                    messages,
                    max_tokens=compact_threshold(self.context_window),
                    llm_caller=self._call_llm_simple if iteration > 1 else None,
                    enable_redact=True,
                )
                try:
                    _tokens_after = _est_tokens(messages)
                except Exception:
                    _tokens_after = _tokens_before
                if _tokens_before and _tokens_after < _tokens_before:
                    _emit(_event_log.CONTEXT_COMPACTED, {
                        "before_tokens": _tokens_before,
                        "after_tokens": _tokens_after,
                        "iteration": iteration,
                        "trigger": "context_window",
                        "actor_id": _ctx_actor_id,
                        "agent_type": _agent_type,
                    })

                try:
                    # 每轮 LLM 调用追踪
                    llm_started = time.monotonic()
                    with trace_llm_call(agent_trace, model=self.model_id or "default", messages=messages, tools=self.registry.to_openai_tools(self.allowed_tools) if tools_available else None) as llm_span:
                        if tools_available:
                            llm_response = self._call_llm_with_tools(messages)
                            content = llm_response.get("content", "") or ""
                            tool_calls = llm_response.get("tool_calls")
                            llm_span["content"] = content
                            llm_span["tool_calls"] = tool_calls
                        else:
                            content = self._call_llm_simple(messages)
                            tool_calls = None
                            llm_span["content"] = content
                    if tools_available:
                        llm_usage = llm_response.get("usage") or {}
                    else:
                        llm_usage = {}
                    llm_duration_ms = int((time.monotonic() - llm_started) * 1000)
                except Exception as e:
                    logger.exception(f"Agent LLM call failed at iteration {iteration}")
                    _emit(_event_log.TURN_ERROR, {"message": f"LLM call failed at iteration {iteration}: {e}", "stage": "llm"})
                    # 优雅降级：如果有工具结果，尝试综合答案
                    # 参考同类知识库系统的 finalize.go：LLM 失败但有工具结果时综合生成
                    if steps and any(step.tool_calls for step in steps):
                        final_content = _synthesize_from_tool_results(steps, query)
                        logger.info(f"[Agent] Graceful degradation: synthesized answer from {len(steps)} steps")
                        return AgentResult(content=final_content, steps=steps, total_iterations=iteration - 1, duration_ms=int((time.monotonic() - start_time) * 1000), stopped_reason="degraded", references=collected_refs, trace_id=_trace_id["id"])
                    final_content = final_content or f"抱歉，处理过程中出现错误：{str(e)}"
                    return AgentResult(content=final_content, steps=steps, total_iterations=iteration - 1, duration_ms=int((time.monotonic() - start_time) * 1000), stopped_reason="error", references=collected_refs, trace_id=_trace_id["id"])

                step.thought = content
                step.reasoning = llm_response.get("reasoning_content", "") or ""
                # 每次迭代的 LLM 调用都发 thinking 事件（含空内容迭代）：
                # 中间迭代模型常只返回 tool_calls、文本为空，漏发会丢失该次的
                # 用量/时长/时间戳，轨迹里表现为步骤与时间轴缺段、token 少计。
                if on_event:
                    on_event("thinking", {
                        "iteration": iteration,
                        "content": content,
                        "reasoning_content": step.reasoning,
                        "duration_ms": llm_duration_ms,
                        "provider": (llm_response.get("provider") or "") if tools_available else "",
                        "model": ((llm_response.get("model") or "") or self.model_id or "") if tools_available else (self.model_id or ""),
                        "usage": llm_usage,
                        "finish_reason": (llm_response.get("finish_reason") or "") if tools_available else "",
                        "degradation": (llm_response.get("degradation_info") or {}) if tools_available else {},
                        "actor_id": _ctx_actor_id,
                        "agent_type": _agent_type,
                    })

                # ── 无工具调用 → 最终回答 ─────────────────────────────
                if not tool_calls:
                    # 空内容重试（参考同类知识库系统的 emptyContent 检测）
                    if not content.strip() and iteration < self.max_iterations:
                        logger.warning(f"[Agent] Empty content at iteration {iteration}, retrying with nudge")
                        _emit(_event_log.LLM_RETRY, {
                            "attempt": iteration,
                            "reason": "empty content, nudged with '请提供你的完整回答。'",
                            "wait_seconds": 0,
                            "stage": "empty_response",
                            "actor_id": _ctx_actor_id,
                            "agent_type": _agent_type,
                        })
                        messages.append({"role": "user", "content": "请提供你的完整回答。"})
                        continue

                    final_content = content
                    steps.append(step)
                    last_contents.append(content.strip())
                    if len(last_contents) >= MAX_REPEATED_RESPONSES and len(set(last_contents[-MAX_REPEATED_RESPONSES:])) == 1:
                        return AgentResult(content=final_content, steps=steps, total_iterations=iteration, duration_ms=int((time.monotonic() - start_time) * 1000), stopped_reason="stuck", references=collected_refs, trace_id=_trace_id["id"])
                    return AgentResult(content=final_content, steps=steps, total_iterations=iteration, duration_ms=int((time.monotonic() - start_time) * 1000), stopped_reason="completed", references=collected_refs, trace_id=_trace_id["id"])

                # ── 有工具调用 → 执行工具（支持并行）─────────────────
                assistant_msg = {"role": "assistant", "content": content, "tool_calls": tool_calls}
                messages.append(assistant_msg)

                if self.parallel_tools and len(tool_calls) > 1:
                    # 并行执行
                    tool_results = {}
                    with ThreadPoolExecutor(max_workers=PARALLEL_TOOL_WORKERS) as executor:
                        futures = {executor.submit(self._execute_single_tool, tc, context): tc for tc in tool_calls}
                        for future in as_completed(futures):
                            try:
                                tc_id, record = future.result()
                                tool_results[tc_id] = record
                            except Exception as exc:
                                logger.exception("Parallel tool execution failed")

                    for tc in tool_calls:
                        tc_id = tc.get("id", "")
                        record = tool_results.get(tc_id)
                        if record:
                            step.tool_calls.append(record)
                            _collect_tool_references(record, collected_refs)
                            if on_event:
                                on_event("tool_call", {"iteration": iteration, "name": record.name, "arguments": record.arguments, "tool_call_id": tc_id, "actor_id": _ctx_actor_id, "agent_type": _agent_type})
                                on_event("tool_result", {"iteration": iteration, "name": record.name, "output": record.result.output if record.result else "", "error": record.result.error if record.result else "", "duration_ms": record.result.duration_ms if record.result else 0, "tool_call_id": tc_id, "meta": _tool_result_meta(record.result), "actor_id": _ctx_actor_id, "agent_type": _agent_type})
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "name": record.name,
                                # 失败时回传结构化错误（error_type/retryable）+ 差异化修正指引，
                                # 让模型修正调用而非机械重试同一请求
                                "content": (record.result.output[:MAX_TOOL_OUTPUT] if not record.result.error else record.result.model_error_text()) if record.result else "Error: No result",
                            })
                else:
                    # 顺序执行
                    for tc in tool_calls:
                        tc_id = tc.get("id", "")
                        fn = tc.get("function", {})
                        tool_name = fn.get("name", "")
                        raw_args = fn.get("arguments", "{}")

                        try:
                            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                        except json.JSONDecodeError:
                            args = {}

                        if on_event:
                            on_event("tool_call", {"iteration": iteration, "name": tool_name, "arguments": args, "tool_call_id": tc_id, "actor_id": _ctx_actor_id, "agent_type": _agent_type})

                        tool_result = self.registry.execute_tool(tool_name, args, context)
                        record = ToolCallRecord(id=tc_id, name=tool_name, arguments=args, result=tool_result)
                        step.tool_calls.append(record)
                        _collect_tool_references(record, collected_refs)

                        if on_event:
                            on_event("tool_result", {"iteration": iteration, "name": tool_name, "output": tool_result.output, "error": tool_result.error, "duration_ms": tool_result.duration_ms, "tool_call_id": tc_id, "meta": _tool_result_meta(tool_result), "actor_id": _ctx_actor_id, "agent_type": _agent_type})

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "name": tool_name,
                            "content": tool_result.output[:MAX_TOOL_OUTPUT] if not tool_result.error else tool_result.model_error_text(),
                        })

                steps.append(step)

        # 达到最大迭代次数
        return AgentResult(content=final_content or "已达到最大推理轮数，基于当前信息给出回答。", steps=steps, total_iterations=self.max_iterations, duration_ms=int((time.monotonic() - start_time) * 1000), stopped_reason="max_iterations", references=collected_refs, trace_id=_trace_id["id"])
