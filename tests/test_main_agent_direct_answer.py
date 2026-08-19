#!/usr/bin/env python
import json
import os
import sys
import time
import unittest
from pathlib import Path
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


class FakeRAGContext:
    intent = "kb_search"
    search_query = "你好"
    refs = []
    memory_context = ""
    chat_history_context = ""
    system_prompt = "测试 system prompt"
    user_prompt = "你好"
    kb_names = ""


def fake_rag_pipeline(*_args, **_kwargs):
    return FakeRAGContext()


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


@override_settings(
    ALLOWED_HOSTS=["testserver"],
    LLM_USE_ENV_CHAT=False,
    LLM_USE_ENV_TITLE=False,
    LLM_USE_ENV_QUESTION=False,
    LLM_USE_ENV_EXTRACT=False,
    LLM_USE_ENV_EMBEDDING=False,
    LLM_USE_ENV_RERANK=False,
)
class MainAgentDirectAnswerTests(TransactionTestCase):
    def setUp(self):
        from personal_knowledge_base.authentication import hash_password, issue_tokens
        from personal_knowledge_base.models import Tenant, TenantMember, User

        suffix = uuid4().hex[:10]
        self.tenant = Tenant.objects.create(name=f"direct-answer-{suffix}", api_key=f"direct-key-{suffix}")
        self.user = User.objects.create(
            username=f"direct_user_{suffix}",
            email=f"direct_user_{suffix}@example.test",
            password_hash=hash_password("test-password"),
            tenant=self.tenant,
            preferences={"enable_memory": True},
        )
        TenantMember.objects.create(user=self.user, tenant=self.tenant, role="owner")
        token, _refresh = issue_tokens(self.user)
        self.client = Client()
        self.auth_headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        self.stream_ids = []

    def tearDown(self):
        from personal_knowledge_base.stream_manager import stream_manager

        for stream_id in self.stream_ids:
            stream_manager.remove_stream(stream_id)

    def create_session(self, title="新的对话"):
        from personal_knowledge_base.models import KnowledgeBase, Session

        kb = KnowledgeBase.objects.create(
            tenant=self.tenant,
            name="直接回答测试知识库",
            description="用于验证简单寒暄不会触发重链路",
            creator_id=self.user.id,
        )
        session = Session.objects.create(
            tenant=self.tenant,
            user_id=self.user.id,
            title=title,
            knowledge_base_id=kb.id,
            agent_config={"agent_enabled": True, "knowledge_base_ids": [kb.id]},
        )
        return session, kb

    def post_json(self, path, payload, accept=None):
        headers = dict(self.auth_headers)
        if accept:
            headers["HTTP_ACCEPT"] = accept
        return self.client.post(path, data=json.dumps(payload), content_type="application/json", **headers)

    def test_hello_stream_uses_main_agent_without_heavy_pipeline(self):
        from personal_knowledge_base.agent_engine import AgentResult
        from personal_knowledge_base.models import Message

        session, kb = self.create_session()
        with patch("personal_knowledge_base.rag_pipeline.run_rag_pipeline") as rag, patch(
            "chat.views.retrieve_memory"
        ) as retrieve_memory, patch("chat.views.AgentEngine.execute") as agent_execute, patch(
            "chat.views.schedule_title_generation"
        ) as schedule_title:
            agent_execute.return_value = AgentResult(
                content="你好！我是主 Agent，有什么可以帮你？",
                steps=[],
                total_iterations=1,
                duration_ms=12,
                stopped_reason="completed",
            )
            response = self.post_json(
                f"/api/v1/agent-chat/{session.id}",
                {
                    "query": "你好",
                    "stream": True,
                    "agent_enabled": True,
                    "knowledge_base_ids": [kb.id],
                    "enable_memory": True,
                },
                accept="text/event-stream",
            )
            body = b"".join(response.streaming_content).decode("utf-8")

        frames = parse_sse(body)
        response_types = [frame["data"].get("response_type") for frame in frames if isinstance(frame["data"], dict)]
        assistant = Message.objects.filter(session=session, role="assistant").order_by("-created_at").first()
        self.stream_ids.append(assistant.id)

        self.assertEqual(response.status_code, 200)
        self.assertIn("message_start", [frame["event"] for frame in frames])
        self.assertIn("answer", response_types)
        self.assertIn("complete", response_types)
        self.assertIn("done", [frame["event"] for frame in frames])
        self.assertTrue(assistant.is_completed)
        self.assertIn("你好", assistant.content)
        self.assertNotEqual((assistant.agent_steps or [{}])[0].get("type"), "main_agent_lightweight")
        self.assertTrue(agent_execute.called)
        self.assertFalse(rag.called)
        self.assertFalse(retrieve_memory.called)
        self.assertTrue(schedule_title.called)

    def test_expensive_prefetch_skip_guard_is_only_for_simple_requests(self):
        session, kb = self.create_session("已命名会话")
        cases = [
            {"images": [{"url": "data:image/png;base64,abc"}]},
            {"attachment_uploads": [{"file_name": "a.txt", "file_size": 12}]},
            {"web_search_enabled": True},
            {"mcp_service_ids": ["svc-1"]},
            {"mentioned_items": [{"id": "file-1", "type": "file", "name": "a.txt"}]},
        ]

        import personal_knowledge_base.chat_runtime as chat_runtime

        self.assertTrue(
            chat_runtime.should_skip_expensive_prefetch(
                "你好",
                {"query": "你好", "knowledge_base_ids": [kb.id]},
            )
        )
        for extra in cases:
            payload = {
                "query": "你好",
                "stream": True,
                "agent_enabled": True,
                "knowledge_base_ids": [kb.id],
                **extra,
            }
            self.assertFalse(chat_runtime.should_skip_expensive_prefetch("你好", payload), extra)

        self.assertFalse(
            chat_runtime.should_skip_expensive_prefetch(
                "我的知识库有哪些内容",
                {"query": "我的知识库有哪些内容", "knowledge_base_ids": [kb.id]},
            )
        )
        self.assertFalse(
            chat_runtime.should_skip_expensive_prefetch(
                "Agent 流式问题",
                {"query": "Agent 流式问题", "knowledge_base_ids": [kb.id]},
            )
        )
        self.assertFalse(hasattr(chat_runtime, "run_lightweight_main_agent"))

    def test_knowledge_question_enters_main_agent_without_rag_prefetch(self):
        from personal_knowledge_base.agent_engine import AgentResult
        from personal_knowledge_base.models import Message

        session, kb = self.create_session()
        captured = {}
        def fake_execute(query, history=None, context_str="", on_event=None):
            captured["query"] = query
            captured["history"] = history
            captured["context_str"] = context_str
            return AgentResult(
                content="主 Agent 会通过 actor 检索知识库内容",
                steps=[],
                total_iterations=1,
                duration_ms=12,
                stopped_reason="completed",
            )

        with patch("personal_knowledge_base.rag_pipeline.run_rag_pipeline", side_effect=fake_rag_pipeline) as rag, patch(
            "chat.views.AgentEngine.execute",
            side_effect=fake_execute,
        ) as agent_execute:
            response = self.post_json(
                f"/api/v1/agent-chat/{session.id}",
                {
                    "query": "我的知识库有哪些内容",
                    "stream": False,
                    "agent_enabled": True,
                    "knowledge_base_ids": [kb.id],
                    "enable_memory": False,
                },
            )

        assistant = Message.objects.filter(session=session, role="assistant").order_by("-created_at").first()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["answer"], "主 Agent 会通过 actor 检索知识库内容")
        self.assertEqual(assistant.content, "主 Agent 会通过 actor 检索知识库内容")
        self.assertFalse(rag.called)
        self.assertTrue(agent_execute.called)
        self.assertIn("当前知识库", captured["context_str"])
        self.assertIn("直接回答测试知识库", captured["context_str"])

    def test_stream_answer_is_not_blocked_by_background_title_generation(self):
        from personal_knowledge_base.agent_engine import AgentResult

        session, kb = self.create_session()

        def slow_title(*_args, **_kwargs):
            time.sleep(1.5)
            return "慢标题"

        with patch("personal_knowledge_base.chat_runtime.role_completion", side_effect=slow_title), patch(
            "chat.views.AgentEngine.execute",
            return_value=AgentResult(
                content="你好！我是主 Agent。",
                steps=[],
                total_iterations=1,
                duration_ms=12,
                stopped_reason="completed",
            ),
        ):
            start = time.perf_counter()
            response = self.post_json(
                f"/api/v1/agent-chat/{session.id}",
                {
                    "query": "你好",
                    "stream": True,
                    "agent_enabled": True,
                    "knowledge_base_ids": [kb.id],
                },
                accept="text/event-stream",
            )
            body = b"".join(response.streaming_content).decode("utf-8")
            elapsed_ms = int((time.perf_counter() - start) * 1000)

        frames = parse_sse(body)
        response_types = [frame["data"].get("response_type") for frame in frames if isinstance(frame["data"], dict)]
        self.assertEqual(response.status_code, 200)
        self.assertIn("complete", response_types)
        self.assertLess(elapsed_ms, 1000)


def main():
    setup_test_environment()
    runner = DiscoverRunner(verbosity=0, interactive=False)
    old_config = runner.setup_databases()
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(MainAgentDirectAnswerTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    finally:
        runner.teardown_databases(old_config)
        teardown_test_environment()


if __name__ == "__main__":
    raise SystemExit(main())
