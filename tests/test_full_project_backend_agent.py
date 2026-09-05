#!/usr/bin/env python
import json
import os
import sys
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.test import Client, TransactionTestCase, override_settings  # noqa: E402
from django.test.runner import DiscoverRunner  # noqa: E402
from django.test.utils import setup_test_environment, teardown_test_environment  # noqa: E402
from django.utils import timezone  # noqa: E402


REPORT_PATH = PROJECT_ROOT / "tests" / "full_project_backend_agent_report.md"

CASE_DEFINITIONS = {
    "test_api_resource_contracts_cover_auth_kb_wiki_and_model_usage": "覆盖认证、知识库列表、Wiki 页面/图谱、模型缓存命中率聚合接口。",
    "test_normal_chat_stream_and_continue_stream_contracts": "覆盖普通 RAG 流式生成、StreamManager 落库、完成消息 continue-stream 回放。",
    "test_agent_stream_non_stream_actor_trace_and_stop": "覆盖 Agent 流式/非流式、Actor trace 序列化、停止生成取消后台 Actor。",
    "test_tool_registry_schema_and_agent_engine_fallbacks": "覆盖 Tool 接口/JSON Schema/Registry、子 Actor 白名单、并行工具执行和工具结果降级。",
}

CASE_EVIDENCE: dict[str, dict] = {}
CASE_RESULTS: dict[str, dict] = {}


def _case_name(test):
    return getattr(test, "_testMethodName", str(test))


def _json_preview(value, max_len=520):
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = str(value)
    return text if len(text) <= max_len else text[:max_len] + "..."


def parse_sse(body: str) -> list[dict]:
    frames = []
    for raw_frame in body.split("\n\n"):
        raw_frame = raw_frame.strip()
        if not raw_frame:
            continue
        event = "message"
        data_lines = []
        for line in raw_frame.splitlines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
        data_text = "\n".join(data_lines)
        try:
            data = json.loads(data_text) if data_text else None
        except json.JSONDecodeError:
            data = data_text
        frames.append({"event": event, "data": data})
    return frames


def fake_rag_pipeline(tenant, query, kb_ids, session=None, user=None, enable_memory=True, model_id=""):
    return SimpleNamespace(
        query=query,
        search_query=f"rewrite:{query}",
        intent="kb_search",
        refs=[
            {
                "knowledge_id": "doc-backend-1",
                "knowledge_title": "后端测试文档",
                "knowledge_description": "综合测试引用",
                "content": "后端测试检索片段。",
                "score": 0.93,
            }
        ],
        memory_context="",
        chat_history_context="",
        kb_names="当前知识库：\n- 综合测试知识库",
        system_prompt="系统提示：严格基于测试上下文回答。",
        user_prompt=f"<context id=\"1\">后端测试检索片段。</context>\n\n<user_question>\n{query}\n</user_question>",
    )


class EvidenceResult(unittest.TextTestResult):
    def startTest(self, test):
        CASE_RESULTS[_case_name(test)] = {"started_at": time.time()}
        super().startTest(test)

    def _store(self, test, status, err=None):
        name = _case_name(test)
        started = CASE_RESULTS.get(name, {}).get("started_at", time.time())
        detail = ""
        if err:
            detail = self._exc_info_to_string(err, test)
        CASE_RESULTS[name] = {
            **CASE_RESULTS.get(name, {}),
            "status": status,
            "duration_ms": int((time.time() - started) * 1000),
            "detail": detail,
        }

    def addSuccess(self, test):
        self._store(test, "PASS")
        super().addSuccess(test)

    def addFailure(self, test, err):
        self._store(test, "FAIL", err)
        super().addFailure(test, err)

    def addError(self, test, err):
        self._store(test, "ERROR", err)
        super().addError(test, err)


class EvidenceRunner(unittest.TextTestRunner):
    resultclass = EvidenceResult


@override_settings(
    ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"],
    LLM_CHAT_API_KEY="",
    LLM_USE_ENV_CHAT=False,
    LLM_USE_ENV_SUMMARY=False,
    LLM_USE_ENV_TITLE=False,
    LLM_USE_ENV_QUESTION=False,
    LLM_USE_ENV_EXTRACT=False,
    LLM_USE_ENV_EMBEDDING=False,
    LLM_USE_ENV_RERANK=False,
    LLM_USE_ENV_VLM=False,
    LLM_USE_ENV_ASR=False,
)
class FullProjectBackendAgentTests(TransactionTestCase):
    def setUp(self):
        from personal_knowledge_base.authentication import hash_password, issue_tokens
        from personal_knowledge_base.models import Tenant, TenantMember, User

        unique = uuid4().hex[:10]
        self.tenant = Tenant.objects.create(name=f"full-test-{unique}", api_key=f"full-test-key-{unique}")
        self.user = User.objects.create(
            username=f"full_user_{unique}",
            email=f"full_user_{unique}@example.test",
            password_hash=hash_password("test-password"),
            tenant=self.tenant,
            preferences={"enable_memory": False},
        )
        TenantMember.objects.create(user=self.user, tenant=self.tenant, role="owner")
        token, _refresh = issue_tokens(self.user)
        self.client = Client()
        self.client.raise_request_exception = False
        self.auth_headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        self.stream_ids: list[str] = []
        self.patchers = [
            patch("chat.views.index_qa_to_kb_async"),
            patch("chat.views.refresh_context_snapshot_async"),
            patch("chat.views.is_memory_available", return_value=False),
            patch("chat.views.role_completion", return_value="综合测试标题"),
            patch("chat.views.delete_session_memory"),
        ]
        self.mocks = [p.start() for p in self.patchers]
        for patcher in self.patchers:
            self.addCleanup(patcher.stop)

    def tearDown(self):
        from personal_knowledge_base.stream_manager import stream_manager

        for stream_id in self.stream_ids:
            stream_manager.remove_stream(stream_id)

    def record(self, **data):
        CASE_EVIDENCE.setdefault(self._testMethodName, {}).update(data)

    def post_json(self, path, payload, accept=None):
        headers = dict(self.auth_headers)
        if accept:
            headers["HTTP_ACCEPT"] = accept
        return self.client.post(path, data=json.dumps(payload), content_type="application/json", **headers)

    def get_json(self, path):
        return self.client.get(path, **self.auth_headers)

    def create_session(self, title="综合测试会话"):
        response = self.post_json("/api/v1/sessions", {"title": title, "knowledge_base_id": "kb-full-test"})
        self.assertEqual(response.status_code, 201, response.content.decode("utf-8", errors="replace"))
        return response.json()["data"]["id"]

    def test_api_resource_contracts_cover_auth_kb_wiki_and_model_usage(self):
        from personal_knowledge_base.models import KnowledgeBase, ModelUsage, WikiPage

        kb = KnowledgeBase.objects.create(
            tenant=self.tenant,
            name="综合测试知识库",
            description="用于综合接口测试",
            creator_id=self.user.id,
        )
        WikiPage.objects.create(
            tenant=self.tenant,
            knowledge_base=kb,
            slug="index",
            title="Wiki 目录",
            content="内部目录页",
            page_type="index",
        )
        WikiPage.objects.create(
            tenant=self.tenant,
            knowledge_base=kb,
            slug="summary-main",
            title="知识库摘要",
            content="摘要连接 [[entity-python|Python]] 和 [[concept-rag|RAG]]",
            summary="全局摘要",
            out_links=[{"slug": "entity-python"}, {"slug": "concept-rag"}],
            page_type="summary",
        )
        WikiPage.objects.create(
            tenant=self.tenant,
            knowledge_base=kb,
            slug="entity-python",
            title="Python",
            content="实体页面",
            summary="Python 实体",
            out_links=[{"slug": "concept-rag"}],
            page_type="entity",
        )
        WikiPage.objects.create(
            tenant=self.tenant,
            knowledge_base=kb,
            slug="concept-rag",
            title="RAG",
            content="概念页面",
            summary="检索增强生成",
            page_type="concept",
        )
        usage_rows = [
            ("chat-1", "qwen-chat", "chat", 1000, 400, 1400),
            ("embed-1", "embedding", "embedding", 800, 160, 800),
            ("rerank-1", "rerank", "rerank", 600, 60, 600),
            ("vlm-1", "vision", "vlm", 400, 40, 500),
            ("summary-1", "summary", "summary", 9999, 9999, 9999),
            ("title-1", "title", "title", 9999, 9999, 9999),
        ]
        for model_id, model_name, model_type, prompt, cached, total in usage_rows:
            ModelUsage.objects.create(
                tenant=self.tenant,
                model_id=model_id,
                model_name=model_name,
                model_type=model_type,
                provider="test",
                scenario=model_type,
                prompt_tokens=prompt,
                cached_tokens=cached,
                total_tokens=total,
            )

        anonymous_response = Client().get("/api/v1/knowledge-bases")
        kb_response = self.get_json("/api/v1/knowledge-bases")
        wiki_pages_response = self.get_json(f"/api/v1/knowledge-bases/{kb.id}/wiki/pages")
        wiki_search_response = self.get_json(f"/api/v1/knowledge-bases/{kb.id}/wiki/search?q=Python")
        wiki_graph_response = self.get_json(f"/api/v1/knowledge-bases/{kb.id}/wiki/graph?mode=overview")
        usage_response = self.get_json("/api/v1/models/usage?range=1&granularity=15m")

        wiki_pages = wiki_pages_response.json()["data"]["items"]
        graph_data = wiki_graph_response.json()["data"]
        usage_data = usage_response.json()["data"]
        cache_models = usage_data["cache_series"]["models"]
        model_keys = [item["model_key"] for item in cache_models]

        self.record(
            anonymous_status=anonymous_response.status_code,
            kb_count=len(kb_response.json()["data"]["items"]),
            wiki_page_slugs=[page["slug"] for page in wiki_pages],
            wiki_search_count=len(wiki_search_response.json()["data"]["items"]),
            graph_nodes=len(graph_data["nodes"]),
            graph_edges=len(graph_data["edges"]),
            cache_model_keys=model_keys,
            cache_prompt_rate=usage_data["cache"]["prompt_rate"],
        )
        self.assertEqual(anonymous_response.status_code, 401)
        self.assertEqual(kb_response.status_code, 200)
        self.assertNotIn("index", [page["slug"] for page in wiki_pages])
        self.assertEqual(wiki_search_response.status_code, 200)
        self.assertGreaterEqual(len(wiki_search_response.json()["data"]["items"]), 1)
        self.assertEqual(wiki_graph_response.status_code, 200)
        self.assertEqual(len(graph_data["nodes"]), 3)
        self.assertGreaterEqual(len(graph_data["edges"]), 2)
        self.assertEqual(model_keys, ["group:chat", "group:embedding", "group:rerank", "group:vlm"])
        self.assertAlmostEqual(usage_data["cache"]["prompt_rate"], round((400 + 160 + 60 + 40) / (1000 + 800 + 600 + 400), 4))

    def test_normal_chat_stream_and_continue_stream_contracts(self):
        from personal_knowledge_base.models import Message

        session_id = self.create_session("普通流式综合测试")

        def fake_stream(*args, **kwargs):
            yield "普通"
            yield "流式"
            yield "回答"

        with patch("personal_knowledge_base.rag_pipeline.run_rag_pipeline", side_effect=fake_rag_pipeline), patch(
            "chat.views.chat_completion_stream",
            side_effect=fake_stream,
        ), patch("chat.views.chat_completion", return_value="不应触发 fallback"):
            response = self.post_json(
                f"/api/v1/knowledge-chat/{session_id}",
                {"query": "测试普通流式", "stream": True, "enable_memory": False},
                accept="text/event-stream",
            )
            body = b"".join(response.streaming_content).decode("utf-8")

        frames = parse_sse(body)
        assistant = Message.objects.filter(session_id=session_id, role="assistant").order_by("-created_at").first()
        deadline = time.time() + 2
        while assistant and not assistant.content and time.time() < deadline:
            time.sleep(0.05)
            assistant.refresh_from_db()
        self.stream_ids.append(assistant.id)
        continue_response = self.get_json(f"/api/v1/sessions/continue-stream/{session_id}?message_id={assistant.id}")
        continue_body = b"".join(continue_response.streaming_content).decode("utf-8")
        continue_frames = parse_sse(continue_body)
        response_types = [frame["data"].get("response_type") for frame in frames if isinstance(frame["data"], dict)]
        continue_types = [frame["data"].get("response_type") for frame in continue_frames if isinstance(frame["data"], dict)]
        continue_contents = [
            frame["data"].get("content", "")
            for frame in continue_frames
            if isinstance(frame["data"], dict)
        ]

        self.record(
            stream_status=response.status_code,
            response_types=response_types,
            db_content=assistant.content,
            db_completed=assistant.is_completed,
            continue_status=continue_response.status_code,
            continue_types=continue_types,
            continue_contents=[text for text in continue_contents if text],
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("answer", response_types)
        self.assertIn("complete", response_types)
        self.assertEqual(assistant.content, "普通流式回答")
        self.assertTrue(assistant.is_completed)
        self.assertEqual(continue_response.status_code, 200)
        self.assertIn("普通流式回答", continue_contents)
        self.assertIn("complete", continue_types)

    def test_agent_stream_non_stream_actor_trace_and_stop(self):
        from personal_knowledge_base.agent_engine import AgentResult, AgentStep
        from personal_knowledge_base.models import AgentActor, Message

        session_id = self.create_session("Agent 综合测试")

        class FakeAgentEngine:
            def __init__(self, *args, **kwargs):
                self.config = kwargs.get("agent_config", {})
                self.session_id = kwargs.get("session_id", "")

            def execute(self, query, history=None, context_str="", on_event=None, request_id=""):
                parent_message_id = self.config.get("parent_message_id", "")
                if parent_message_id:
                    AgentActor.objects.create(
                        session_id=self.session_id,
                        parent_actor_id="main",
                        actor_id=f"wiki_researcher-{uuid4().hex[:4]}",
                        agent_type="wiki_researcher",
                        mode="subagent",
                        status="idle",
                        last_outcome="success",
                        input_prompt=query,
                        output="Wiki 子 Agent 结果",
                        parent_message_id=parent_message_id,
                    )
                if on_event:
                    on_event("thinking", {"iteration": 1, "content": "主 Agent 正在分析"})
                    on_event(
                        "actor_started",
                        {
                            "response_type": "actor_started",
                            "actor_id": "wiki_researcher-1",
                            "agent_type": "wiki_researcher",
                            "name": "Wiki 研究子 Agent",
                            "status": "running",
                        },
                    )
                    on_event(
                        "actor_completed",
                        {
                            "response_type": "actor_completed",
                            "actor_id": "wiki_researcher-1",
                            "agent_type": "wiki_researcher",
                            "name": "Wiki 研究子 Agent",
                            "status": "idle",
                            "output": "Wiki 子 Agent 结果",
                        },
                    )
                return AgentResult(
                    content="Agent 综合回答",
                    steps=[AgentStep(iteration=1, thought="调度子 Agent")],
                    total_iterations=1,
                    duration_ms=12,
                )

        with patch("personal_knowledge_base.rag_pipeline.run_rag_pipeline", side_effect=fake_rag_pipeline), patch(
            "chat.views.AgentEngine",
            FakeAgentEngine,
        ), patch("chat.views.build_agent_history_with_snapshot", return_value=[]):
            stream_response = self.post_json(
                f"/api/v1/agent-chat/{session_id}",
                {"query": "测试 Agent 流式", "stream": True, "enable_memory": False},
                accept="text/event-stream",
            )
            stream_body = b"".join(stream_response.streaming_content).decode("utf-8")
            non_stream_response = self.post_json(
                f"/api/v1/agent-chat/{session_id}",
                {"query": "测试 Agent 非流式", "stream": False, "enable_memory": False},
            )

        stream_frames = parse_sse(stream_body)
        response_types = [frame["data"].get("response_type") for frame in stream_frames if isinstance(frame["data"], dict)]
        latest_assistant = Message.objects.filter(session_id=session_id, role="assistant").order_by("-created_at").first()
        self.stream_ids.append(latest_assistant.id)
        messages_response = self.get_json(f"/api/v1/messages/{session_id}/load")
        serialized_messages = messages_response.json()["data"]["items"]
        actor_trace_count = sum(len(item.get("actor_traces") or []) for item in serialized_messages if item["role"] == "assistant")

        pending_assistant = Message.objects.create(
            session_id=session_id,
            request_id=str(uuid4()),
            role="assistant",
            content="",
            is_completed=False,
        )
        pending_actor = AgentActor.objects.create(
            session_id=session_id,
            parent_actor_id="main",
            actor_id="doc_retriever-stop-test",
            agent_type="doc_retriever",
            mode="subagent",
            status="running",
            parent_message_id=pending_assistant.id,
        )
        stop_response = self.post_json(f"/api/v1/sessions/{session_id}/stop", {"message_id": pending_assistant.id})
        pending_actor.refresh_from_db()
        pending_assistant.refresh_from_db()

        self.record(
            stream_status=stream_response.status_code,
            stream_response_types=response_types,
            non_stream_status=non_stream_response.status_code,
            non_stream_answer=non_stream_response.json()["data"]["answer"],
            actor_trace_count=actor_trace_count,
            stop_status=stop_response.status_code,
            stopped_actor_status=pending_actor.status,
            stopped_message_completed=pending_assistant.is_completed,
        )
        self.assertEqual(stream_response.status_code, 200)
        self.assertIn("actor_started", response_types)
        self.assertIn("actor_completed", response_types)
        self.assertIn("complete", response_types)
        self.assertEqual(non_stream_response.status_code, 200)
        self.assertEqual(non_stream_response.json()["data"]["answer"], "Agent 综合回答")
        self.assertGreaterEqual(actor_trace_count, 2)
        self.assertEqual(stop_response.status_code, 200)
        self.assertEqual(pending_actor.status, "cancelled")
        self.assertTrue(pending_assistant.is_completed)

    def test_tool_registry_schema_and_agent_engine_fallbacks(self):
        from personal_knowledge_base.agent_engine import AgentEngine
        from personal_knowledge_base.agent_tools import Tool, ToolRegistry, get_tool_registry

        session_id = self.create_session("工具仓库测试")
        registry = get_tool_registry()
        actor_tool = registry.get("actor")
        actor_schema = actor_tool.parameters()
        subagent_context = {
            "tenant": self.tenant,
            "tenant_id": self.tenant.id,
            "session_id": session_id,
            "actor_id": "doc_retriever-1",
            "allow_actor_tool": False,
        }
        actor_result = actor_tool.execute({"action": "run", "subagent_type": "doc_retriever", "prompt": "测试"}, subagent_context)

        engine = AgentEngine(
            tenant=self.tenant,
            session_id=session_id,
            user_id=self.user.id,
            agent_config={
                "allowed_tools": ["thinking"],
                "parallel_tool_calls": True,
                "max_rounds": 3,
                "allow_actor_tool": False,
            },
        )
        calls = [
            {
                "id": "call-1",
                "function": {"name": "thinking", "arguments": json.dumps({"thought": "第一路"}, ensure_ascii=False)},
            },
            {
                "id": "call-2",
                "function": {"name": "thinking", "arguments": json.dumps({"thought": "第二路"}, ensure_ascii=False)},
            },
        ]
        engine._call_llm_with_tools = lambda messages, max_retries=3: {"content": "需要并行思考", "tool_calls": calls} if len(messages) < 4 else {"content": "最终回答", "tool_calls": None}
        engine._call_llm_simple = lambda messages: "摘要"
        parallel_result = engine.execute("并行工具测试")

        degrading_engine = AgentEngine(
            tenant=self.tenant,
            session_id=session_id,
            user_id=self.user.id,
            agent_config={"allowed_tools": ["thinking"], "max_rounds": 3, "allow_actor_tool": False},
        )
        state = {"count": 0}

        def degrading_llm(messages, max_retries=3):
            state["count"] += 1
            if state["count"] == 1:
                return {
                    "content": "先查工具",
                    "tool_calls": [
                        {
                            "id": "call-degrade",
                            "function": {"name": "thinking", "arguments": json.dumps({"thought": "已找到信息"}, ensure_ascii=False)},
                        }
                    ],
                }
            raise TimeoutError("simulated model timeout")

        degrading_engine._call_llm_with_tools = degrading_llm
        degrading_engine._call_llm_simple = lambda messages: "摘要"
        degraded_result = degrading_engine.execute("降级测试")

        class BrokenTool(Tool):
            def name(self):
                return "broken_tool"

            def description(self):
                return "Always raises for registry error handling."

            def parameters(self):
                return {"type": "object", "properties": {}}

            def execute(self, args, context):
                raise RuntimeError("boom")

        isolated_registry = ToolRegistry()
        isolated_registry.register(BrokenTool())
        broken_result = isolated_registry.execute_tool("broken_tool", {}, {})

        self.record(
            actor_schema_actions=actor_schema["properties"]["action"]["enum"],
            subagent_actor_error=actor_result.error,
            parallel_iterations=parallel_result.total_iterations,
            parallel_tool_count=len(parallel_result.steps[0].tool_calls),
            degraded_reason=degraded_result.stopped_reason,
            degraded_preview=degraded_result.content[:120],
            broken_tool_error=broken_result.error[:80],
        )
        self.assertIn("run", actor_schema["properties"]["action"]["enum"])
        self.assertIn("spawn", actor_schema["properties"]["action"]["enum"])
        self.assertEqual(actor_result.error, "subagents cannot call actor tool")
        self.assertEqual(parallel_result.stopped_reason, "completed")
        self.assertEqual(len(parallel_result.steps[0].tool_calls), 2)
        self.assertEqual(degraded_result.stopped_reason, "degraded")
        self.assertIn("根据检索到的信息", degraded_result.content)
        self.assertIn("RuntimeError", broken_result.error)


def write_report(result: EvidenceResult):
    total = result.testsRun
    failed = len(result.failures)
    errored = len(result.errors)
    skipped = len(result.skipped)
    passed = total - failed - errored - skipped
    lines = [
        "# 当前项目后端与 Agent 综合测试报告",
        "",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        "- 测试脚本：`tests/test_full_project_backend_agent.py`",
        "- 执行命令：`/home/liuxuedeng/anaconda3/envs/django-agent/bin/python tests/test_full_project_backend_agent.py`",
        "- 测试口径：Django 测试数据库 + 可控 mock；不依赖真实外部 LLM、真实向量库或真实 Neo4j 服务。",
        f"- 汇总：共 {total} 项，PASS {passed}，FAIL {failed}，ERROR {errored}，SKIP {skipped}。",
        "",
        "## 用例结果",
        "",
        "| 用例 | 结果 | 耗时 | 目标 | 关键证据 |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for name, objective in CASE_DEFINITIONS.items():
        item = CASE_RESULTS.get(name, {"status": "NOT_RUN", "duration_ms": 0, "detail": ""})
        lines.append(
            f"| `{name}` | {item['status']} | {item.get('duration_ms', 0)} ms | {objective} | "
            f"`{_json_preview(CASE_EVIDENCE.get(name, {}))}` |"
        )

    failed_items = [(name, data) for name, data in CASE_RESULTS.items() if data.get("status") in {"FAIL", "ERROR"}]
    lines.extend(["", "## 失败与风险", ""])
    if not failed_items:
        lines.append("- 本次测试未发现失败用例。")
    else:
        for name, data in failed_items:
            detail = data.get("detail", "").strip().splitlines()
            preview = "\n".join(detail[-18:]) if detail else ""
            lines.extend([f"### `{name}`", "", f"- 状态：{data.get('status')}", f"- 证据：`{_json_preview(CASE_EVIDENCE.get(name, {}), max_len=900)}`"])
            if preview:
                lines.extend(["", "```text", preview, "```"])
            lines.append("")

    lines.extend(
        [
            "",
            "## 覆盖范围",
            "",
            "- 覆盖：认证、知识库/Wiki/图谱接口、模型缓存命中率聚合、普通流式、continue-stream、Agent 流式与非流式、Actor trace、停止生成、Tool Schema、工具异常降级。",
            "- 未覆盖：真实模型质量、真实 embedding/rerank/vlm 调用、真实 Neo4j 可用性、生产环境并发压测、浏览器真实 DOM 交互。",
            "- 说明：报告所有结论来自本脚本实际断言结果；若代码或环境变化，应重新运行脚本更新。",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    setup_test_environment()
    runner = DiscoverRunner(verbosity=0, interactive=False)
    old_config = runner.setup_databases()
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(FullProjectBackendAgentTests)
        result = EvidenceRunner(verbosity=2).run(suite)
        write_report(result)
        return 0 if result.wasSuccessful() else 1
    finally:
        runner.teardown_databases(old_config)
        teardown_test_environment()


if __name__ == "__main__":
    raise SystemExit(main())
