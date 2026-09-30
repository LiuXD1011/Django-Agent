"""P3：模型调用生命周期与本地/远端用量对账测试。

验收目标（计划 §9.2 A07/A12/A14 部分）：
- 一次业务模型调用只有一个带用量的 generation（生命周期路径不再触发事后 report）；
- model_call_id 同时写入远端 generation metadata 与本地 ModelUsage.metadata / llm/call 事件；
- 备用模型切换的每次业务可见尝试分别记录（失败与成功区分，model_call_id 不同）；
- 流式消费方断连（GeneratorExit）→ 远端按取消终结一次，本地用量统计规则不变（不新增记录）。
"""
from unittest.mock import patch

from django.test import TestCase, override_settings

from personal_knowledge_base import observability as obs
from personal_knowledge_base.model_usage import ModelCall, record_model_usage
from personal_knowledge_base.model_providers import chat_completion_stream
from personal_knowledge_base.models import ModelUsage, Tenant

from personal_knowledge_base.test_langfuse_observability import FakeLangfuseClient, LangfuseFakeMixin


@override_settings(
    LLM_USE_ENV_CHAT=False,
    LLM_USE_ENV_SUMMARY=False,
    LLM_USE_ENV_QUESTION=False,
    LLM_USE_ENV_EXTRACT=False,
    LLM_USE_ENV_EMBEDDING=False,
)
class ModelLifecycleTests(LangfuseFakeMixin, TestCase):
    def setUp(self):
        self.install_fake_client()
        self.tenant = Tenant.objects.create(name="lifecycle", api_key="lifecycle")

    def test_lifecycle_single_generation_with_model_call_id(self):
        handle = obs.start_business_trace("chat.turn", session_id="s1")
        mc = ModelCall().start(model="model-a", provider="openai", scenario="chat")
        record_model_usage(
            self.tenant,
            model_id="m-1",
            model_name="model-a",
            model_type="chat",
            provider="openai",
            scenario="chat",
            prompt_tokens=7,
            completion_tokens=3,
            total_tokens=10,
            duration_ms=90,
            model_call_id=mc.model_call_id,
            generation=mc.handle,
        )
        obs.close_business_trace(handle)

        generations = self.fake.generations()
        # 一次调用只产生一个远端 generation（不再叠加事后 report）
        self.assertEqual(len(generations), 1)
        gen = generations[0]
        self.assertEqual(gen.usage_details["input"], 7)
        self.assertEqual(gen.usage_details["output"], 3)
        self.assertEqual(gen.usage_details["total"], 10)
        self.assertEqual(gen.attrs["metadata"]["model_call_id"], mc.model_call_id)
        # 本地记录带同一对账键
        local = ModelUsage.objects.get(scenario="chat")
        self.assertEqual((local.metadata or {}).get("model_call_id"), mc.model_call_id)

    def test_cancel_finishes_generation_once_without_local_record(self):
        handle = obs.start_business_trace("chat.turn", session_id="s1")
        mc = ModelCall().start(model="model-a", provider="openai", scenario="chat")
        mc.cancel("client disconnected during stream")
        mc.cancel("second call must be noop")
        obs.close_business_trace(handle)

        generations = self.fake.generations()
        self.assertEqual(len(generations), 1)
        self.assertTrue(generations[0].ended)
        # 取消以 WARNING 级别与取消原因记录
        last_update = generations[0].updates[-1]
        self.assertEqual(last_update["level"], "WARNING")
        self.assertEqual(last_update["status_message"], "operation failed (details hidden)")
        # 无本地用量记录（保持既有断连统计语义）
        self.assertFalse(ModelUsage.objects.exists())

    def test_usage_details_subset_semantics(self):
        """缓存/推理 token 是输入/输出子集：usage_details 不重复累加。"""
        handle = obs.start_business_trace("chat.turn")
        mc = ModelCall().start(model="model-a", provider="openai", scenario="chat")
        record_model_usage(
            self.tenant,
            model_id="m-1",
            model_name="model-a",
            model_type="chat",
            provider="openai",
            scenario="chat",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cached_tokens=30,
            reasoning_tokens=10,
            model_call_id=mc.model_call_id,
            generation=mc.handle,
        )
        obs.close_business_trace(handle)
        details = self.fake.generations()[0].usage_details
        self.assertEqual(details["input"], 70)
        self.assertEqual(details["output"], 40)
        self.assertEqual(details["total"], 150)  # 不与 cached/reasoning 重复相加
        self.assertEqual(details["input_cached_tokens"], 30)
        self.assertEqual(details["output_reasoning_tokens"], 10)


@override_settings(
    LLM_USE_ENV_CHAT=True,
    LLM_CHAT_API_KEY="sk-test",
    LLM_CHAT_BASE_URL="https://bailian.example/v1",
    LLM_CHAT_MODEL="qwen-test",
)
class StreamCancelTests(LangfuseFakeMixin, TestCase):
    """流式断连：GeneratorExit → 远端取消终结一次，本地统计语义不变。"""

    def setUp(self):
        self.install_fake_client()
        self.tenant = Tenant.objects.create(name="stream-cancel", api_key="stream-cancel")

    def test_generator_close_cancels_generation_without_local_record(self):
        def fake_stream(base_url, api_key, model_name, messages):
            for chunk in ["你", "好", "世界"]:
                yield {"choices": [{"delta": {"content": chunk}}]}

        handle = obs.start_business_trace("chat.turn", session_id="s1")
        with patch(
            "personal_knowledge_base.model_providers.openai_compatible_chat_stream",
            side_effect=fake_stream,
        ):
            stream = chat_completion_stream(self.tenant, [{"role": "user", "content": "hi"}])
            first = next(stream)
            stream.close()  # 模拟 SSE 断连：消费方提前放弃生成器
        obs.close_business_trace(handle)

        self.assertEqual(first, "你")
        # 远端 generation 恰好一个且被取消终结
        generations = self.fake.generations()
        self.assertEqual(len(generations), 1)
        self.assertTrue(generations[0].ended)
        last_update = generations[0].updates[-1]
        self.assertEqual(last_update["level"], "WARNING")
        # 本地无新增用量记录（断连语义与基线一致）
        self.assertFalse(ModelUsage.objects.exists())
