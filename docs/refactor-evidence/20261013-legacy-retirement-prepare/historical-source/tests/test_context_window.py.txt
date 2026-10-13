#!/usr/bin/env python
"""上下文窗口解析与占用查询的测试。

覆盖：
1. 解析链（参考 deepseek-harness 三级 fallback）：
   ModelConfig.context_window 覆盖 > 全局默认；env 直连模型/未知模型 → 默认。
2. compact_threshold：窗口 - 预留，且默认阈值与历史行为（120000）一致。
3. 引擎消费：agent_config.context_window 显式配置优先。
4. GET /sessions/{id}/context-usage 端点返回窗口、估算占用与百分比。
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.test import Client, TestCase, override_settings  # noqa: E402

from personal_knowledge_base.agent_engine import AgentEngine  # noqa: E402
from personal_knowledge_base.context_manager import (  # noqa: E402
    CONTEXT_RESERVE_TOKENS,
    DEFAULT_CONTEXT_WINDOW,
    compact_threshold,
)
from personal_knowledge_base.model_providers import resolve_model_context_window  # noqa: E402


class ResolveContextWindowTests(TestCase):
    def setUp(self):
        from personal_knowledge_base.models import ModelConfig, Tenant

        suffix = uuid4().hex[:10]
        self.tenant = Tenant.objects.create(name=f"ctx-{suffix}", api_key=f"ctx-key-{suffix}")
        self.custom = ModelConfig.objects.create(
            id=f"chat-custom-{suffix}",
            tenant=self.tenant,
            name="custom-ctx-model",
            type="chat",
            source="openai",
            context_window=32000,
        )
        self.default_only = ModelConfig.objects.create(
            id=f"chat-default-{suffix}",
            tenant=self.tenant,
            name="default-ctx-model",
            type="chat",
            source="openai",
            context_window=None,
        )

    def test_configured_model_returns_its_window(self):
        self.assertEqual(resolve_model_context_window(self.tenant, self.custom.id), 32000)

    def test_unconfigured_model_returns_global_default(self):
        self.assertEqual(resolve_model_context_window(self.tenant, self.default_only.id), DEFAULT_CONTEXT_WINDOW)

    def test_env_model_returns_global_default_without_db_lookup(self):
        # env 直连模型没有 ModelConfig 行，直接走默认
        self.assertEqual(resolve_model_context_window(self.tenant, "env-aliyun-bailian-knowledgeqa-qwen3.7-plus"), DEFAULT_CONTEXT_WINDOW)

    def test_unknown_model_returns_global_default(self):
        self.assertEqual(resolve_model_context_window(self.tenant, "no-such-model"), DEFAULT_CONTEXT_WINDOW)

    def test_invalid_configured_value_falls_back_to_default(self):
        self.custom.context_window = -5
        self.custom.save(update_fields=["context_window"])
        self.assertEqual(resolve_model_context_window(self.tenant, self.custom.id), DEFAULT_CONTEXT_WINDOW)


class CompactThresholdTests(unittest.TestCase):
    def test_default_window_matches_legacy_threshold(self):
        # 兼容性契约：默认窗口 - 预留 必须等于历史 MAX_CONTEXT_TOKENS=120000
        self.assertEqual(compact_threshold(DEFAULT_CONTEXT_WINDOW), 120000)
        self.assertEqual(compact_threshold(None), 120000)

    def test_custom_window_subtracts_reserve(self):
        self.assertEqual(compact_threshold(32000), 32000 - CONTEXT_RESERVE_TOKENS)

    def test_tiny_window_has_floor(self):
        self.assertEqual(compact_threshold(1000), 4096)


class EngineContextWindowTests(unittest.TestCase):
    def test_explicit_config_wins_without_db_lookup(self):
        with patch("personal_knowledge_base.model_providers.resolve_model_context_window") as resolver:
            engine = AgentEngine(tenant=None, session_id="s", agent_config={"context_window": 64000})
        self.assertEqual(engine.context_window, 64000)
        resolver.assert_not_called()

    def test_default_resolution_via_provider_chain(self):
        engine = AgentEngine(tenant=None, session_id="s", agent_config={"model_id": "m-1"})
        self.assertEqual(engine.context_window, DEFAULT_CONTEXT_WINDOW)


@override_settings(ALLOWED_HOSTS=["testserver"])
class ContextUsageEndpointTests(TestCase):
    def setUp(self):
        from personal_knowledge_base.models import Message, Session, Tenant

        suffix = uuid4().hex[:10]
        self.tenant = Tenant.objects.create(name=f"ctx-usage-{suffix}", api_key=f"ctx-usage-key-{suffix}")
        self.session = Session.objects.create(
            tenant=self.tenant,
            user_id="",
            title="ctx usage",
            agent_config={"model_id": "some-chat-model", "max_rounds": 8},
        )
        for i in range(2):
            # 与真实业务一致：一轮对话的 user/assistant 共享同一 request_id，
            # build_agent_history_messages 按 request_id 配对完整轮次
            Message.objects.create(
                session=self.session,
                request_id=f"req-{i}",
                role="user",
                content=f"测试提问 {i}，包含一些用于 token 估算的文本内容。",
                is_completed=True,
                agent_id="main",
                visible_to_user=True,
            )
            Message.objects.create(
                session=self.session,
                request_id=f"req-{i}",
                role="assistant",
                content=f"测试回答 {i}，这里是更长的回答正文，用于让 token 估算大于零。",
                is_completed=True,
                agent_id="main",
                visible_to_user=True,
            )
        self.client = Client()
        self.auth = {"HTTP_X_API_KEY": self.tenant.api_key}

    def test_endpoint_returns_window_and_estimated_usage(self):
        resp = self.client.get(f"/api/v1/sessions/{self.session.id}/context-usage", **self.auth)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()["data"]
        self.assertEqual(body["context_window"], DEFAULT_CONTEXT_WINDOW)
        self.assertEqual(body["compact_threshold"], 120000)
        self.assertEqual(body["model_id"], "some-chat-model")
        self.assertGreater(body["used_tokens"], 0)
        self.assertLessEqual(body["percent"], 100)

    def test_endpoint_honors_model_query_param_for_window(self):
        from personal_knowledge_base.models import ModelConfig

        ModelConfig.objects.create(
            id=f"chat-big-{uuid4().hex[:8]}",
            tenant=self.tenant,
            name="big-context-model",
            type="chat",
            source="openai",
            context_window=1000000,
        )
        model_id = ModelConfig.objects.filter(name="big-context-model").first().id
        resp = self.client.get(f"/api/v1/sessions/{self.session.id}/context-usage?model_id={model_id}", **self.auth)
        body = resp.json()["data"]
        self.assertEqual(body["context_window"], 1000000)

    def test_endpoint_requires_auth(self):
        resp = self.client.get(f"/api/v1/sessions/{self.session.id}/context-usage")
        self.assertIn(resp.status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()
