from unittest.mock import patch

from django.test import SimpleTestCase

from personal_knowledge_base.llm_providers import OpenAIProvider, ProviderConfig
from personal_knowledge_base.thinking import Thinking, adapt, capability, normalize


BASE = "https://open.bigmodel.cn/api/paas/v4"
MODEL = "glm-5.3-flash"


class GlmThinkingTests(SimpleTestCase):
    def setUp(self):
        self.provider = OpenAIProvider(ProviderConfig(
            base_url=BASE, api_key="fixture-key", model_name=MODEL,
        ))
        self.litellm = self.enterContext(patch(
            "personal_knowledge_base.llm_providers._load_litellm",
        )).return_value
        self.litellm.completion.return_value = {
            "choices": [{"message": {"content": "摘要"}}],
        }

    def test_summary_uses_low_effort_instead_of_disabling_required_thinking(self):
        self.provider.chat([{"role": "user", "content": "生成摘要"}], enable_thinking=False)
        kwargs = self.litellm.completion.call_args.kwargs
        self.assertNotIn("enable_thinking", kwargs)
        self.assertEqual(kwargs["extra_body"], {
            "thinking": {"type": "enabled"}, "reasoning_effort": "low",
        })

    def test_default_does_not_override_supplier_effort(self):
        self.provider.chat([{"role": "user", "content": "你好"}])
        kwargs = self.litellm.completion.call_args.kwargs
        self.assertNotIn("enable_thinking", kwargs)
        self.assertNotIn("extra_body", kwargs)

    def test_configured_effort_is_supported_without_an_off_mode(self):
        cap = capability(BASE, MODEL)
        with self.assertRaises(ValueError):
            normalize({"mode": "off", "effort": None}, cap)
        for effort in ("low", "high", "max"):
            with self.subTest(effort=effort):
                self.provider.chat(
                    [{"role": "user", "content": "测试"}],
                    thinking=Thinking(mode="on", effort=effort),
                )
                self.assertEqual(self.litellm.completion.call_args.kwargs["extra_body"], {
                    "thinking": {"type": "enabled"}, "reasoning_effort": effort,
                })

    def test_adapt_records_applied_low_effort_for_internal_summary_policy(self):
        policy = adapt(Thinking(revision=7), BASE, MODEL, enable_thinking=False)
        self.assertEqual(policy.mode, "on")
        self.assertEqual(policy.effort, "low")
        self.assertEqual(policy.revision, 7)
        self.assertEqual(policy.source, "internal")

    def test_other_glm_models_and_unknown_endpoints_keep_existing_parameters(self):
        for base, model in ((BASE, "glm-4.7"), ("https://proxy.example/v1", MODEL)):
            with self.subTest(base=base, model=model):
                provider = OpenAIProvider(ProviderConfig(
                    base_url=base, api_key="fixture-key", model_name=model,
                ))
                provider.chat([{"role": "user", "content": "摘要"}], enable_thinking=False)
                kwargs = self.litellm.completion.call_args.kwargs
                self.assertFalse(kwargs["enable_thinking"])
                self.assertNotIn("extra_body", kwargs)
