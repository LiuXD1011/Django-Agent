"""LLM Provider 工厂测试：路由、隔离、缓存、降级。"""

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from personal_knowledge_base.model_providers import chat_completion
from personal_knowledge_base.llm_providers import (
    BailianProvider,
    DeepSeekProvider,
    OpenAIProvider,
    ProviderConfig,
    QwenProvider,
    ZhipuProvider,
    factory,
)
from personal_knowledge_base.models import ModelConfig, ModelUsage, Tenant


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


class ProviderMethodsTests(TestCase):
    """Provider 方法基础行为。"""

    def _mock_response(self, json_body, status_code=200):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = json_body
        return mock_resp

    def test_chat_returns_response_json(self):
        provider = factory.create(_make_config("openai"))
        response = {
            "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        with patch("personal_knowledge_base.llm_providers._litellm_completion", return_value=response):
            data = provider.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(data["choices"][0]["message"]["content"], "hello")

    def test_embedding_returns_vectors(self):
        provider = factory.create(_make_config("qwen", model_name="bge-m3"))
        response = {"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]}
        with patch("personal_knowledge_base.llm_providers._litellm_embedding", return_value=response):
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
        normalized_chunks = [
            {"choices": [{"delta": {"content": "Hel"}}]},
            {"choices": [{"delta": {"content": "lo"}}]},
        ]
        with patch("personal_knowledge_base.llm_providers._litellm_completion", return_value=iter(normalized_chunks)):
            chunks = list(provider.chat_stream([{"role": "user", "content": "hi"}]))
        contents = [c["choices"][0]["delta"]["content"] for c in chunks]
        self.assertEqual(contents, ["Hel", "lo"])


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


class LiteLLMAdapterTests(TestCase):
    """LiteLLM SDK 适配：统一 chat、stream、embedding 参数和响应形状。"""

    def test_openai_compatible_base_url_uses_openai_litellm_prefix(self):
        config = _make_config("deepseek", base_url="https://api.deepseek.com/v1", model_name="deepseek-chat")
        self.assertEqual(config.litellm_model(), "openai/deepseek-chat")

    def test_openai_compatible_model_name_with_slash_still_uses_openai_prefix(self):
        config = _make_config("openai", base_url="https://api.siliconflow.cn/v1", model_name="BAAI/bge-m3")
        self.assertEqual(config.litellm_model(), "openai/BAAI/bge-m3")

    def test_custom_litellm_model_can_override_provider_mapping(self):
        config = _make_config("aliyun-bailian", model_name="qwen-plus", litellm_model_name="dashscope/qwen-plus")
        self.assertEqual(config.litellm_model(), "dashscope/qwen-plus")

    def test_chat_delegates_to_litellm_with_retry_and_timeout(self):
        provider = factory.create(
            _make_config("deepseek", model_name="deepseek-chat", timeout=12, num_retries=3)
        )
        with patch("personal_knowledge_base.llm_providers._litellm_completion") as completion:
            completion.return_value = {
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            }
            data = provider.chat([{"role": "user", "content": "hi"}], temperature=0.2, max_tokens=64)

        self.assertEqual(data["choices"][0]["message"]["content"], "ok")
        completion.assert_called_once()
        self.assertIs(completion.call_args.args[0], provider.config)
        self.assertEqual(completion.call_args.kwargs["stream"], False)
        self.assertEqual(completion.call_args.kwargs["temperature"], 0.2)
        self.assertEqual(completion.call_args.kwargs["max_tokens"], 64)

    def test_stream_delegates_to_litellm_and_normalizes_chunks(self):
        provider = factory.create(_make_config("openai", model_name="gpt-4o-mini"))
        chunks = [
            {"choices": [{"delta": {"content": "Hel"}}]},
            {"choices": [{"delta": {"content": "lo"}}]},
        ]
        with patch("personal_knowledge_base.llm_providers._litellm_completion", return_value=iter(chunks)):
            streamed = list(provider.chat_stream([{"role": "user", "content": "hi"}]))

        self.assertEqual([c["choices"][0]["delta"]["content"] for c in streamed], ["Hel", "lo"])

    def test_embedding_delegates_to_litellm(self):
        provider = factory.create(_make_config("openai", model_name="text-embedding-3-small"))
        with patch("personal_knowledge_base.llm_providers._litellm_embedding") as embedding:
            embedding.return_value = {
                "data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}],
                "usage": {"total_tokens": 2},
            }
            vectors = provider.embedding(["hello", "world"])

        self.assertEqual(vectors, [[0.1, 0.2], [0.3, 0.4]])
        embedding.assert_called_once()
        self.assertIs(embedding.call_args.args[0], provider.config)


@override_settings(LLM_USE_ENV_CHAT=False, LLM_CHAT_MODEL_TIMEOUT=1)
class ChatCompletionFallbackIntegrationTests(TestCase):
    """业务 chat 调用：主模型异常后自动切换备用模型，并记录两次调用状态。"""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="chat fallback tenant", api_key="chat-fallback-key")
        factory.clear_cache()

    def _create_chat_model(self, model_id: str, source: str, priority: int = 0):
        return ModelConfig.objects.create(
            id=model_id,
            tenant=self.tenant,
            name=model_id,
            type="KnowledgeQA",
            source=source,
            parameters={
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-test",
                "model": model_id,
            },
            fallback_priority=priority,
            status="active",
        )

    def test_chat_completion_falls_back_to_priority_model_and_records_usage(self):
        self._create_chat_model("primary-chat", "openai", priority=0)
        self._create_chat_model("backup-chat", "deepseek", priority=10)

        with patch.object(OpenAIProvider, "chat", side_effect=RuntimeError("primary timeout")), \
             patch.object(DeepSeekProvider, "chat", return_value={
                 "choices": [{"message": {"content": "backup ok"}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
             }):
            content = chat_completion(self.tenant, [{"role": "user", "content": "hi"}], model_id="primary-chat")

        self.assertEqual(content, "backup ok")
        failed = ModelUsage.objects.get(model_id="primary-chat")
        succeeded = ModelUsage.objects.get(model_id="backup-chat")
        self.assertFalse(failed.success)
        self.assertTrue(succeeded.success)
        self.assertEqual(succeeded.total_tokens, 6)
