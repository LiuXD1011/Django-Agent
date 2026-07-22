"""LLM Provider 工厂测试：路由、隔离、缓存、降级。"""

import json
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from personal_knowledge_base.llm_providers import (
    BailianProvider,
    BaseLLMProvider,
    DeepSeekProvider,
    OpenAIProvider,
    ProviderConfig,
    ProviderFactory,
    QwenProvider,
    ZhipuProvider,
    factory,
)
from personal_knowledge_base.models import ModelConfig, Tenant


def _make_config(provider_name="openai", **kw):
    defaults = {
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-test",
        "model_name": "gpt-4o",
        "provider_name": provider_name,
    }
    defaults.update(kw)
    return ProviderConfig(**defaults)


class FactoryRoutingTests(TestCase):
    """AC #16, #20: 工厂根据 provider_name 路由到正确的 Provider 类。"""

    def test_create_openai_provider(self):
        provider = factory.create(_make_config("openai"))
        self.assertIsInstance(provider, OpenAIProvider)

    def test_create_deepseek_provider(self):
        provider = factory.create(_make_config("deepseek", base_url="https://api.deepseek.com/v1", model_name="deepseek-chat"))
        self.assertIsInstance(provider, DeepSeekProvider)

    def test_create_bailian_provider(self):
        provider = factory.create(_make_config("aliyun-bailian"))
        self.assertIsInstance(provider, BailianProvider)

    def test_create_qwen_provider(self):
        provider = factory.create(_make_config("qwen"))
        self.assertIsInstance(provider, QwenProvider)

    def test_create_zhipu_provider(self):
        provider = factory.create(_make_config("zhipu", model_name="glm-4"))
        self.assertIsInstance(provider, ZhipuProvider)

    def test_unknown_provider_falls_back_to_openai(self):
        provider = factory.create(_make_config("some-unknown-vendor"))
        self.assertIsInstance(provider, OpenAIProvider)

    def test_registry_contains_at_least_five_providers(self):
        names = factory.list_providers()
        for expected in ("openai", "deepseek", "aliyun-bailian", "qwen", "zhipu"):
            self.assertIn(expected, names)


class ProviderInstanceIsolationTests(TestCase):
    """AC #17: 不同 (tenant, model) 组合获得隔离的 Provider 实例。"""

    def test_different_models_return_different_instances(self):
        config_a = _make_config("openai", model_name="gpt-4o")
        config_b = _make_config("openai", model_name="gpt-4o-mini")
        provider_a = factory.get_or_create("tenant-1:model-a", config_a)
        provider_b = factory.get_or_create("tenant-1:model-b", config_b)
        self.assertIsNot(provider_a, provider_b)
        self.assertIsNot(provider_a.session, provider_b.session)

    def test_different_tenants_return_different_instances(self):
        config = _make_config("openai")
        provider_a = factory.get_or_create("tenant-1:model-x", config)
        provider_b = factory.get_or_create("tenant-2:model-x", config)
        self.assertIsNot(provider_a, provider_b)


class ProviderCacheTests(TestCase):
    """AC #17, #18: 实例缓存、失效与运行时切换。"""

    def setUp(self):
        factory.clear_cache()

    def test_same_key_returns_cached_instance(self):
        config = _make_config("openai")
        first = factory.get_or_create("t1:m1", config)
        second = factory.get_or_create("t1:m1", config)
        self.assertIs(first, second)

    def test_config_change_creates_new_instance(self):
        """模型配置变更后，工厂缓存自动失效。"""
        config_v1 = _make_config("openai", model_name="gpt-4o")
        config_v2 = _make_config("openai", model_name="gpt-4o-mini")
        first = factory.get_or_create("t1:m1", config_v1)
        second = factory.get_or_create("t1:m1", config_v2)
        self.assertIsNot(first, second)
        self.assertEqual(second.config.model_name, "gpt-4o-mini")

    def test_invalidate_single_key(self):
        config = _make_config("openai")
        first = factory.get_or_create("t1:m1", config)
        factory.invalidate_key("t1:m1")
        second = factory.get_or_create("t1:m1", config)
        self.assertIsNot(first, second)

    def test_invalidate_tenant_clears_only_that_tenant(self):
        config = _make_config("openai")
        provider_a = factory.get_or_create("t1:m1", config)
        provider_b = factory.get_or_create("t2:m1", config)
        factory.invalidate_tenant("t1")
        new_provider_a = factory.get_or_create("t1:m1", config)
        same_provider_b = factory.get_or_create("t2:m1", config)
        self.assertIsNot(provider_a, new_provider_a)
        self.assertIs(provider_b, same_provider_b)


class ProviderHttpMethodsTests(TestCase):
    """Provider HTTP 方法基础行为（mock requests.Session）。"""

    def _mock_response(self, json_body, status_code=200):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = json_body
        return mock_resp

    def test_chat_returns_response_json(self):
        provider = factory.create(_make_config("openai"))
        mock_resp = self._mock_response({
            "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        })
        with patch.object(provider.session, "post", return_value=mock_resp):
            data = provider.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(data["choices"][0]["message"]["content"], "hello")

    def test_embedding_returns_vectors(self):
        provider = factory.create(_make_config("qwen", model_name="bge-m3"))
        mock_resp = self._mock_response({"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]})
        with patch.object(provider.session, "post", return_value=mock_resp):
            vectors = provider.embedding(["hello", "world"])
        self.assertEqual(vectors, [[0.1, 0.2], [0.3, 0.4]])

    def test_rerank_returns_raw_json(self):
        provider = factory.create(_make_config("zhipu", model_name="reranker"))
        raw = {"results": [{"index": 0, "relevance_score": 0.9}, {"index": 1, "relevance_score": 0.1}]}
        mock_resp = self._mock_response(raw)
        with patch.object(provider.session, "post", return_value=mock_resp):
            data = provider.rerank("query", ["doc1", "doc2"])
        self.assertEqual(data, raw)

    def test_chat_stream_yields_chunks(self):
        provider = factory.create(_make_config("deepseek"))
        sse_body = [
            b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n',
            b'data: {"choices":[{"delta":{"content":"lo"}}]}\n',
            b'data: [DONE]\n',
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = iter(sse_body)
        with patch.object(provider.session, "post", return_value=mock_resp):
            chunks = list(provider.chat_stream([{"role": "user", "content": "hi"}]))
        contents = [c["choices"][0]["delta"]["content"] for c in chunks]
        self.assertEqual(contents, ["Hel", "lo"])


class FallbackChainTests(TestCase):
    """AC #19: 主模型失败后按优先级降级到备用模型。"""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="降级测试租户", api_key="fallback-key")
        factory.clear_cache()

    def _create_model(self, name, source, priority=0):
        return ModelConfig.objects.create(
            id=name,
            tenant=self.tenant,
            name=name,
            type="KnowledgeQA",
            source=source,
            parameters={"base_url": "https://api.example.com/v1", "model": name, "api_key": "sk-test"},
            fallback_priority=priority,
            status="active",
        )

    def test_fallback_succeeds_on_primary_failure(self):
        primary = self._create_model("primary", "openai", priority=10)
        backup = self._create_model("backup", "deepseek", priority=5)

        with patch.object(OpenAIProvider, "chat", side_effect=Exception("primary down")), \
             patch.object(DeepSeekProvider, "chat", return_value={
                 "choices": [{"message": {"content": "backup ok"}, "finish_reason": "stop"}],
                 "usage": {"total_tokens": 3},
             }):
            result = factory.chat_with_fallback(
                self.tenant, [{"role": "user", "content": "hi"}], model_id="primary",
            )
        self.assertEqual(result["content"], "backup ok")
        self.assertEqual(result["degradation_info"]["from_model"], "primary")
        self.assertEqual(result["degradation_info"]["to_model"], "backup")
        self.assertIn("primary down", result["degradation_info"]["reason"])

    def test_all_fail_raises_with_details(self):
        primary = self._create_model("p1", "openai", priority=10)
        backup = self._create_model("p2", "deepseek", priority=5)

        with patch.object(OpenAIProvider, "chat", side_effect=Exception("p1 down")), \
             patch.object(DeepSeekProvider, "chat", side_effect=Exception("p2 down")):
            with self.assertRaises(Exception) as ctx:
                factory.chat_with_fallback(
                    self.tenant, [{"role": "user", "content": "hi"}], model_id="p1",
                )
        self.assertIn("p1 down", str(ctx.exception))
        self.assertIn("p2 down", str(ctx.exception))

    def test_no_fallback_models_single_call(self):
        """没有备用模型时（priority=0）直接调用主模型。"""
        only = self._create_model("only", "openai", priority=0)
        with patch.object(OpenAIProvider, "chat", return_value={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 2},
        }) as mock_chat:
            result = factory.chat_with_fallback(
                self.tenant, [{"role": "user", "content": "hi"}], model_id="only",
            )
        mock_chat.assert_called_once()
        self.assertEqual(result["content"], "ok")
        self.assertNotIn("degradation_info", result)


class ProviderTypesTests(TestCase):
    """AC #20: provider_types() 动态反映工厂注册表。"""

    def test_provider_types_contains_five_vendors(self):
        from personal_knowledge_base.model_providers import provider_types
        names = [p["name"] for p in provider_types()]
        for expected in ("openai", "deepseek", "aliyun-bailian", "qwen", "zhipu"):
            self.assertIn(expected, names)


class ProviderConfigSignatureTests(TestCase):
    """ProviderConfig 签名计算用于缓存失效判断。"""

    def test_same_config_same_signature(self):
        c1 = _make_config("openai", model_name="gpt-4o")
        c2 = _make_config("openai", model_name="gpt-4o")
        self.assertEqual(c1.signature(), c2.signature())

    def test_different_model_different_signature(self):
        c1 = _make_config("openai", model_name="gpt-4o")
        c2 = _make_config("openai", model_name="gpt-4o-mini")
        self.assertNotEqual(c1.signature(), c2.signature())

    def test_different_key_different_signature(self):
        c1 = _make_config("openai", api_key="sk-aaa")
        c2 = _make_config("openai", api_key="sk-bbb")
        self.assertNotEqual(c1.signature(), c2.signature())
