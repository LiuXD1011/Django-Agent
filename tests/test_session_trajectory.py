"""会话事件溯源测试：事件层完整性、折叠纯度、投影重建、租户隔离。

设计依据 docs/trajectory-event-sourcing.md。
"""

from pathlib import Path
import json
from unittest.mock import patch
import sys
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.test import Client, TestCase, override_settings  # noqa: E402

from personal_knowledge_base import event_log  # noqa: E402
from personal_knowledge_base.models import Message, Session, SessionEvent, Tenant  # noqa: E402

def _unique(name: str) -> str:
    return f"{name}-{uuid4().hex[:10]}"

class EventStoreTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name=_unique("evtest"), api_key=_unique("key"))
        self.session = Session.objects.create(tenant=self.tenant, title="轨迹测试会话")

    def test_seq_monotonic_and_gapless(self):
        for i in range(1, 6):
            event = event_log.append_event(self.session, "req-1", event_log.AGENT_ITERATION, {"iteration": i})
            self.assertIsNotNone(event)
            self.assertEqual(event.seq, i)
        seqs = list(SessionEvent.objects.filter(session=self.session).order_by("seq").values_list("seq", flat=True))
        self.assertEqual(seqs, [1, 2, 3, 4, 5])
        self.assertEqual(Session.objects.get(pk=self.session.pk).event_seq, 5)

    def test_unknown_type_rejected(self):
        event = event_log.append_event(self.session, "req-1", "bogus/type", {"x": 1})
        self.assertIsNone(event)
        self.assertEqual(SessionEvent.objects.filter(session=self.session).count(), 0)

    def test_data_frozen_against_caller_mutation(self):
        data = {"content": "hello", "nested": {"a": [1, 2]}}
        event = event_log.append_event(self.session, "req-1", event_log.TURN_USER_MESSAGE, data)
        assert event is not None
        data["content"] = "mutated"
        data["nested"]["a"].append(3)
        event.refresh_from_db()
        self.assertEqual(event.data["content"], "hello")
        self.assertEqual(event.data["nested"]["a"], [1, 2])

    def test_non_json_values_degraded(self):
        event = event_log.append_event(self.session, "req-1", event_log.TURN_USER_MESSAGE, {"obj": object()})
        assert event is not None
        self.assertIsInstance(event.data["obj"], str)

    def test_append_failure_never_raises(self):
        # 不存在的会话主键模拟底层失败路径：append 必须返回 None 而非抛异常
        ghost = Session(pk="ghost-session", tenant=self.tenant, title="ghost")
        self.assertIsNone(event_log.append_event(ghost, "req-1", event_log.TURN_USER_MESSAGE, {}))

class FoldTrajectoryTests(TestCase):
    def _events(self):
        self.tenant = Tenant.objects.create(name=_unique("fold"), api_key=_unique("key"))
        self.session = Session.objects.create(tenant=self.tenant, title="fold")
        specs = [
            ("req-1", event_log.SESSION_STARTED, {"title": "fold"}),
            ("req-1", event_log.TURN_USER_MESSAGE, {"content": "什么是RAG?", "images": [], "attachments": [], "mentioned_items": [], "channel": "web"}),
            ("req-1", event_log.TURN_ASSISTANT_CREATED, {"mode": "agent", "model_id": "glm-test", "channel": "web"}),
            ("req-1", event_log.REQUEST_HEADER, {"model": "glm-test", "temperature": 0.7, "allowed_tools": ["knowledge_search", "grep_chunks"], "tool_schemas": [{"name": "knowledge_search", "description": "Search KB", "required": ["query"], "properties": {"query": "string"}}], "max_iterations": 5, "history_messages": 6, "agent_mode": "multi_agent"}),
            ("req-1", event_log.RETRIEVAL_SEARCH, {"query": "RAG", "kb_ids": ["kb1"], "top_k": 5}),
            ("req-1", event_log.RETRIEVAL_RESULT, {"count": 3, "intent": "kb_search", "degradations": [], "refs": [{"chunk_id": "c1", "knowledge_title": "RAG论文"}]}),
            ("req-1", event_log.CONTEXT_COMPACTED, {"before_tokens": 90000, "after_tokens": 52000, "iteration": 1}),
            ("req-1", event_log.AGENT_ITERATION, {"iteration": 1}),
            ("req-1", event_log.LLM_RETRY, {"attempt": 1, "max_retries": 3, "reason": "rate limit", "wait_seconds": 2}),
            ("req-1", event_log.AGENT_THINKING, {"iteration": 1, "content": "先检索", "duration_ms": 800, "usage": {"prompt_tokens": 100, "completion_tokens": 20}, "model": "glm-test"}),
            ("req-1", event_log.TOOL_CALL, {"iteration": 1, "tool_call_id": "tc1", "name": "knowledge_search", "argument_keys": ["query"]}),
            ("req-1", event_log.TOOL_RESULT, {"iteration": 1, "tool_call_id": "tc1", "name": "knowledge_search", "output": "found stuff", "error": "", "duration_ms": 120}),
            ("req-1", event_log.TURN_COMPLETED, {"content": "RAG 是检索增强生成", "stopped_reason": "completed", "duration_ms": 5000}),
        ]
        for request_id, event_type, data in specs:
            event_log.append_event(self.session, request_id, event_type, data)
        return list(SessionEvent.objects.filter(session=self.session).order_by("seq"))

    def test_fold_shape(self):
        turns = event_log.fold_trajectory(self._events())["turns"]
        self.assertEqual(len(turns), 1)
        turn = turns[0]
        self.assertEqual(turn["user"]["content"], "什么是RAG?")
        self.assertEqual(turn["assistant"]["content"], "RAG 是检索增强生成")
        self.assertEqual(turn["stopped_reason"], "completed")
        self.assertEqual(turn["duration_ms"], 5000)
        self.assertEqual(turn["retrievals"][0]["count"], 3)
        self.assertEqual(turn["retrievals"][0]["refs"][0]["title"], "RAG论文")
        self.assertEqual(len(turn["steps"]), 1)
        step = turn["steps"][0]
        self.assertEqual(step["thought"], "先检索")
        self.assertEqual(step["tools"][0]["name"], "knowledge_search")
        self.assertEqual(step["llm"]["duration_ms"], 800)
        self.assertEqual(turn["usage"]["prompt_tokens"], 100)
        self.assertEqual(turn["usage"]["completion_tokens"], 20)
        self.assertEqual(turn["usage"]["total_tokens"], 120)
        self.assertEqual(turn["usage"]["llm_calls"], 1)
        self.assertEqual(turn["model_id"], "glm-test")
        # 新增：请求上下文 / 重试 / 压缩 / 真实时间 span
        self.assertEqual(turn["request"]["tools"], ["knowledge_search", "grep_chunks"])
        self.assertEqual(turn["request"]["max_iterations"], 5)
        self.assertEqual(turn["request"]["temperature"], 0.7)
        self.assertEqual(turn["request"]["tool_schemas"]["knowledge_search"]["description"], "Search KB")
        self.assertEqual(turn["retries"][0]["reason"], "rate limit")
        self.assertEqual(turn["compactions"][0]["before_tokens"], 90000)
        self.assertEqual(turn["compactions"][0]["after_tokens"], 52000)
        step = turn["steps"][0]
        self.assertIsNotNone(step["started_at"])
        self.assertIsNotNone(step["ended_at"])
        self.assertLessEqual(step["started_at"], step["ended_at"])
        self.assertEqual(step["llm"]["usage"], {"prompt_tokens": 100, "completion_tokens": 20, "cached_tokens": 0, "reasoning_tokens": 0})
        self.assertIsNotNone(step["tools"][0]["started_at"])
        self.assertIsNotNone(step["tools"][0]["ended_at"])
        self.assertEqual(step["tools"][0]["schema"]["description"], "Search KB")

    def test_fold_is_pure(self):
        events = self._events()
        self.assertEqual(event_log.fold_trajectory(events), event_log.fold_trajectory(events))

class ProjectionRebuildTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name=_unique("proj"), api_key=_unique("key"))
        self.session = Session.objects.create(tenant=self.tenant, title="proj")
        self.request_id = _unique("req")
        event_log.append_event(self.session, self.request_id, event_log.TURN_USER_MESSAGE, {
            "content": "帮我查 RAG", "images": [], "attachments": [], "mentioned_items": [], "channel": "web",
        })
        event_log.append_event(self.session, self.request_id, event_log.RETRIEVAL_RESULT, {
            "count": 2, "intent": "kb_search", "degradations": [],
            "refs": [{"chunk_id": "c9", "knowledge_title": "检索九号"}],
        })
        event_log.append_event(self.session, self.request_id, event_log.TURN_COMPLETED, {
            "content": "RAG 即检索增强生成", "stopped_reason": "completed", "duration_ms": 4200,
        })

    def test_rebuild_restores_messages(self):
        result = event_log.rebuild_projection(str(self.session.pk))
        self.assertEqual(result["turns_rebuilt"], 1)
        messages = list(Message.objects.filter(session=self.session).order_by("created_at"))
        self.assertEqual([m.role for m in messages], ["user", "assistant"])
        self.assertEqual(messages[0].content, "帮我查 RAG")
        self.assertEqual(messages[1].content, "RAG 即检索增强生成")
        self.assertEqual(messages[1].agent_duration_ms, 4200)
        self.assertTrue(messages[1].is_completed)
        self.assertFalse(messages[1].is_fallback)
        self.assertEqual(messages[1].request_id, self.request_id)

    def test_rebuild_preserves_untraceable_messages(self):
        # 存量无事件消息不应被重建逻辑触碰
        orphan = Message.objects.create(session=self.session, request_id="legacy", role="user", content="旧消息")
        event_log.rebuild_projection(str(self.session.pk))
        self.assertTrue(Message.objects.filter(pk=orphan.pk).exists())

    def test_error_turn_projects_as_fallback(self):
        error_request = _unique("req-err")
        event_log.append_event(self.session, error_request, event_log.TURN_USER_MESSAGE, {
            "content": "会失败的问题", "images": [], "attachments": [], "mentioned_items": [], "channel": "web",
        })
        event_log.append_event(self.session, error_request, event_log.TURN_ERROR, {"message": "生成失败", "stage": "llm"})
        event_log.rebuild_projection(str(self.session.pk))
        assistant = Message.objects.filter(session=self.session, request_id=error_request, role="assistant").first()
        self.assertIsNotNone(assistant)
        self.assertTrue(assistant.is_fallback)
        self.assertIn("生成失败", assistant.content)

class TrajectoryApiTests(TestCase):
    def setUp(self):
        from personal_knowledge_base.authentication import hash_password, issue_tokens
        from personal_knowledge_base.models import TenantMember, User

        self.tenant = Tenant.objects.create(name=_unique("api"), api_key=_unique("key"))
        self.other_tenant = Tenant.objects.create(name=_unique("api2"), api_key=_unique("key"))
        self.user = User.objects.create(
            username=_unique("traj_user"),
            email=f"{_unique('traj')}@example.test",
            password_hash=hash_password("test-password"),
            tenant=self.tenant,
            preferences={"enable_memory": False},
        )
        TenantMember.objects.create(user=self.user, tenant=self.tenant, role="owner")
        token, _refresh = issue_tokens(self.user)
        self.client = Client()
        self.client.raise_request_exception = False
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        self.session = Session.objects.create(tenant=self.tenant, title="api 会话", user_id=str(self.user.id))
        event_log.append_event(self.session, "req-a", event_log.TURN_USER_MESSAGE, {
            "content": "租户 A 的问题", "images": [], "attachments": [], "mentioned_items": [], "channel": "web",
        })
        event_log.append_event(self.session, "req-a", event_log.TURN_COMPLETED, {
            "content": "租户 A 的回答", "stopped_reason": "completed", "duration_ms": 900,
        })

    def test_trajectory_returns_folded_turns(self):
        response = self.client.get(f"/api/v1/sessions/{self.session.id}/trajectory", **self.headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertEqual(payload["session_id"], str(self.session.id))
        self.assertEqual(len(payload["turns"]), 1)
        self.assertEqual(payload["turns"][0]["user"]["content"], "租户 A 的问题")
        self.assertEqual(payload["turns"][0]["assistant"]["content"], "租户 A 的回答")

    def test_events_endpoint_pagination(self):
        response = self.client.get(
            f"/api/v1/sessions/{self.session.id}/events",
            {"after_seq": 1, "limit": 1},
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["seq"], 2)
        self.assertEqual(payload["next_after_seq"], 2)

    def test_tenant_isolation_hides_other_tenant_session(self):
        # 第二个租户的合法用户访问第一个租户的会话 → 404
        from personal_knowledge_base.authentication import hash_password, issue_tokens
        from personal_knowledge_base.models import TenantMember, User

        outsider = User.objects.create(
            username=_unique("outsider"),
            email=f"{_unique('out')}@example.test",
            password_hash=hash_password("test-password"),
            tenant=self.other_tenant,
            preferences={"enable_memory": False},
        )
        TenantMember.objects.create(user=outsider, tenant=self.other_tenant, role="owner")
        token, _refresh = issue_tokens(outsider)
        foreign = Client()
        foreign.raise_request_exception = False

        response = foreign.get(f"/api/v1/sessions/{self.session.id}/trajectory", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(response.status_code, 404)
        response = foreign.get(f"/api/v1/sessions/{self.session.id}/events", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(response.status_code, 404)

    def test_anonymous_rejected(self):
        anonymous = Client()
        anonymous.raise_request_exception = False
        response = anonymous.get(f"/api/v1/sessions/{self.session.id}/trajectory")
        self.assertIn(response.status_code, (401, 403))



@override_settings(APP_TASKS_SYNC=True)
class AgentChatTrajectoryIntegrationTests(TestCase):
    """全链路：agent-chat 端点 + 伪引擎发流事件 → 事件落库 → 轨迹折叠可读。

    APP_TASKS_SYNC=True 让 run_database_background 内联执行生成线程，
    测试中不需要真实线程与流式轮询等待。
    """

    def setUp(self):
        from personal_knowledge_base.authentication import hash_password, issue_tokens
        from personal_knowledge_base.models import TenantMember, User
        from unittest.mock import patch

        self.tenant = Tenant.objects.create(name=_unique("chain"), api_key=_unique("key"))
        self.user = User.objects.create(
            username=_unique("chain_user"),
            email=f"{_unique('chain')}@example.test",
            password_hash=hash_password("test-password"),
            tenant=self.tenant,
            preferences={"enable_memory": False},
        )
        TenantMember.objects.create(user=self.user, tenant=self.tenant, role="owner")
        token, _refresh = issue_tokens(self.user)
        self.client = Client()
        self.client.raise_request_exception = False
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

        self.patchers = [
            patch("chat.views.is_memory_available", return_value=False),
            patch("chat.views.role_completion", return_value="测试标题"),
            patch("chat.views.schedule_chat_maintenance"),
        ]
        self.mocks = [p.start() for p in self.patchers]
        for patcher in self.patchers:
            self.addCleanup(patcher.stop)

    def test_agent_turn_produces_complete_event_sequence(self):
        from personal_knowledge_base.agent_engine import AgentResult
        from personal_knowledge_base.models import SessionEvent

        create = self.client.post(
            "/api/v1/sessions",
            data=json.dumps({"title": "链路会话"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(create.status_code, 201)
        session_id = create.json()["data"]["id"]

        class ScriptedEngine:
            def __init__(self, *args, **kwargs):
                pass

            def execute(self, query, history=None, context_str="", on_event=None, request_id=""):
                assert request_id, "request_id 必须传入引擎用于轨迹归组"
                emit = on_event if callable(on_event) else (lambda *_: None)
                # 迭代 1：模型只返回 tool_calls、文本为空（真实场景的常见形态），
                # 该次 LLM 调用仍必须留下轨迹（用量/时长/时间戳），否则时间轴缺段、token 少计
                emit("thinking", {
                    "iteration": 1, "content": "",
                    "duration_ms": 900,
                    "usage": {"prompt_tokens": 800, "completion_tokens": 10, "total_tokens": 810},
                })
                emit("tool_call", {"iteration": 1, "tool_call_id": "call-8", "name": "wiki_search", "arguments": {"query": "检索词"}})
                emit("tool_result", {"iteration": 1, "tool_call_id": "call-8", "name": "wiki_search", "output": "wiki 命中", "error": "", "duration_ms": 60})
                emit("thinking", {
                    "iteration": 2, "content": "这是最终回答",
                    "duration_ms": 640,
                    "usage": {"prompt_tokens": 88, "completion_tokens": 12, "total_tokens": 100},
                })
                return AgentResult(content="这是最终回答", steps=[], total_iterations=2, duration_ms=1500, stopped_reason="completed")

        with patch("chat.views.AgentEngine", ScriptedEngine):
            response = self.client.post(
                f"/api/v1/agent-chat/{session_id}",
                data=json.dumps({"query": "帮我查链路", "stream": True, "enable_memory": False}),
                content_type="application/json",
                HTTP_ACCEPT="text/event-stream",
                **self.headers,
            )
        self.assertEqual(response.status_code, 200)
        b"".join(response.streaming_content)

        events = list(SessionEvent.objects.filter(session_id=session_id).order_by("seq"))
        types = [e.type for e in events]
        self.assertEqual(types[0], event_log.SESSION_STARTED)
        self.assertEqual(types[1], event_log.TURN_USER_MESSAGE)
        self.assertIn(event_log.TURN_ASSISTANT_CREATED, types)
        # agent/iteration 由真实引擎内部发射；本测试 mock 掉引擎，故不断言
        self.assertIn(event_log.AGENT_THINKING, types)
        self.assertIn(event_log.TOOL_CALL, types)
        self.assertIn(event_log.TOOL_RESULT, types)
        self.assertEqual(types[-1], event_log.TURN_COMPLETED)
        seqs = [e.seq for e in events]
        self.assertEqual(seqs, list(range(1, len(seqs) + 1)))

        tool_call = next(e for e in events if e.type == event_log.TOOL_CALL)
        self.assertEqual(tool_call.data["argument_keys"], ["query"])
        self.assertNotIn("检索词", json.dumps(tool_call.data), "工具参数值不得入轨迹，只允许键名")

        trajectory = self.client.get(f"/api/v1/sessions/{session_id}/trajectory", **self.headers)
        self.assertEqual(trajectory.status_code, 200)
        turns = trajectory.json()["data"]["turns"]
        self.assertEqual(len(turns), 1)
        turn = turns[0]
        self.assertEqual(turn["assistant"]["content"], "这是最终回答")
        self.assertEqual(turn["stopped_reason"], "completed")
        self.assertEqual(turn["duration_ms"], 1500)
        # 两个迭代（含空内容迭代）都有步骤与 span
        self.assertEqual(len(turn["steps"]), 2)
        empty_step, final_step = turn["steps"]
        self.assertEqual(empty_step["iteration"], 1)
        self.assertEqual(empty_step["thought"], "")
        self.assertEqual(empty_step["llm"]["usage"], {"prompt_tokens": 800, "completion_tokens": 10, "cached_tokens": 0, "reasoning_tokens": 0})
        # started_at 由真实引擎的 agent/iteration 事件提供；本测试 mock 掉引擎，
        # 折叠层的 span 覆盖在 FoldTrajectoryTests 中断言
        self.assertIsNotNone(empty_step["ended_at"])
        self.assertEqual(empty_step["tools"][0]["name"], "wiki_search")
        # 用量跨迭代累计（修复回归：空内容迭代不得丢用量）
        self.assertEqual(turn["usage"]["prompt_tokens"], 888)
        self.assertEqual(turn["usage"]["completion_tokens"], 22)
        self.assertEqual(turn["usage"]["llm_calls"], 2)


if __name__ == "__main__":
    import unittest

    from django.test.runner import DiscoverRunner
    from django.test.utils import setup_test_environment, teardown_test_environment

    setup_test_environment()
    runner = DiscoverRunner(verbosity=1, interactive=False)
    old_config = runner.setup_databases()
    try:
        suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
        result = runner.run_suite(suite)
        exit_code = 0 if result.wasSuccessful() else 1
    finally:
        runner.teardown_databases(old_config)
    teardown_test_environment()
    sys.exit(exit_code)
