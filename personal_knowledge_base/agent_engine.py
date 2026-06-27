"""
Agent ReAct 引擎

参考 WeKnora 的 internal/agent/engine.go，实现 Think → Analyze → Act → Observe 循环。

核心流程：
1. 构建系统 prompt（含工具说明）
2. 循环调用 LLM（带 function calling）
3. 如果 LLM 返回 tool_calls → 执行工具（支持并行） → 结果追加到上下文 → 继续循环
4. 如果 LLM 返回纯文本 → 作为最终回答
5. 达到 max_iterations 或卡死检测 → 强制结束
6. 上下文窗口管理：token 估算 + 历史压缩
"""

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from .agent_tools import DEFAULT_ALLOWED_TOOLS, ToolResult, ToolRegistry, get_tool_registry

logger = logging.getLogger(__name__)

MAX_REPEATED_RESPONSES = 2
MAX_CONTEXT_TOKENS = 120000  # 约 120K tokens 上限
MAX_TOOL_OUTPUT = 16 * 1024
PARALLEL_TOOL_WORKERS = 4


# ── Token 估算 ───────────────────────────────────────────────────────
def estimate_tokens(text: str) -> int:
    """简易 token 估算：中文约 1.5 字/token，英文约 4 字符/token。"""
    if not text:
        return 0
    chinese_chars = len(re.findall(r'[一-鿿]', text))
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)


def estimate_messages_tokens(messages: list[dict]) -> int:
    """估算消息列表的 token 数。"""
    total = 0
    for msg in messages:
        total += 4  # role 开销
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        # tool_calls 也计入
        for tc in msg.get("tool_calls", []):
            total += estimate_tokens(json.dumps(tc, ensure_ascii=False))
    return total


# ── 上下文压缩 ───────────────────────────────────────────────────────
def compress_context(messages: list[dict], max_tokens: int = MAX_CONTEXT_TOKENS) -> list[dict]:
    """
    压缩消息列表以适应上下文窗口。
    策略：保留 system prompt + 最近的消息，删除最早的工具消息组。
    """
    current_tokens = estimate_messages_tokens(messages)
    if current_tokens <= max_tokens:
        return messages

    # 始终保留：system prompt（第 1 条）+ 最后 2 条（当前轮）
    system = messages[0] if messages and messages[0].get("role") == "system" else None
    tail = messages[-2:] if len(messages) > 2 else messages[1:]
    middle = messages[1:-2] if len(messages) > 2 else []

    # 从中间部分的前面开始删除（每组：assistant + tool 结果）
    while current_tokens > max_tokens and len(middle) > 2:
        # 删除最前面的一组（assistant + tool messages）
        removed = 0
        while middle and removed < 2:
            removed_msg = middle.pop(0)
            removed += estimate_tokens(json.dumps(removed_msg, ensure_ascii=False))
        current_tokens -= removed

    # 重新组装
    result = []
    if system:
        result.append(system)
    result.extend(middle)
    result.extend(tail)
    return result


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
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        d = {"iteration": self.iteration, "thought": self.thought}
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

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "steps": [s.to_dict() for s in self.steps],
            "total_iterations": self.total_iterations,
            "duration_ms": self.duration_ms,
            "stopped_reason": self.stopped_reason,
        }


# ── 系统 Prompt 模板 ─────────────────────────────────────────────────
SYSTEM_PROMPT_WITH_TOOLS = """你是一个知识库问答助手，能够使用工具来帮助回答问题。

## 可用工具
{tools_desc}

## 回答策略
1. 先理解用户问题，判断是否需要检索知识库
2. 如果需要检索，使用 knowledge_search 工具搜索相关内容
3. 如果需要查看具体文档，使用 get_document_info 或 list_knowledge_docs
4. 如果需要在已检索内容中查找特定信息，使用 grep_chunks
5. 对于复杂问题，使用 thinking 工具进行推理
6. 基于检索到的信息给出准确、有组织的回答

## 重要规则
- 优先使用知识库中的信息回答
- 引用具体来源时注明文档标题
- 如果知识库中没有相关信息，如实说明
- 不要编造信息
- 可以同时调用多个工具（并行执行）

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

        self.max_iterations = self.config.get("max_rounds", 5)
        self.temperature = self.config.get("temperature", 0.7)
        self.custom_system_prompt = self.config.get("system_prompt", "")
        self.allowed_tools = self.config.get("allowed_tools", DEFAULT_ALLOWED_TOOLS)
        self.model_id = self.config.get("model_id", "")
        self.parallel_tools = self.config.get("parallel_tool_calls", True)

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
            kb_ids = list(KnowledgeBase.objects.filter(tenant=self.tenant).values_list("id", flat=True))
        return {"tenant_id": self.tenant.id, "kb_ids": kb_ids, "session_id": self.session_id, "user_id": self.user_id}

    def _call_llm_with_tools(self, messages: list[dict]) -> dict:
        from .model_providers import chat_completion_raw
        tools = self.registry.to_openai_tools(self.allowed_tools)
        return chat_completion_raw(self.tenant, messages, model_id=self.model_id, tools=tools if tools else None, temperature=self.temperature)

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
    ) -> AgentResult:
        from .observability import trace_agent_execution, trace_llm_call, trace_tool_execution

        start_time = time.monotonic()
        steps: list[AgentStep] = []
        context = self._build_context()
        system_prompt = self._build_system_prompt()

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

        # 顶层 Agent 追踪
        with trace_agent_execution(
            session_id=self.session_id,
            user_id=self.user_id,
            query=query[:2000],
            agent_mode=self.config.get("agent_mode", ""),
        ) as agent_trace:
            agent_trace.metadata["tenant_id"] = self.tenant.id
            agent_trace.metadata["max_iterations"] = self.max_iterations
            agent_trace.metadata["allowed_tools"] = self.allowed_tools

            for iteration in range(1, self.max_iterations + 1):
                step = AgentStep(iteration=iteration, timestamp=time.time())

                # 上下文窗口管理
                messages = compress_context(messages, MAX_CONTEXT_TOKENS)

                try:
                    # 每轮 LLM 调用追踪
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
                except Exception as e:
                    logger.exception(f"Agent LLM call failed at iteration {iteration}")
                    llm_span["error"] = str(e)
                    final_content = final_content or f"抱歉，处理过程中出现错误：{str(e)}"
                    return AgentResult(content=final_content, steps=steps, total_iterations=iteration - 1, duration_ms=int((time.monotonic() - start_time) * 1000), stopped_reason="error")

            step.thought = content
            if on_event and content:
                on_event("thinking", {"iteration": iteration, "content": content})

            # ── 无工具调用 → 最终回答 ─────────────────────────────
            if not tool_calls:
                final_content = content
                steps.append(step)
                last_contents.append(content.strip())
                if len(last_contents) >= MAX_REPEATED_RESPONSES and len(set(last_contents[-MAX_REPEATED_RESPONSES:])) == 1:
                    return AgentResult(content=final_content, steps=steps, total_iterations=iteration, duration_ms=int((time.monotonic() - start_time) * 1000), stopped_reason="stuck")
                return AgentResult(content=final_content, steps=steps, total_iterations=iteration, duration_ms=int((time.monotonic() - start_time) * 1000), stopped_reason="completed")

            # ── 有工具调用 → 执行工具（支持并行）─────────────────
            assistant_msg = {"role": "assistant", "content": content, "tool_calls": tool_calls}
            messages.append(assistant_msg)

            if self.parallel_tools and len(tool_calls) > 1:
                # 并行执行
                tool_results = {}
                with ThreadPoolExecutor(max_workers=PARALLEL_TOOL_WORKERS) as executor:
                    futures = {executor.submit(self._execute_single_tool, tc, context): tc for tc in tool_calls}
                    for future in as_completed(futures):
                        tc_id, record = future.result()
                        tool_results[tc_id] = record

                for tc in tool_calls:
                    tc_id = tc.get("id", "")
                    record = tool_results.get(tc_id)
                    if record:
                        step.tool_calls.append(record)
                        # 工具追踪
                        with trace_tool_execution(agent_trace, record.name, record.arguments) as tool_span:
                            tool_span["output"] = record.result.output[:4000] if record.result else ""
                            tool_span["error"] = record.result.error if record.result else ""
                            tool_span["duration_ms"] = record.result.duration_ms if record.result else 0
                        if on_event:
                            on_event("tool_call", {"iteration": iteration, "name": record.name, "arguments": record.arguments})
                            on_event("tool_result", {"iteration": iteration, "name": record.name, "output": record.result.output[:500] if record.result else "", "error": record.result.error if record.result else "", "duration_ms": record.result.duration_ms if record.result else 0})
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": (record.result.output[:MAX_TOOL_OUTPUT] if not record.result.error else f"Error: {record.result.error}") if record.result else "Error: No result",
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
                        on_event("tool_call", {"iteration": iteration, "name": tool_name, "arguments": args})

                    # 工具追踪
                    with trace_tool_execution(agent_trace, tool_name, args) as tool_span:
                        tool_result = self.registry.execute_tool(tool_name, args, context)
                        tool_span["output"] = tool_result.output[:4000]
                        tool_span["error"] = tool_result.error
                        tool_span["duration_ms"] = tool_result.duration_ms

                    record = ToolCallRecord(id=tc_id, name=tool_name, arguments=args, result=tool_result)
                    step.tool_calls.append(record)

                    if on_event:
                        on_event("tool_result", {"iteration": iteration, "name": tool_name, "output": tool_result.output[:500], "error": tool_result.error, "duration_ms": tool_result.duration_ms})

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": tool_result.output[:MAX_TOOL_OUTPUT] if not tool_result.error else f"Error: {tool_result.error}",
                    })

            steps.append(step)

        # 达到最大迭代次数
        return AgentResult(content=final_content or "已达到最大推理轮数，基于当前信息给出回答。", steps=steps, total_iterations=self.max_iterations, duration_ms=int((time.monotonic() - start_time) * 1000), stopped_reason="max_iterations")
