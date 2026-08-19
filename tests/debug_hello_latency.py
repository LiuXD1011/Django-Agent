#!/usr/bin/env python
"""
Debug "你好" latency in the current chat pipeline.

This script intentionally calls the real Django endpoint and real configured
LLM provider. It instruments key functions at runtime and writes a Markdown
report with timing evidence.

Run:
  /home/liuxuedeng/anaconda3/envs/django-agent/bin/python tests/debug_hello_latency.py
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.test import Client  # noqa: E402
from django.test import override_settings  # noqa: E402
from django.utils import timezone  # noqa: E402

from personal_knowledge_base.authentication import hash_password, issue_tokens  # noqa: E402
from personal_knowledge_base.models import KnowledgeBase, Message, Session, Tenant, TenantMember, User  # noqa: E402


REPORT_PATH = PROJECT_ROOT / "tests" / "hello_latency_debug_report.md"
QUERY = "你好"


class TimingRecorder:
    def __init__(self):
        self.records: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self.current_case = ""

    def add(self, name: str, duration_ms: int, **extra):
        with self._lock:
            self.records.append(
                {
                    "case": self.current_case,
                    "name": name,
                    "duration_ms": duration_ms,
                    "thread": threading.current_thread().name,
                    **extra,
                }
            )

    @contextmanager
    def case(self, name: str):
        previous = self.current_case
        self.current_case = name
        try:
            yield
        finally:
            self.current_case = previous


RECORDER = TimingRecorder()


def _duration_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _safe_len(value: Any) -> int:
    try:
        return len(value)
    except Exception:
        return 0


def _message_chars(messages: list[dict[str, Any]]) -> int:
    total = 0
    for msg in messages or []:
        total += len(str(msg.get("content", "")))
        if msg.get("tool_calls"):
            total += len(json.dumps(msg.get("tool_calls"), ensure_ascii=False))
    return total


def _wrap_function(module: Any, attr: str, label: str):
    original = getattr(module, attr)

    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        ok = True
        error = ""
        try:
            return original(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - diagnostic path
            ok = False
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            RECORDER.add(label, _duration_ms(start), ok=ok, error=error)

    setattr(module, attr, wrapper)
    return original


def _wrap_method(cls: type, attr: str, label: str):
    original = getattr(cls, attr)

    def wrapper(self, *args, **kwargs):
        start = time.perf_counter()
        ok = True
        error = ""
        extra: dict[str, Any] = {}
        try:
            result = original(self, *args, **kwargs)
            if label == "AgentEngine.execute":
                extra = {
                    "iterations": getattr(result, "total_iterations", None),
                    "stopped_reason": getattr(result, "stopped_reason", ""),
                    "agent_duration_ms": getattr(result, "duration_ms", None),
                    "steps": _safe_len(getattr(result, "steps", [])),
                }
            return result
        except Exception as exc:  # pragma: no cover - diagnostic path
            ok = False
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            RECORDER.add(label, _duration_ms(start), ok=ok, error=error, **extra)

    setattr(cls, attr, wrapper)
    return original


@contextmanager
def instrument_pipeline():
    import chat.views as chat_views
    import personal_knowledge_base.chat_runtime as chat_runtime
    import personal_knowledge_base.rag_pipeline as rag_pipeline
    import personal_knowledge_base.model_providers as model_providers
    import personal_knowledge_base.memory as memory
    from personal_knowledge_base.agent_engine import AgentEngine

    originals: list[tuple[Any, str, Any]] = []

    def patch_function(module: Any, attr: str, label: str):
        originals.append((module, attr, _wrap_function(module, attr, label)))

    def patch_method(cls: type, attr: str, label: str):
        originals.append((cls, attr, _wrap_method(cls, attr, label)))

    # Endpoint-local stages.
    patch_function(chat_views, "_save_session_after_chat", "chat._save_session_after_chat")
    patch_function(chat_views, "_run_agent_generation", "chat._run_agent_generation")
    patch_function(chat_views, "_build_agent_prefetch_context", "chat._build_agent_prefetch_context")
    patch_function(chat_runtime, "should_skip_expensive_prefetch", "chat_runtime.should_skip_expensive_prefetch")

    # RAG and memory stages.
    patch_function(rag_pipeline, "run_rag_pipeline", "rag.run_rag_pipeline")
    patch_function(memory, "retrieve_memory", "memory.retrieve_memory")

    # Agent stages.
    patch_method(AgentEngine, "execute", "AgentEngine.execute")
    patch_method(AgentEngine, "_call_llm_with_tools", "AgentEngine._call_llm_with_tools")

    # LLM HTTP calls.
    original_raw = model_providers.openai_compatible_chat_raw

    def raw_wrapper(base_url, api_key, model_name, messages, tools=None, temperature=None):
        start = time.perf_counter()
        ok = True
        error = ""
        response_info: dict[str, Any] = {}
        try:
            data = original_raw(base_url, api_key, model_name, messages, tools=tools, temperature=temperature)
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message", {})
            response_info = {
                "finish_reason": choice.get("finish_reason"),
                "response_chars": len(str(message.get("content", ""))),
                "tool_calls": _safe_len(message.get("tool_calls") or []),
            }
            return data
        except Exception as exc:  # pragma: no cover - diagnostic path
            ok = False
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            RECORDER.add(
                "llm.openai_compatible_chat_raw",
                _duration_ms(start),
                ok=ok,
                error=error,
                model_name=model_name,
                message_count=_safe_len(messages),
                message_chars=_message_chars(messages),
                has_tools=bool(tools),
                tool_count=_safe_len(tools or []),
                **response_info,
            )

    model_providers.openai_compatible_chat_raw = raw_wrapper
    originals.append((model_providers, "openai_compatible_chat_raw", original_raw))

    try:
        yield
    finally:
        for owner, attr, original in reversed(originals):
            setattr(owner, attr, original)


def create_debug_objects(title: str):
    suffix = uuid4().hex[:10]
    tenant = Tenant.objects.create(name=f"latency-debug-{suffix}", api_key=f"latency-key-{suffix}")
    user = User.objects.create(
        username=f"latency_user_{suffix}",
        email=f"latency_user_{suffix}@example.test",
        password_hash=hash_password("test-password"),
        tenant=tenant,
        preferences={"enable_memory": True},
    )
    TenantMember.objects.create(user=user, tenant=tenant, role="owner", status="active")
    token, _ = issue_tokens(user)
    kb = KnowledgeBase.objects.create(
        tenant=tenant,
        name=f"延迟诊断知识库-{suffix}",
        description="Empty KB for hello latency diagnosis",
        creator_id=user.id,
    )
    session = Session.objects.create(
        tenant=tenant,
        user_id=user.id,
        title=title,
        knowledge_base_id=kb.id,
        agent_config={"agent_enabled": True, "knowledge_base_ids": [kb.id], "enable_memory": True},
    )
    return tenant, user, token, kb, session


def parse_sse_frames(buffer: str):
    frames = buffer.split("\n\n")
    remainder = frames.pop() if frames else ""
    parsed = []
    for frame in frames:
        event = "message"
        data_lines = []
        for line in frame.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if not data_lines:
            continue
        data_raw = "\n".join(data_lines)
        try:
            data = json.loads(data_raw)
        except json.JSONDecodeError:
            data = data_raw
        parsed.append((event, data))
    return parsed, remainder


def run_agent_stream_case(case_name: str, title: str, *, enable_memory: bool = True) -> dict[str, Any]:
    tenant, user, token, kb, session = create_debug_objects(title)
    client = Client()
    headers = {
        "HTTP_AUTHORIZATION": f"Bearer {token}",
        "HTTP_X_TENANT_ID": str(tenant.id),
        "HTTP_ACCEPT": "text/event-stream",
        "HTTP_X_REQUEST_ID": f"latency-{uuid4()}",
    }
    payload = {
        "query": QUERY,
        "stream": True,
        "channel": "web",
        "agent_enabled": True,
        "knowledge_base_ids": [kb.id],
        "enable_memory": enable_memory,
    }

    result: dict[str, Any] = {
        "case": case_name,
        "session_title_initial": title,
        "enable_memory": enable_memory,
        "status_code": None,
        "header_latency_ms": None,
        "first_event_ms": None,
        "first_answer_ms": None,
        "first_tool_event_ms": None,
        "done_ms": None,
        "total_ms": None,
        "event_counts": {},
        "final_content_preview": "",
        "assistant_completed": False,
        "assistant_duration_ms": None,
        "error": "",
    }

    t0 = time.perf_counter()
    with RECORDER.case(case_name):
        try:
            response = client.post(
                f"/api/v1/agent-chat/{session.id}",
                data=json.dumps(payload, ensure_ascii=False),
                content_type="application/json",
                **headers,
            )
            result["header_latency_ms"] = _duration_ms(t0)
            result["status_code"] = response.status_code
            if response.status_code != 200:
                result["error"] = getattr(response, "content", b"").decode("utf-8", errors="replace")[:500]
                return result

            buffer = ""
            for chunk in response.streaming_content:
                if isinstance(chunk, bytes):
                    text = chunk.decode("utf-8", errors="replace")
                else:
                    text = str(chunk)
                buffer += text
                events, buffer = parse_sse_frames(buffer)
                for event, data in events:
                    now_ms = _duration_ms(t0)
                    result["event_counts"][event] = result["event_counts"].get(event, 0) + 1
                    response_type = data.get("response_type") if isinstance(data, dict) else ""
                    if response_type:
                        key = f"response_type:{response_type}"
                        result["event_counts"][key] = result["event_counts"].get(key, 0) + 1
                    if result["first_event_ms"] is None:
                        result["first_event_ms"] = now_ms
                    if response_type in {"tool_call", "tool_result", "actor_started", "actor_update", "actor_completed"} and result["first_tool_event_ms"] is None:
                        result["first_tool_event_ms"] = now_ms
                    if response_type == "answer" and isinstance(data, dict) and data.get("content") and result["first_answer_ms"] is None:
                        result["first_answer_ms"] = now_ms
                    if response_type == "answer" and isinstance(data, dict) and data.get("content"):
                        result["final_content_preview"] = str(data.get("content", ""))[:220]
                    if event == "done":
                        result["done_ms"] = now_ms
                        break
                if result["done_ms"] is not None:
                    break
            result["total_ms"] = _duration_ms(t0)

            assistant = (
                Message.objects.filter(session=session, role="assistant", visible_to_user=True)
                .order_by("-created_at")
                .first()
            )
            if assistant:
                result["assistant_completed"] = assistant.is_completed
                result["assistant_duration_ms"] = assistant.agent_duration_ms
                if not result["final_content_preview"]:
                    result["final_content_preview"] = (assistant.content or "")[:220]
            return result
        finally:
            # Keep cleanup best-effort; timings are already captured.
            time.sleep(0.2)
            try:
                tenant.delete()
            except Exception:
                pass


def summarize_records(records: list[dict[str, Any]], case: str):
    by_name: dict[str, list[int]] = {}
    for record in records:
        if record.get("case") != case:
            continue
        by_name.setdefault(record["name"], []).append(int(record["duration_ms"]))
    rows = []
    for name, values in sorted(by_name.items()):
        rows.append(
            {
                "name": name,
                "count": len(values),
                "total_ms": sum(values),
                "max_ms": max(values),
                "mean_ms": int(statistics.mean(values)),
            }
        )
    return rows


def format_ms(value):
    if value is None:
        return "-"
    return str(value)


def write_report(results: list[dict[str, Any]], records: list[dict[str, Any]]):
    lines = [
        "# 你好延迟诊断报告",
        "",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        "- 测试脚本：`tests/debug_hello_latency.py`",
        f"- 测试问题：`{QUERY}`",
        "- 测试口径：真实调用当前 Django `agent-chat` 流式接口，并用 runtime wrapper 记录关键函数耗时。",
        "",
        "## 环境配置",
        "",
        f"- `LLM_USE_ENV_CHAT`: `{getattr(settings, 'LLM_USE_ENV_CHAT', None)}`",
        f"- `LLM_USE_ENV_TITLE`: `{getattr(settings, 'LLM_USE_ENV_TITLE', None)}`",
        f"- `LLM_CHAT_MODEL`: `{getattr(settings, 'LLM_CHAT_MODEL', '')}`",
        f"- `LLM_TITLE_MODEL`: `{getattr(settings, 'LLM_TITLE_MODEL', '')}`",
        f"- `LLM_CHAT_MODEL_TIMEOUT`: `{getattr(settings, 'LLM_CHAT_MODEL_TIMEOUT', '')}`",
        f"- `LLM_CHAT_BASE_URL`: `{getattr(settings, 'LLM_CHAT_BASE_URL', '')}`",
        f"- `LLM_CHAT_API_KEY configured`: `{bool(getattr(settings, 'LLM_CHAT_API_KEY', ''))}`",
        "",
        "## 接口耗时结果",
        "",
        "| 场景 | HTTP | Header 等待 | 首事件 | 首回答 | 工具/Actor 首事件 | Done | Total | Assistant 完成 | Agent 内部耗时 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for item in results:
        lines.append(
            "| {case} | {status} | {header} | {first_event} | {first_answer} | {first_tool} | {done} | {total} | {completed} | {agent_ms} |".format(
                case=item["case"],
                status=item["status_code"],
                header=format_ms(item["header_latency_ms"]),
                first_event=format_ms(item["first_event_ms"]),
                first_answer=format_ms(item["first_answer_ms"]),
                first_tool=format_ms(item["first_tool_event_ms"]),
                done=format_ms(item["done_ms"]),
                total=format_ms(item["total_ms"]),
                completed=item["assistant_completed"],
                agent_ms=format_ms(item["assistant_duration_ms"]),
            )
        )

    lines.extend(["", "## 阶段耗时汇总", ""])
    for item in results:
        lines.extend([
            f"### {item['case']}",
            "",
            "| 阶段 | 次数 | 合计 ms | 最大单次 ms | 平均 ms |",
            "| --- | ---: | ---: | ---: | ---: |",
        ])
        for row in summarize_records(records, item["case"]):
            lines.append(f"| `{row['name']}` | {row['count']} | {row['total_ms']} | {row['max_ms']} | {row['mean_ms']} |")
        lines.append("")

    lines.extend([
        "## LLM 调用明细",
        "",
        "| 场景 | 模型 | 工具数 | 消息数 | Prompt 字符 | 耗时 ms | finish_reason | tool_calls | 输出字符 |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |",
    ])
    for record in records:
        if record["name"] != "llm.openai_compatible_chat_raw":
            continue
        lines.append(
            "| {case} | `{model}` | {tool_count} | {message_count} | {message_chars} | {duration} | {finish} | {tool_calls} | {response_chars} |".format(
                case=record.get("case", ""),
                model=record.get("model_name", ""),
                tool_count=record.get("tool_count", 0),
                message_count=record.get("message_count", 0),
                message_chars=record.get("message_chars", 0),
                duration=record.get("duration_ms", 0),
                finish=record.get("finish_reason", ""),
                tool_calls=record.get("tool_calls", ""),
                response_chars=record.get("response_chars", ""),
            )
        )

    lines.extend(["", "## 事件统计", ""])
    for item in results:
        lines.append(f"### {item['case']}")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(item["event_counts"], ensure_ascii=False, indent=2, sort_keys=True))
        lines.append("```")
        lines.append("")

    lines.extend([
        "## 代码路径证据",
        "",
        "- 前端仍固定发送 `agent_enabled: true`，后端 Agent 入口现在直接进入主 `AgentEngine`。",
        "- 对 `你好/您好/hi/hello/hey/嗨` 这类无附件、无图片、无 Web/MCP/文件提及的请求，`should_skip_expensive_prefetch(...)` 只跳过昂贵上下文预取，不生成答案。",
        "- 本报告如果出现一次 `AgentEngine.execute`、一次带 tools 的 LLM 调用，且没有 `rag.run_rag_pipeline` / `memory.retrieve_memory`，说明简单问题由主 Agent 首发直接回答。",
        "- 标题生成、记忆写入、ChatHistoryKB 索引和 ContextSnapshot 刷新均放在回答后的后台维护路径中。",
        "- 这更贴近 MiMo-Code：同一个主 Agent 决定直接回答还是调度 actor 子 Agent，而不是额外的轻量主 Agent。",
        "",
        "## 原始记录",
        "",
        "```json",
        json.dumps({"results": results, "records": records}, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
    ])
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main():
    results = []
    with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1", "*"]):
        with instrument_pipeline():
            results.append(run_agent_stream_case("agent_stream_new_session_title", "新的对话", enable_memory=True))
            results.append(run_agent_stream_case("agent_stream_existing_title", "已命名会话", enable_memory=True))
            results.append(run_agent_stream_case("agent_stream_existing_title_no_memory", "已命名会话", enable_memory=False))

    write_report(results, RECORDER.records)
    print(f"Wrote {REPORT_PATH}")
    for item in results:
        print(
            f"{item['case']}: status={item['status_code']} "
            f"header={item['header_latency_ms']}ms first_answer={item['first_answer_ms']}ms "
            f"done={item['done_ms']}ms total={item['total_ms']}ms"
        )
    return 0 if all(item["status_code"] == 200 for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
