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


REPORT_PATH = PROJECT_ROOT / "tests" / "chat_feature_test_report.md"

CASE_DEFINITIONS = {
    "test_requires_auth_for_session_and_chat_endpoints": "未认证请求应被拒绝，避免对话接口匿名访问。",
    "test_session_lifecycle_and_soft_delete": "会话创建、查询、置顶、取消置顶、删除应保持状态一致。",
    "test_normal_chat_non_stream_persists_user_and_assistant_messages": "普通非流式问答应返回回答，并落库 user/assistant 两条可见消息。",
    "test_messages_load_and_search_hide_invisible_actor_messages": "消息加载与搜索不应暴露 visible_to_user=False 的子 Actor 隐藏消息。",
    "test_normal_chat_stream_emits_sse_and_persists_final_answer": "普通流式问答应产生 SSE 事件，并在完成后持久化最终回答。",
    "test_continue_stream_replays_unfinished_message_from_offset_zero": "continue-stream 应从 offset=0 回放未完成消息的 StreamManager 事件。",
    "test_continue_stream_completed_message_returns_final_snapshot": "已完成消息的 continue-stream 应直接返回最终消息和 complete/done 事件。",
    "test_stop_marks_message_completed_and_cancels_related_actor": "停止生成应标记目标消息完成，并取消关联的后台 Actor。",
    "test_agent_chat_stream_emits_actor_generation_events": "Agent 流式问答应通过生成线程写入事件并由 SSE 推送最终结果。",
    "test_agent_chat_non_stream_returns_http_response": "Agent 非流式问答应返回有效 HTTP 响应，而不是空响应或 500。",
}

CASE_EVIDENCE: dict[str, dict] = {}
CASE_RESULTS: dict[str, dict] = {}


def _case_name(test):
    return getattr(test, "_testMethodName", str(test))


def _json_preview(value, max_len=360):
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = str(value)
    return text if len(text) <= max_len else text[:max_len] + "..."


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

    def addSkip(self, test, reason):
        name = _case_name(test)
        CASE_RESULTS[name] = {
            **CASE_RESULTS.get(name, {}),
            "status": "SKIP",
            "duration_ms": 0,
            "detail": reason,
        }
        super().addSkip(test, reason)


class EvidenceRunner(unittest.TextTestRunner):
    resultclass = EvidenceResult


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


def fake_rag_context(query: str, kb_ids=None, refs=None):
    return SimpleNamespace(
        query=query,
        search_query=f"rewrite:{query}",
        intent="kb_search",
        refs=refs if refs is not None else [
            {
                "knowledge_id": "doc-1",
                "knowledge_title": "测试文档",
                "knowledge_description": "用于对话功能测试",
                "content": "这是测试检索内容。",
                "score": 0.91,
            }
        ],
        memory_context="",
        chat_history_context="",
        kb_names="当前知识库：\n- 测试知识库",
        system_prompt="系统提示：基于测试上下文回答。",
        user_prompt=f"<context id=\"1\">这是测试检索内容。</context>\n\n<user_question>\n{query}\n</user_question>",
    )


def fake_rag_pipeline(tenant, query, kb_ids, session=None, user=None, enable_memory=True, model_id=""):
    return fake_rag_context(query, kb_ids=kb_ids)


@override_settings(
    ALLOWED_HOSTS=["testserver"],
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
class ChatFeatureObjectiveTests(TransactionTestCase):
    def setUp(self):
        from personal_knowledge_base.authentication import hash_password, issue_tokens
        from personal_knowledge_base.models import Tenant, TenantMember, User

        unique = uuid4().hex[:10]
        self.tenant = Tenant.objects.create(name=f"chat-test-{unique}", api_key=f"chat-test-key-{unique}")
        self.user = User.objects.create(
            username=f"chat_user_{unique}",
            email=f"chat_user_{unique}@example.test",
            password_hash=hash_password("test-password"),
            tenant=self.tenant,
            preferences={"enable_memory": False},
        )
        TenantMember.objects.create(user=self.user, tenant=self.tenant, role="owner")
        token, _refresh = issue_tokens(self.user)
        self.client = Client()
        self.auth_headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        self.stream_ids: list[str] = []

        self.patchers = [
            patch("chat.views.index_qa_to_kb_async"),
            patch("chat.views.refresh_context_snapshot_async"),
            patch("chat.views.is_memory_available", return_value=False),
            patch("chat.views.role_completion", return_value="测试标题"),
            patch("chat.views.delete_session_memory"),
        ]
        self.mocks = [p.start() for p in self.patchers]
        for p in self.patchers:
            self.addCleanup(p.stop)

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

    def create_session(self, title="对话测试会话"):
        response = self.post_json("/api/v1/sessions", {"title": title, "knowledge_base_id": "kb-chat-test"})
        self.assertEqual(response.status_code, 201)
        return response.json()["data"]["id"]

    def test_requires_auth_for_session_and_chat_endpoints(self):
        anonymous = Client()
        sessions_response = anonymous.get("/api/v1/sessions")
        chat_response = anonymous.post(
            "/api/v1/knowledge-chat/non-existent",
            data=json.dumps({"query": "未认证测试"}),
            content_type="application/json",
        )

        self.record(
            sessions_status=sessions_response.status_code,
            chat_status=chat_response.status_code,
        )
        self.assertEqual(sessions_response.status_code, 401)
        self.assertEqual(chat_response.status_code, 401)

    def test_session_lifecycle_and_soft_delete(self):
        from personal_knowledge_base.models import Session

        session_id = self.create_session("生命周期测试")
        get_response = self.get_json(f"/api/v1/sessions/{session_id}")
        list_response = self.get_json("/api/v1/sessions")
        pin_response = self.client.post(f"/api/v1/sessions/{session_id}/pin", **self.auth_headers)
        unpin_response = self.client.delete(f"/api/v1/sessions/{session_id}/pin", **self.auth_headers)
        delete_response = self.client.delete(f"/api/v1/sessions/{session_id}", **self.auth_headers)
        deleted_at = Session.objects.get(id=session_id).deleted_at

        self.record(
            get_status=get_response.status_code,
            list_count=len(list_response.json()["data"]["items"]),
            pinned=pin_response.json()["data"]["is_pinned"],
            unpinned=not unpin_response.json()["data"]["is_pinned"],
            delete_status=delete_response.status_code,
            deleted_at_present=deleted_at is not None,
        )
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(list_response.status_code, 200)
        self.assertTrue(pin_response.json()["data"]["is_pinned"])
        self.assertFalse(unpin_response.json()["data"]["is_pinned"])
        self.assertEqual(delete_response.status_code, 200)
        self.assertIsNotNone(deleted_at)

    def test_normal_chat_non_stream_persists_user_and_assistant_messages(self):
        from personal_knowledge_base.models import Message

        session_id = self.create_session("普通非流式测试")
        with patch("personal_knowledge_base.rag_pipeline.run_rag_pipeline", side_effect=fake_rag_pipeline), patch(
            "chat.views.chat_completion",
            return_value="这是普通非流式回答。",
        ) as completion:
            response = self.post_json(
                f"/api/v1/knowledge-chat/{session_id}",
                {"query": "普通非流式问题", "stream": False, "enable_memory": False},
            )

        messages = list(Message.objects.filter(session_id=session_id).order_by("created_at"))
        assistant = [m for m in messages if m.role == "assistant"][0]
        self.record(
            status=response.status_code,
            answer=response.json()["data"]["answer"],
            message_roles=[m.role for m in messages],
            assistant_completed=assistant.is_completed,
            assistant_refs_count=len(assistant.knowledge_references),
            llm_called=completion.called,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["answer"], "这是普通非流式回答。")
        self.assertEqual([m.role for m in messages], ["user", "assistant"])
        self.assertTrue(assistant.is_completed)
        self.assertEqual(len(assistant.knowledge_references), 1)
        self.assertTrue(completion.called)

    def test_messages_load_and_search_hide_invisible_actor_messages(self):
        from personal_knowledge_base.models import Message, Session

        session = Session.objects.create(tenant=self.tenant, title="消息可见性测试")
        visible_user = Message.objects.create(
            session=session,
            request_id="visible-req",
            role="user",
            content="可见问题",
            is_completed=True,
            visible_to_user=True,
        )
        visible_assistant = Message.objects.create(
            session=session,
            request_id="visible-req",
            role="assistant",
            content="可见回答",
            is_completed=True,
            visible_to_user=True,
        )
        Message.objects.create(
            session=session,
            request_id="hidden-req",
            role="assistant",
            content="隐藏子 Actor 内容",
            is_completed=True,
            agent_id="doc_retriever-1",
            visible_to_user=False,
        )

        load_response = self.get_json(f"/api/v1/messages/{session.id}/load?limit=20")
        search_response = self.post_json("/api/v1/messages/search", {"query": "隐藏子 Actor 内容"})
        loaded = load_response.json()["data"]["items"]
        searched = search_response.json()["data"]["items"]

        self.record(
            load_status=load_response.status_code,
            loaded_ids=[item["id"] for item in loaded],
            hidden_present_in_load=any(item["content"] == "隐藏子 Actor 内容" for item in loaded),
            search_status=search_response.status_code,
            search_count=len(searched),
        )
        self.assertEqual(load_response.status_code, 200)
        self.assertEqual([item["id"] for item in loaded], [visible_user.id, visible_assistant.id])
        self.assertFalse(any(item["content"] == "隐藏子 Actor 内容" for item in loaded))
        self.assertEqual(search_response.status_code, 200)
        self.assertEqual(searched, [])

    def test_normal_chat_stream_emits_sse_and_persists_final_answer(self):
        from personal_knowledge_base.models import Message

        session_id = self.create_session("普通流式测试")

        def token_stream(_tenant, _messages, _model_id):
            yield "流"
            yield "式"
            yield "回答"

        with patch("personal_knowledge_base.rag_pipeline.run_rag_pipeline", side_effect=fake_rag_pipeline), patch(
            "chat.views.chat_completion_stream",
            side_effect=token_stream,
        ):
            response = self.post_json(
                f"/api/v1/knowledge-chat/{session_id}",
                {"query": "普通流式问题", "stream": True, "enable_memory": False},
                accept="text/event-stream",
            )
            body = b"".join(response.streaming_content).decode("utf-8")

        frames = parse_sse(body)
        response_types = [frame["data"].get("response_type") for frame in frames if isinstance(frame["data"], dict)]
        assistant = Message.objects.filter(session_id=session_id, role="assistant").order_by("-created_at").first()
        deadline = time.time() + 2
        while time.time() < deadline:
            assistant.refresh_from_db()
            if assistant.is_completed and assistant.content:
                break
            time.sleep(0.05)
        self.stream_ids.append(assistant.id)
        self.record(
            status=response.status_code,
            content_type=response["Content-Type"],
            event_names=[frame["event"] for frame in frames],
            response_types=response_types,
            final_db_content=assistant.content,
            assistant_completed=assistant.is_completed,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response["Content-Type"])
        self.assertIn("message_start", [frame["event"] for frame in frames])
        self.assertIn("complete", response_types)
        self.assertIn("done", [frame["event"] for frame in frames])
        self.assertEqual(assistant.content, "流式回答")
        self.assertTrue(assistant.is_completed)

    def test_continue_stream_replays_unfinished_message_from_offset_zero(self):
        from personal_knowledge_base.models import Message, Session
        from personal_knowledge_base.stream_manager import stream_manager

        session = Session.objects.create(tenant=self.tenant, title="continue-stream 未完成测试")
        assistant = Message.objects.create(
            session=session,
            request_id="continue-req",
            role="assistant",
            content="",
            is_completed=False,
        )
        self.stream_ids.append(assistant.id)
        stream = stream_manager.create_stream(assistant.id, session.id)
        stream.append_event("thinking", {"content": "中间草稿"})
        stream.append_event("tool_call", {"name": "knowledge_search", "arguments": {"query": "测试"}, "iteration": 1})
        stream.append_event("tool_result", {"name": "knowledge_search", "output": "工具输出" * 80, "duration_ms": 12})
        stream.append_event("actor_started", {"response_type": "actor_started", "actor_id": "wiki_researcher-1"})
        stream.set_final_result(content="最终回放回答", refs=[{"knowledge_title": "测试文档"}])
        stream.append_event("complete", {"done": True, "content": "最终回放回答"})

        response = self.get_json(f"/api/v1/sessions/continue-stream/{session.id}?message_id={assistant.id}")
        body = b"".join(response.streaming_content).decode("utf-8")
        frames = parse_sse(body)
        response_types = [frame["data"].get("response_type") for frame in frames if isinstance(frame["data"], dict)]
        tool_result_frames = [
            frame["data"]
            for frame in frames
            if isinstance(frame["data"], dict) and frame["data"].get("response_type") == "tool_result"
        ]

        self.record(
            status=response.status_code,
            event_names=[frame["event"] for frame in frames],
            response_types=response_types,
            replayed_tool_result_output_len=len(tool_result_frames[0]["output"]) if tool_result_frames else 0,
            final_answer_seen=any(
                isinstance(frame["data"], dict) and frame["data"].get("content") == "最终回放回答"
                for frame in frames
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("answer", response_types)
        self.assertIn("tool_call", response_types)
        self.assertIn("tool_result", response_types)
        self.assertIn("actor_started", response_types)
        self.assertIn("complete", response_types)
        self.assertIn("done", [frame["event"] for frame in frames])
        self.assertLessEqual(len(tool_result_frames[0]["output"]), 300)
        self.assertTrue(any(isinstance(frame["data"], dict) and frame["data"].get("content") == "最终回放回答" for frame in frames))

    def test_continue_stream_completed_message_returns_final_snapshot(self):
        from personal_knowledge_base.models import Message, Session

        session = Session.objects.create(tenant=self.tenant, title="continue-stream 完成测试")
        assistant = Message.objects.create(
            session=session,
            request_id="completed-req",
            role="assistant",
            content="已完成回答",
            rendered_content="已完成回答",
            is_completed=True,
        )

        response = self.get_json(f"/api/v1/sessions/continue-stream/{session.id}?message_id={assistant.id}")
        body = b"".join(response.streaming_content).decode("utf-8")
        frames = parse_sse(body)
        response_types = [frame["data"].get("response_type") for frame in frames if isinstance(frame["data"], dict)]

        self.record(
            status=response.status_code,
            event_names=[frame["event"] for frame in frames],
            response_types=response_types,
            completed_content_seen=any(
                isinstance(frame["data"], dict) and frame["data"].get("content") == "已完成回答"
                for frame in frames
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("complete", response_types)
        self.assertIn("done", [frame["event"] for frame in frames])
        self.assertTrue(any(isinstance(frame["data"], dict) and frame["data"].get("content") == "已完成回答" for frame in frames))

    def test_stop_marks_message_completed_and_cancels_related_actor(self):
        from personal_knowledge_base.agent_actor import ActorRegistry
        from personal_knowledge_base.models import AgentActor, Message, Session
        from personal_knowledge_base.stream_manager import stream_manager

        session = Session.objects.create(tenant=self.tenant, title="停止测试")
        assistant = Message.objects.create(
            session=session,
            request_id="stop-req",
            role="assistant",
            content="",
            is_completed=False,
        )
        self.stream_ids.append(assistant.id)
        stream_manager.create_stream(assistant.id, session.id)
        main_actor = ActorRegistry.ensure_main_actor(session)
        actor = ActorRegistry.create_subagent(
            session=session,
            parent_actor=main_actor,
            agent_type="wiki_researcher",
            input_prompt="后台研究",
            parent_message_id=assistant.id,
            background=True,
        )
        ActorRegistry.mark_running(actor)

        response = self.post_json(f"/api/v1/sessions/{session.id}/stop", {"message_id": assistant.id})
        assistant.refresh_from_db()
        actor = AgentActor.objects.get(id=actor.id)

        self.record(
            status=response.status_code,
            stopped=response.json()["data"]["stopped"],
            assistant_completed=assistant.is_completed,
            actor_status=actor.status,
            actor_outcome=actor.last_outcome,
            cancel_requested=(actor.metadata or {}).get("cancel_requested"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(assistant.is_completed)
        self.assertEqual(actor.status, "cancelled")
        self.assertEqual(actor.last_outcome, "cancelled")
        self.assertTrue((actor.metadata or {}).get("cancel_requested"))

    def test_agent_chat_stream_emits_actor_generation_events(self):
        from personal_knowledge_base.agent_engine import AgentResult, AgentStep
        from personal_knowledge_base.models import Message

        session_id = self.create_session("Agent 流式测试")

        class FakeAgentEngine:
            def __init__(self, *args, **kwargs):
                pass

            def execute(self, query, history=None, context_str="", on_event=None):
                if on_event:
                    on_event("thinking", {"content": "Agent 正在分析"})
                    on_event("tool_call", {"name": "actor", "arguments": {"action": "run"}, "iteration": 1})
                    on_event("tool_result", {"name": "actor", "output": "子 Agent 结果", "duration_ms": 5})
                return AgentResult(
                    content="Agent 流式最终回答",
                    steps=[AgentStep(iteration=1, thought="调用子 Agent")],
                    total_iterations=1,
                    duration_ms=9,
                )

        with patch("personal_knowledge_base.rag_pipeline.run_rag_pipeline", side_effect=fake_rag_pipeline), patch(
            "chat.views.AgentEngine",
            FakeAgentEngine,
        ), patch("chat.views.build_agent_history_with_snapshot", return_value=[]):
            response = self.post_json(
                f"/api/v1/agent-chat/{session_id}",
                {"query": "Agent 流式问题", "stream": True, "enable_memory": False},
                accept="text/event-stream",
            )
            body = b"".join(response.streaming_content).decode("utf-8")

        frames = parse_sse(body)
        response_types = [frame["data"].get("response_type") for frame in frames if isinstance(frame["data"], dict)]
        assistant = Message.objects.filter(session_id=session_id, role="assistant").order_by("-created_at").first()
        self.stream_ids.append(assistant.id)
        self.record(
            status=response.status_code,
            response_types=response_types,
            final_db_content=assistant.content,
            assistant_completed=assistant.is_completed,
            agent_steps_count=len(assistant.agent_steps or []),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("answer", response_types)
        self.assertIn("tool_call", response_types)
        self.assertIn("tool_result", response_types)
        self.assertIn("complete", response_types)
        self.assertEqual(assistant.content, "Agent 流式最终回答")
        self.assertTrue(assistant.is_completed)

    def test_agent_chat_non_stream_returns_http_response(self):
        from personal_knowledge_base.agent_engine import AgentResult, AgentStep
        from personal_knowledge_base.models import Message

        session_id = self.create_session("Agent 非流式测试")

        class FakeAgentEngine:
            def __init__(self, *args, **kwargs):
                pass

            def execute(self, query, history=None, context_str="", on_event=None):
                return AgentResult(
                    content="Agent 非流式回答",
                    steps=[AgentStep(iteration=1, thought="非流式执行")],
                    total_iterations=1,
                    duration_ms=7,
                )

        self.client.raise_request_exception = False
        with patch("personal_knowledge_base.rag_pipeline.run_rag_pipeline", side_effect=fake_rag_pipeline), patch(
            "chat.views.AgentEngine",
            FakeAgentEngine,
        ), patch("chat.views.build_agent_history_with_snapshot", return_value=[]):
            response = self.post_json(
                f"/api/v1/agent-chat/{session_id}",
                {"query": "Agent 非流式问题", "stream": False, "enable_memory": False},
            )

        assistant_messages = list(Message.objects.filter(session_id=session_id, role="assistant").order_by("created_at"))
        self.record(
            status=response.status_code,
            content_type=response.get("Content-Type", ""),
            response_preview=response.content.decode("utf-8", errors="replace")[:240],
            assistant_messages=len(assistant_messages),
            last_assistant_completed=assistant_messages[-1].is_completed if assistant_messages else None,
            last_assistant_content=assistant_messages[-1].content if assistant_messages else "",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertEqual(payload["answer"], "Agent 非流式回答")
        self.assertEqual(len(assistant_messages), 1)
        self.assertTrue(assistant_messages[-1].is_completed)


def write_report(result: EvidenceResult):
    total = result.testsRun
    failed = len(result.failures)
    errored = len(result.errors)
    skipped = len(result.skipped)
    passed = total - failed - errored - skipped
    lines = [
        "# 对话功能客观测试报告",
        "",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        f"- 测试脚本：`tests/test_chat_feature_objective.py`",
        f"- 执行命令：`/home/liuxuedeng/anaconda3/envs/django-agent/bin/python tests/test_chat_feature_objective.py`",
        f"- 测试口径：后端 API / Django 测试库 / 可控 mock；不依赖真实外部 LLM、真实向量检索或浏览器 UI。",
        f"- 汇总：共 {total} 项，PASS {passed}，FAIL {failed}，ERROR {errored}，SKIP {skipped}。",
        "",
        "## 用例结果",
        "",
        "| 用例 | 结果 | 耗时 | 目标 | 关键证据 |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for name, objective in CASE_DEFINITIONS.items():
        result_item = CASE_RESULTS.get(name, {"status": "NOT_RUN", "duration_ms": 0, "detail": ""})
        evidence = CASE_EVIDENCE.get(name, {})
        lines.append(
            f"| `{name}` | {result_item['status']} | {result_item.get('duration_ms', 0)} ms | "
            f"{objective} | `{_json_preview(evidence)}` |"
        )

    failed_items = [
        (name, data)
        for name, data in CASE_RESULTS.items()
        if data.get("status") in {"FAIL", "ERROR"}
    ]
    lines.extend(["", "## 失败与风险", ""])
    if not failed_items:
        lines.append("- 本次测试未发现失败用例。")
    else:
        for name, data in failed_items:
            detail = data.get("detail", "").strip().splitlines()
            preview = "\n".join(detail[-12:]) if detail else ""
            lines.append(f"### `{name}`")
            lines.append("")
            lines.append(f"- 状态：{data.get('status')}")
            lines.append(f"- 证据：`{_json_preview(CASE_EVIDENCE.get(name, {}), max_len=800)}`")
            if preview:
                lines.append("")
                lines.append("```text")
                lines.append(preview)
                lines.append("```")
            lines.append("")

    lines.extend(
        [
            "## 覆盖范围",
            "",
            "- 覆盖：认证拦截、会话生命周期、普通非流式问答、普通 SSE 流式问答、continue-stream 回放、停止生成、消息可见性、Agent 流式与非流式路径。",
            "- 未覆盖：真实前端浏览器交互、真实外部模型质量、真实向量库召回质量、真实 Neo4j 可用性、并发压测和长时间稳定性。",
            "- 说明：本报告内容由测试脚本根据实际断言结果生成；如果业务代码或环境变化，应重新运行脚本更新报告。",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    setup_test_environment()
    runner = DiscoverRunner(verbosity=0, interactive=False)
    old_config = runner.setup_databases()
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(ChatFeatureObjectiveTests)
        result = EvidenceRunner(verbosity=2).run(suite)
        write_report(result)
        return 0 if result.wasSuccessful() else 1
    finally:
        runner.teardown_databases(old_config)
        teardown_test_environment()


if __name__ == "__main__":
    raise SystemExit(main())
