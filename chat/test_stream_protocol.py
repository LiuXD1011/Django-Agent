import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, TestCase

from personal_knowledge_base.agent_engine import AgentEngine, AgentResult
from personal_knowledge_base.agent_tools import ToolResult
from personal_knowledge_base.authentication import issue_tokens
from personal_knowledge_base.models import Message, Session, Tenant, User
from personal_knowledge_base.stream_manager import stream_manager
from personal_knowledge_base.stream_protocol import tool_stream_payload


class _EventRegistry:
    def to_openai_tools(self, _allowed_tools):
        return [
            {
                "type": "function",
                "function": {"name": "test_tool", "description": "test", "parameters": {}},
            }
        ]

    def execute_tool(self, _name, _arguments, _context):
        return ToolResult(output="x" * 800, error="tool failed", duration_ms=73)


class _ImmediateAgentEngine:
    def __init__(self, *_args, **_kwargs):
        pass

    def execute(self, _query, history=None, context_str="", on_event=None):
        if on_event:
            on_event("thinking", {"content": "worker started"})
        return AgentResult(content="complete", steps=[], total_iterations=1, duration_ms=1)


class _NoopThread:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def start(self):
        pass


class StreamProtocolTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Stream tenant", api_key="stream-test-key")
        self.user = User.objects.create(
            username="stream-user",
            email="stream@example.com",
            password_hash="unused",
            tenant=self.tenant,
        )
        token, _ = issue_tokens(self.user)
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        self.session = Session.objects.create(tenant=self.tenant, title="Stream test")
        self.message = Message.objects.create(
            session=self.session,
            request_id="stream-request",
            role="assistant",
            content="",
            rendered_content="",
            is_completed=False,
        )
        self.continue_url = (
            f"/api/v1/sessions/continue-stream/{self.session.id}?message_id={self.message.id}"
        )

    def tearDown(self):
        stream_manager.remove_stream(self.message.id)

    def test_agent_engine_tool_result_event_keeps_full_output_in_parallel_and_sequential_paths(self):
        tool_calls = [
            {"id": "call-1", "function": {"name": "test_tool", "arguments": "{}"}},
            {"id": "call-2", "function": {"name": "test_tool", "arguments": "{}"}},
        ]

        for parallel_tools, calls in ((False, tool_calls[:1]), (True, tool_calls)):
            engine = AgentEngine(
                SimpleNamespace(id="tenant-1"),
                "session-1",
                agent_config={
                    "allowed_tools": ["test_tool"],
                    "knowledge_base_ids": ["kb-1"],
                    "max_rounds": 2,
                    "parallel_tool_calls": parallel_tools,
                },
            )
            engine.registry = _EventRegistry()
            engine._call_llm_with_tools = Mock(
                side_effect=[
                    {"content": "", "tool_calls": calls},
                    {"content": "complete", "tool_calls": None},
                ]
            )
            events = []

            with (
                patch(
                    "personal_knowledge_base.observability.trace_agent_execution",
                    return_value=nullcontext(SimpleNamespace(metadata={})),
                ),
                patch(
                    "personal_knowledge_base.observability.trace_llm_call",
                    return_value=nullcontext({}),
                ),
            ):
                engine.execute("query", on_event=lambda event_type, data: events.append((event_type, data)))

            tool_results = [data for event_type, data in events if event_type == "tool_result"]
            self.assertEqual(len(tool_results), len(calls))
            for data in tool_results:
                self.assertEqual(len(data["output"]), 800)
                self.assertEqual(data["error"], "tool failed")
                self.assertIn(data["tool_call_id"], {call["id"] for call in calls})
                self.assertEqual(data["duration_ms"], 73)

    def test_tool_result_keeps_identity_error_and_full_output(self):
        payload = tool_stream_payload(
            "tool_result",
            "assistant-1",
            {
                "tool_call_id": "call-1",
                "name": "database_query",
                "output": "x" * 800,
                "error": "query failed",
                "duration_ms": 7,
                "iteration": 2,
            },
        )

        self.assertEqual(payload["tool_call_id"], "call-1")
        self.assertEqual(payload["error"], "query failed")
        self.assertEqual(len(payload["output"]), 800)

    @patch("chat.views.CONTINUE_STREAM_MAX_WAIT_SECONDS", 0)
    def test_continue_stream_timeout_persists_terminal_error(self):
        response = self.client.get(self.continue_url, **self.headers)

        b"".join(response.streaming_content)

        self.message.refresh_from_db()
        self.assertTrue(self.message.is_completed)
        self.assertEqual(self.message.content, "等待超时")

    def test_continue_stream_missing_stream_persists_terminal_error(self):
        stream_manager.remove_stream(self.message.id)

        response = self.client.get(self.continue_url, **self.headers)
        body = b"".join(response.streaming_content).decode("utf-8")

        self.message.refresh_from_db()
        self.assertTrue(self.message.is_completed)
        self.assertEqual(self.message.content, "生成失败")
        self.assertIn("生成失败", body)

    def test_agent_stream_is_registered_before_active_and_legacy_workers_start(self):
        active_session = Session.objects.create(tenant=self.tenant, title="Active startup")
        active_request_id = "active-startup"
        with patch("chat.views.run_database_background") as run_background:
            response = self.client.post(
                f"/api/v1/agent-chat/{active_session.id}",
                data=json.dumps({"query": "你好", "stream": True, "enable_memory": False}),
                content_type="application/json",
                HTTP_ACCEPT="text/event-stream",
                HTTP_X_REQUEST_ID=active_request_id,
                **self.headers,
            )

        self.assertEqual(response.status_code, 200)
        run_background.assert_called_once()
        active_message = Message.objects.get(session=active_session, request_id=active_request_id, role="assistant")
        self.assertIsNotNone(stream_manager.get_stream(active_message.id))

        legacy_session = Session.objects.create(tenant=self.tenant, title="Legacy startup")
        legacy_request_id = "legacy-startup"
        request = RequestFactory().post(
            f"/api/v1/agent-chat/{legacy_session.id}",
            data=json.dumps({"query": "你好", "stream": True, "enable_memory": False}),
            content_type="application/json",
            HTTP_AUTHORIZATION=self.headers["HTTP_AUTHORIZATION"],
            HTTP_ACCEPT="text/event-stream",
            HTTP_X_REQUEST_ID=legacy_request_id,
        )
        with patch("personal_knowledge_base.views.threading.Thread", _NoopThread):
            from personal_knowledge_base import views as legacy_views

            response = legacy_views.chat_endpoint(request, legacy_session.id, agent=True)

        self.assertEqual(response.status_code, 200)
        legacy_message = Message.objects.get(session=legacy_session, request_id=legacy_request_id, role="assistant")
        self.assertIsNotNone(stream_manager.get_stream(legacy_message.id))

        stream_manager.remove_stream(active_message.id)
        stream_manager.remove_stream(legacy_message.id)

    def test_agent_workers_reuse_streams_created_at_startup(self):
        from chat import views as active_views
        from personal_knowledge_base import views as legacy_views

        for views_module in (active_views, legacy_views):
            message = Message.objects.create(
                session=self.session,
                request_id=f"worker-{views_module.__name__}",
                role="assistant",
                content="",
                rendered_content="",
                is_completed=False,
            )
            stream = stream_manager.create_stream(message.id, self.session.id)
            stream.append_event("thinking", {"content": "registered before worker"})
            engine_patch_target = (
                "chat.views.AgentEngine"
                if views_module is active_views
                else "personal_knowledge_base.agent_engine.AgentEngine"
            )

            with (
                patch(engine_patch_target, _ImmediateAgentEngine),
                patch.object(views_module, "schedule_chat_maintenance"),
            ):
                views_module._run_agent_generation(
                    assistant_msg_id=message.id,
                    session_id=self.session.id,
                    user_msg_id="user-1",
                    query="query",
                    history_msgs=[],
                    agent_context="",
                    agent_config={},
                    refs=[],
                    tenant=self.tenant,
                    user_id=self.user.id,
                    enable_memory=False,
                )

            self.assertIs(stream_manager.get_stream(message.id), stream)
            self.assertEqual(stream.get_events()[0].data["content"], "registered before worker")
            stream_manager.remove_stream(message.id)
