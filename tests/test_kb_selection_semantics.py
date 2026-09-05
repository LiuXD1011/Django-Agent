"""知识库选择语义测试：显式空选择、字段缺失回退、多选完整性。

背景 bug：`kb_ids = data.get("knowledge_base_ids") or [session.knowledge_base_id]`
把"显式取消全部选择"（空数组）与"字段缺失"混为一谈，导致：
1. 用户取消全部选择后被会话绑定的旧知识库静默顶回；
2. 多选 [A, B] 在回退路径下只保留单值绑定字段的第一个，B 被静默丢弃。

修复后的语义（chat/views.py chat_endpoint）：
1. 请求显式携带 knowledge_base_ids（含空数组）→ 尊重用户选择；
2. 字段缺失 → 回退 agent_config.knowledge_base_ids（完整多选列表）；
3. 仍无 → 回退单值绑定字段 session.knowledge_base_id。
"""

from pathlib import Path
import json
import sys
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from unittest.mock import patch  # noqa: E402

from django.test import Client, TestCase, override_settings  # noqa: E402

from personal_knowledge_base.authentication import hash_password, issue_tokens  # noqa: E402
from personal_knowledge_base.agent_engine import AgentResult  # noqa: E402
from personal_knowledge_base.models import KnowledgeBase, Tenant, TenantMember, User  # noqa: E402


@override_settings(APP_TASKS_SYNC=True)
class KnowledgeBaseSelectionSemanticsTests(TestCase):
    """通过 agent-chat 端点断言传给 AgentEngine 的 knowledge_base_ids。"""

    def setUp(self):
        self.tenant = Tenant.objects.create(name=_unique("kbsel"), api_key=_unique("key"))
        self.kb_a = KnowledgeBase.objects.create(tenant=self.tenant, name="KB-A")
        self.kb_b = KnowledgeBase.objects.create(tenant=self.tenant, name="KB-B")
        self.user = User.objects.create(
            username=_unique("kbsel_user"),
            email=f"{_unique('kbsel')}@example.test",
            password_hash=hash_password("test-password"),
            tenant=self.tenant,
            preferences={"enable_memory": False},
        )
        TenantMember.objects.create(user=self.user, tenant=self.tenant, role="owner")
        token, _refresh = issue_tokens(self.user)
        self.client = Client()
        self.client.raise_request_exception = False
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

        self.captured: dict = {}
        test_case = self

        class ScriptedEngine:
            def __init__(self, *args, **kwargs):
                # 捕获构造参数（含 agent_config.knowledge_base_ids）供断言
                test_case.captured["agent_config"] = kwargs.get("agent_config") or {}

            def execute(self, query, history=None, context_str="", on_event=None, request_id=""):
                return AgentResult(content="ok", steps=[], total_iterations=1, duration_ms=5, stopped_reason="completed")

        engine_patcher = patch("chat.views.AgentEngine", ScriptedEngine)
        engine_patcher.start()
        self.addCleanup(engine_patcher.stop)
        for target, value in (
            ("chat.views.is_memory_available", False),
            ("chat.views.role_completion", "标题"),
            ("chat.views.schedule_chat_maintenance", None),
        ):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _create_session(self, *, knowledge_base_id="", agent_config=None):
        payload = {"title": "选择语义会话"}
        if knowledge_base_id:
            payload["knowledge_base_id"] = knowledge_base_id
        if agent_config is not None:
            payload["agent_config"] = agent_config
        response = self.client.post(
            "/api/v1/sessions",
            data=json.dumps(payload),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 201, response.content.decode())
        return response.json()["data"]["id"]

    def _send(self, session_id, payload):
        response = self.client.post(
            f"/api/v1/agent-chat/{session_id}",
            data=json.dumps({"query": "测试", "stream": False, "enable_memory": False, **payload}),
            content_type="application/json",
            HTTP_ACCEPT="text/event-stream",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        b"".join(response.streaming_content)
        return self.captured.get("agent_config", {}).get("knowledge_base_ids")

    def test_explicit_empty_selection_respected_not_overridden(self):
        """显式取消全部选择（空数组）→ 不回退会话绑定的旧知识库。"""
        session_id = self._create_session(knowledge_base_id=str(self.kb_a.id))
        sent_kb_ids = self._send(session_id, {"knowledge_base_ids": []})
        self.assertEqual(sent_kb_ids, [])

    def test_explicit_multi_selection_passes_through_complete(self):
        """显式多选 [A, B] → 完整传递，不丢第二个。"""
        session_id = self._create_session()
        ids = [str(self.kb_a.id), str(self.kb_b.id)]
        sent_kb_ids = self._send(session_id, {"knowledge_base_ids": ids})
        self.assertEqual(sent_kb_ids, ids)

    def test_missing_field_falls_back_to_full_multi_selection(self):
        """字段缺失（旧客户端）→ 回退 agent_config 里的完整多选列表，而非单值字段。"""
        session_id = self._create_session(
            knowledge_base_id=str(self.kb_a.id),
            agent_config={"knowledge_base_ids": [str(self.kb_a.id), str(self.kb_b.id)]},
        )
        payload = {"query": "测试", "stream": False, "enable_memory": False}
        response = self.client.post(
            f"/api/v1/agent-chat/{session_id}",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_ACCEPT="text/event-stream",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        b"".join(response.streaming_content)
        sent_kb_ids = self.captured.get("agent_config", {}).get("knowledge_base_ids")
        self.assertEqual(sent_kb_ids, [str(self.kb_a.id), str(self.kb_b.id)])

    def test_missing_field_falls_back_to_single_bound_kb(self):
        """字段缺失且无多选配置 → 退会话创建时绑定的单值字段。"""
        session_id = self._create_session(knowledge_base_id=str(self.kb_a.id))
        payload = {"query": "测试", "stream": False, "enable_memory": False}
        response = self.client.post(
            f"/api/v1/agent-chat/{session_id}",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_ACCEPT="text/event-stream",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        b"".join(response.streaming_content)
        sent_kb_ids = self.captured.get("agent_config", {}).get("knowledge_base_ids")
        self.assertEqual(sent_kb_ids, [str(self.kb_a.id)])


def _unique(name: str) -> str:
    return f"{name}-{uuid4().hex[:10]}"


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
