import contextvars
import tempfile
import threading

from django.test import SimpleTestCase, TestCase, override_settings

from personal_knowledge_base import observability as obs
from personal_knowledge_base.models import Knowledge, KnowledgeBase, KnowledgeProcessingSpan, Tenant
from personal_knowledge_base.model_usage import record_model_usage
from personal_knowledge_base.span_tracker import SpanTracker


class FakeObservation:
    def __init__(self, recorder, name, parent=None, kind="span", **attrs):
        self.recorder = recorder
        self.id = f"obs-{id(recorder) % 100000}-{len(recorder.observations)}"
        self.name = name
        self.parent = parent
        self.kind = kind
        self.attrs = attrs
        for key, value in attrs.items():
            setattr(self, key, value)
        self.updates: list[dict] = []
        self.children: list["FakeObservation"] = []
        self.ended = False
        recorder.observations.append(self)

    def start_span(self, name="", metadata=None, **kwargs):
        child = FakeObservation(self.recorder, name, parent=self, kind="span", metadata=metadata, **kwargs)
        self.children.append(child)
        return child

    def start_generation(self, name="", model=None, metadata=None, usage=None, **kwargs):
        child = FakeObservation(self.recorder, name, parent=self, kind="generation", model=model, usage=usage, metadata=metadata, **kwargs)
        self.children.append(child)
        return child

    def update(self, **kwargs):
        self.updates.append(kwargs)

    def end(self):
        self.ended = True


class FakeLangfuseClient:
    """镜像 Langfuse v3 SDK 中本项目实际用到的 API 面。"""

    def __init__(self):
        self.observations: list[FakeObservation] = []
        self.flush_count = 0
        self.datasets_created: list[str] = []
        self.dataset_items: list[dict] = []

    def start_span(self, name="", metadata=None, **kwargs):
        return FakeObservation(self, name, kind="root", metadata=metadata, **kwargs)

    def start_generation(self, name="", model=None, metadata=None, usage=None, **kwargs):
        return FakeObservation(self, name, kind="generation", model=model, usage=usage, metadata=metadata, **kwargs)

    def flush(self):
        self.flush_count += 1

    def create_dataset(self, name="", **kwargs):
        self.datasets_created.append(name)

    def create_dataset_item(self, **kwargs):
        self.dataset_items.append(kwargs)

    def generations(self):
        return [item for item in self.observations if item.kind == "generation"]

    def roots(self):
        return [item for item in self.observations if item.kind == "root"]


class LangfuseFakeMixin:
    def install_fake_client(self):
        self._old_client = obs._client
        self._old_ready = obs._client_ready
        self.fake = FakeLangfuseClient()
        obs._client = self.fake
        obs._client_ready = True
        self.addCleanup(self._restore_fake)

    def _restore_fake(self):
        obs._client = self._old_client
        obs._client_ready = self._old_ready
        obs._current_span.set(None)


class LangfuseDisabledTests(LangfuseFakeMixin, SimpleTestCase):
    def setUp(self):
        # 其他测试类直接改写模块级 _client/_client_ready，这里先复位到"未初始化"态
        self._saved_state = (obs._client, obs._client_ready)
        obs._client = None
        obs._client_ready = False
        self.addCleanup(self._restore_state)

    def _restore_state(self):
        obs._client, obs._client_ready = self._saved_state
        obs._current_span.set(None)

    def test_disabled_when_keys_missing(self):
        self.assertFalse(obs.langfuse_enabled())
        self.assertIsNone(obs.get_langfuse())
        self.assertIsNone(obs.start_business_trace("chat.message", session_id="s1"))

    def test_child_span_is_noop_when_disabled(self):
        with obs.child_span("retrieval", metadata={"kb_count": 1}) as span:
            self.assertIsNone(span)
        obs.report_model_call(scenario="chat")  # 不得抛异常
        obs.flush_langfuse()


class LangfuseTraceTests(LangfuseFakeMixin, SimpleTestCase):
    def setUp(self):
        self.install_fake_client()


    def test_business_trace_nests_generations_and_children(self):
        handle = obs.start_business_trace("chat.message", session_id="s1", user_id="u1", metadata={"tenant_id": "t1"})
        self.assertIsNotNone(handle)

        obs.report_model_call(name="llm.chat", model="m1", scenario="chat", prompt_tokens=10, completion_tokens=5, total_tokens=15)

        with obs.child_span("retrieval", metadata={"kb_count": 2}) as child:
            self.assertIsNotNone(child)
            obs.report_model_call(name="llm.embed", scenario="embedding", prompt_tokens=3, total_tokens=3)

        obs.close_business_trace(handle, output={"answer_length": 42})

        roots = self.fake.roots()
        self.assertEqual(len(roots), 1)
        root = roots[0]
        self.assertTrue(root.ended)
        generations = self.fake.generations()
        self.assertEqual(len(generations), 2)
        by_name = {gen.name: gen for gen in generations}
        self.assertIs(by_name["llm.chat"].parent, root)
        self.assertEqual(by_name["llm.chat"].usage, {"input": 10, "output": 5, "total": 15, "unit": "TOKENS"})
        retrieval = root.children[-1]
        self.assertEqual(retrieval.name, "retrieval")
        self.assertIs(by_name["llm.embed"].parent, retrieval)
        self.assertTrue(retrieval.ended)
        # trace 关闭后 contextvar 已清空
        self.assertIsNone(obs._current_span.get())

    def test_orphan_generation_skipped_by_default(self):
        obs.report_model_call(name="llm.chat", scenario="chat")
        self.assertEqual(self.fake.generations(), [])

    @override_settings(LANGFUSE_ORPHAN_MODE="standalone")
    def test_orphan_generation_standalone_mode(self):
        obs.report_model_call(name="llm.chat", scenario="chat")
        self.assertEqual(len(self.fake.generations()), 1)

    def test_agent_trace_metadata_omits_query_content_by_default(self):
        with obs.trace_agent_execution(session_id="s1", user_id="u1", query="机密问题内容") as ctx:
            self.assertNotEqual(ctx.trace_id, "")
        root = self.fake.roots()[0]
        self.assertNotIn("query", root.attrs["metadata"])
        self.assertEqual(root.attrs["metadata"]["query_length"], len("机密问题内容"))

    def test_trace_llm_call_without_trace_id_creates_nothing(self):
        # 与 tests.py 的零 token 用量回归同源：空 trace_id 时不得创建任何 span
        with obs.trace_llm_call(obs.TraceContext(), model="deepseek-v4", messages=[{"role": "user", "content": "hello"}]) as result:
            result["content"] = "ok"
        self.assertEqual(self.fake.observations, [])

    def test_trace_llm_call_nests_under_active_trace(self):
        root = obs.start_business_trace("agent.run", session_id="s1")
        with obs.trace_llm_call(obs.TraceContext(trace_id="manual"), model="m1", messages=[]) as result:
            result["content"] = "answer"
        llm_spans = [item for item in self.fake.observations if item.name.startswith("llm.call")]
        self.assertEqual(len(llm_spans), 1)
        self.assertIs(llm_spans[0].parent, root)
        self.assertTrue(llm_spans[0].ended)
        obs.close_business_trace(root)

    def test_thread_context_propagation(self):
        handle = obs.start_business_trace("chat.message", session_id="s1")
        request_context = contextvars.copy_context()
        results = {}

        def worker():
            def inner():
                obs.report_model_call(name="llm.chat", scenario="chat")
                results["current"] = obs._current_span.get()
            request_context.run(inner)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        self.assertIs(results["current"], handle)
        generation = self.fake.generations()[0]
        self.assertIs(generation.parent, handle)


class LangfuseEvaluationReportTests(LangfuseFakeMixin, SimpleTestCase):
    def setUp(self):
        self.install_fake_client()


    def test_report_evaluation_run_trace_only_by_default(self):
        obs.report_evaluation_run(
            name="eval.tenant_rag",
            task_run_id="task-1",
            metrics={"verification_status": "verified", "rag": {"f1": 0.8}},
            dataset_name="tenant-eval:d1",
            entries=[{"question": "q1", "reference_answer": "a1"}],
        )

        roots = self.fake.roots()
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0].name, "eval.tenant_rag")
        self.assertTrue(roots[0].ended)
        self.assertEqual(self.fake.datasets_created, [])
        self.assertEqual(self.fake.dataset_items, [])
        self.assertGreaterEqual(self.fake.flush_count, 1)

    @override_settings(LANGFUSE_UPLOAD_EVAL_DATASETS=True)
    def test_report_evaluation_run_uploads_dataset_when_enabled(self):
        obs.report_evaluation_run(
            name="eval.tenant_rag",
            task_run_id="task-1",
            metrics={"verification_status": "verified"},
            dataset_name="tenant-eval:d1",
            entries=[
                {"question": "q1", "reference_answer": "a1"},
                {"question": "q2", "ground_truth": "a2"},
            ],
        )

        self.assertIn("tenant-eval:d1", self.fake.datasets_created)
        self.assertEqual(len(self.fake.dataset_items), 2)
        self.assertEqual(self.fake.dataset_items[0]["input"], {"question": "q1"})
        self.assertEqual(self.fake.dataset_items[0]["expected_output"], {"answer": "a1"})


@override_settings(
    LLM_USE_ENV_CHAT=False,
    LLM_USE_ENV_SUMMARY=False,
    LLM_USE_ENV_QUESTION=False,
    LLM_USE_ENV_EXTRACT=False,
    LLM_USE_ENV_EMBEDDING=False,
)
class LangfuseRecordUsageTests(LangfuseFakeMixin, TestCase):
    def setUp(self):
        self.install_fake_client()
        self.tenant = Tenant.objects.create(name="langfuse-usage", api_key="langfuse-usage")


    def test_record_model_usage_reports_generation_and_persists(self):
        handle = obs.start_business_trace("chat.message", session_id="s1")
        record_model_usage(
            self.tenant,
            model_id="m-1",
            model_name="model-a",
            model_type="chat",
            provider="openai",
            scenario="chat",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            cached_tokens=2,
            duration_ms=120,
        )

        generations = self.fake.generations()
        self.assertEqual(len(generations), 1)
        generation = generations[0]
        self.assertEqual(generation.name, "llm.chat")
        self.assertIs(generation.parent, handle)
        self.assertEqual(generation.usage, {"input": 10, "output": 5, "total": 15, "unit": "TOKENS", "input_details": {"cached": 2}})
        self.assertEqual(generation.attrs["metadata"]["tenant_id"], str(self.tenant.id))
        obs.close_business_trace(handle)

    def test_internal_model_types_still_reported(self):
        # summary 等内部场景跳过 DB 记录，但 Langfuse generation 仍然上报（解析 trace 需要）
        handle = obs.start_business_trace("knowledge.parse")
        record_model_usage(
            self.tenant,
            model_name="model-a",
            model_type="summary",
            scenario="summary",
            total_tokens=7,
            duration_ms=30,
        )
        self.assertEqual(len(self.fake.generations()), 1)
        self.assertIs(self.fake.generations()[0].parent, handle)
        obs.close_business_trace(handle)

    def test_client_failure_does_not_break_local_recording(self):
        class ExplodingClient:
            def start_generation(self, **kwargs):
                raise RuntimeError("langfuse down")

        original_client = obs._client
        obs._client = ExplodingClient()
        self.addCleanup(setattr, obs, "_client", original_client)

        record_model_usage(
            self.tenant,
            model_name="model-a",
            model_type="chat",
            scenario="chat",
            prompt_tokens=1,
            total_tokens=1,
        )
        # 本地 ModelUsage 仍然写入（闸口既有行为不受旁路故障影响）
        self.assertTrue(self.tenant.modelusage_set.filter(scenario="chat").exists())


@override_settings(
    LLM_USE_ENV_CHAT=False,
    LLM_USE_ENV_SUMMARY=False,
    LLM_USE_ENV_QUESTION=False,
    LLM_USE_ENV_EXTRACT=False,
    LLM_USE_ENV_EMBEDDING=False,
)
class LangfuseSpanTrackerTests(LangfuseFakeMixin, TestCase):
    def setUp(self):
        self.install_fake_client()
        media_dir = tempfile.TemporaryDirectory()
        override = override_settings(MEDIA_ROOT=media_dir.name)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(media_dir.cleanup)
        self.tenant = Tenant.objects.create(name="langfuse-parse", api_key="langfuse-parse")
        self.kb = KnowledgeBase.objects.create(tenant=self.tenant, name="langfuse-kb")
        self.knowledge = Knowledge.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            type="file",
            title="Langfuse Doc",
            source="doc.md",
            file_name="doc.md",
            file_type="md",
        )


    def test_parse_trace_mirrors_stages(self):
        tracker = SpanTracker(str(self.knowledge.id))
        root_span = tracker.open_attempt(attempt=1)
        self.assertIsNotNone(root_span)

        roots = [item for item in self.fake.roots() if item.name == "knowledge.parse"]
        self.assertEqual(len(roots), 1)
        parse_root = roots[0]
        self.assertEqual(parse_root.attrs["metadata"]["knowledge_id"], str(self.knowledge.id))

        stage = tracker.begin_stage("chunking", attempt=1, input_data={"chunk_size": 512})
        subspan = tracker.begin_subspan(stage.span_id, "structural", input_data={})
        tracker.end_span(subspan.span_id, output_data={"count": 3})
        tracker.end_span(stage.span_id, output_data={"chunk_count": 3})
        tracker.finalize_attempt(attempt=1)

        mirrored = {item.name: item for item in parse_root.children}
        self.assertIn("stage.chunking", mirrored)
        stage_lf = mirrored["stage.chunking"]
        subspan_lf = {item.name: item for item in stage_lf.children}.get("subspan.structural")
        self.assertIsNotNone(subspan_lf)
        self.assertTrue(stage_lf.ended)
        self.assertTrue(subspan_lf.ended)
        self.assertEqual(stage_lf.updates[-1]["output"]["chunk_count"], 3)
        self.assertTrue(parse_root.ended)
        # 本地 DB 行为不受镜像影响
        self.assertTrue(
            KnowledgeProcessingSpan.objects.filter(knowledge=self.knowledge, name="chunking", status="done").exists()
        )
