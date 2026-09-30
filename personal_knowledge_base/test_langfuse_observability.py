import contextvars
import tempfile
import threading

from django.test import SimpleTestCase, TestCase, override_settings

from personal_knowledge_base import observability as obs
from personal_knowledge_base.models import Knowledge, KnowledgeBase, KnowledgeProcessingSpan, Tenant
from personal_knowledge_base.model_usage import ModelCall, record_model_usage
from personal_knowledge_base.span_tracker import SpanTracker


class FakeObservation:
    """镜像 Langfuse v3.15.0 真实 SDK 观测对象接口面（签名对齐，禁止任意 **kwargs 宽松面）。

    真实契约要点（见 test_langfuse_sdk_contract.py 的实证测试）：
    - start_generation/start_observation 仅接受关键字参数，usage 字段名为 usage_details；
    - start_span 不接受 session_id/user_id（update_trace 才是正确入口）；
    - trace_id 为远端 trace ID，id 为 observation ID。
    """

    def __init__(self, recorder, name, parent=None, kind="span", **attrs):
        self.recorder = recorder
        self.id = f"obs-{id(recorder) % 100000}-{len(recorder.observations)}"
        self.trace_id = parent.trace_id if parent is not None else f"trace-{len(recorder.observations)}"
        self.name = name
        self.parent = parent
        self.kind = kind
        self.attrs = attrs
        for key, value in attrs.items():
            setattr(self, key, value)
        self.trace_updates: list[dict] = []
        self.updates: list[dict] = []
        self.score_calls: list[dict] = []
        self.children: list["FakeObservation"] = []
        self.ended = False
        recorder.observations.append(self)

    def start_span(self, name="", metadata=None, **kwargs):
        child = FakeObservation(self.recorder, name, parent=self, kind="span", metadata=metadata, **kwargs)
        self.children.append(child)
        return child

    def start_generation(self, *, name, model=None, metadata=None, usage_details=None, **kwargs):
        child = FakeObservation(
            self.recorder, name, parent=self, kind="generation",
            model=model, usage_details=usage_details, metadata=metadata, **kwargs,
        )
        self.children.append(child)
        return child

    def start_observation(self, *, name, as_type="span", metadata=None, usage_details=None, **kwargs):
        kind = "generation" if as_type == "generation" else as_type
        child = FakeObservation(
            self.recorder, name, parent=self, kind=kind,
            usage_details=usage_details, metadata=metadata, **kwargs,
        )
        self.children.append(child)
        return child

    def update(self, **kwargs):
        self.updates.append(kwargs)
        # 与真实 SDK 一致：update 立即改变后续导出的属性
        for key, value in kwargs.items():
            setattr(self, key, value)

    def update_trace(self, *, session_id=None, user_id=None, name=None, metadata=None, **kwargs):
        payload = {"session_id": session_id, "user_id": user_id, **kwargs}
        self.trace_updates.append(payload)
        if session_id is not None:
            self.attrs["session_id"] = session_id
        if user_id is not None:
            self.attrs["user_id"] = user_id

    def score(self, *, name, value, score_id=None, data_type=None, comment=None, **kwargs):
        self.score_calls.append({"name": name, "value": value, "score_id": score_id})

    def end(self):
        self.ended = True


class FakeLangfuseClient:
    """镜像 Langfuse v3 SDK 中本项目实际用到的 API 面（与 3.15.0 签名一致）。"""

    def __init__(self):
        self.observations: list[FakeObservation] = []
        self.flush_count = 0
        self.datasets_created: list[str] = []
        self.dataset_items: list[dict] = []

    def start_span(self, name="", metadata=None, **kwargs):
        return FakeObservation(self, name, kind="root", metadata=metadata, **kwargs)

    def start_generation(self, *, name, model=None, metadata=None, usage_details=None, **kwargs):
        return FakeObservation(
            self, name, kind="generation", model=model,
            usage_details=usage_details, metadata=metadata, **kwargs,
        )

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
        self.enterContext(override_settings(LANGFUSE_ENABLED=True))
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
        self.assertEqual(by_name["llm.chat"].usage_details, {"input": 10, "output": 5, "total": 15})
        retrieval = root.children[-1]
        self.assertEqual(retrieval.name, "retrieval")
        self.assertIs(by_name["llm.embed"].parent, retrieval)
        self.assertTrue(retrieval.ended)
        # trace 关闭后 contextvar 已恢复（无外层时为空）
        self.assertIsNone(obs._current_span.get())
        # session_id 经 update_trace 传递（真实 SDK 契约）
        self.assertEqual(root.trace_updates[-1]["session_id"], "s1")
        # 句柄暴露真实 trace_id 与 observation_id 且二者不同
        self.assertNotEqual(handle.trace_id, "")
        self.assertNotEqual(handle.trace_id, handle.observation_id)

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
        self.assertIs(llm_spans[0].parent, root.span)
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
        self.assertIs(generation.parent, handle.span)


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

    @override_settings(LANGFUSE_UPLOAD_EVAL_DATASETS=True, LANGFUSE_LOG_CONTENT=True)
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

    def test_report_evaluation_run_bridges_example_scores(self):
        """逐样例评分桥接：evaluation.example 子 span + 确定性 score_id（A18）。"""
        obs.report_evaluation_run(
            name="eval.tenant_rag",
            task_run_id="task-9",
            metrics={"verification_status": "verified"},
            examples=[
                {"example_id": "task-9:row-0", "faithfulness": 0.9, "answer_relevancy": 0.8, "valid": True},
                {"example_id": "task-9:row-1", "valid": False, "error": "ragas_score_invalid"},
            ],
        )
        example_spans = [item for item in self.fake.observations if item.name == "evaluation.example"]
        self.assertEqual(len(example_spans), 2)
        first = example_spans[0]
        self.assertEqual(first.attrs["metadata"]["example_id"], "task-9:row-0")
        score_names = {call["name"] for call in first.score_calls}
        self.assertEqual(score_names, {"faithfulness", "answer_relevancy"})
        # 确定性 score_id：同一任务/样例/指标重复同步得到同一 id（幂等）
        first_score_ids = {call["name"]: call["score_id"] for call in first.score_calls}
        obs.report_evaluation_run(
            name="eval.tenant_rag",
            task_run_id="task-9",
            metrics={},
            examples=[
                {"example_id": "task-9:row-0", "faithfulness": 0.9, "answer_relevancy": 0.8, "valid": True},
            ],
        )
        again = [item for item in self.fake.observations if item.name == "evaluation.example"][0]
        again_ids = {call["name"]: call["score_id"] for call in again.score_calls}
        self.assertEqual(first_score_ids, again_ids)

    def test_report_evaluation_run_without_examples_makes_no_example_spans(self):
        """只有汇总指标的旧任务不伪造逐样例值。"""
        obs.report_evaluation_run(name="eval.open_rag", task_run_id="task-10", metrics={"f1": 0.5})
        self.assertEqual([item for item in self.fake.observations if item.name == "evaluation.example"], [])


class LangfusePrivacyTests(LangfuseFakeMixin, SimpleTestCase):
    """A15/A16：内容默认不出网；开启后脱敏+截断；秘密任何情况下不发送。"""

    def setUp(self):
        self.install_fake_client()

    def test_safe_metadata_redacts_sensitive_keys(self):
        result = obs._safe_metadata({
            "api_key": "sk-abcdef123456",
            "password": "hunter2",
            "AUTHORIZATION": "Bearer xxx",
            "model": "gpt-test",
            "empty_secret": "",
        })
        self.assertEqual(result["api_key"], "<redacted>")
        self.assertEqual(result["password"], "<redacted>")
        self.assertEqual(result["AUTHORIZATION"], "<redacted>")
        self.assertEqual(result["model"], "gpt-test")
        self.assertEqual(result["empty_secret"], "")

    def test_mask_secrets_inline_forms(self):
        text = "connect to https://user:pass@host/x and api_key=abcd1234&next=1"
        masked = obs._mask_secrets(text)
        self.assertNotIn("pass@", masked)
        self.assertNotIn("abcd1234", masked)  # api_key=... 整体替换为 ***

    def test_tool_span_omits_args_and_output_by_default(self):
        with obs.trace_agent_execution("s1", "u1", "q") as ctx:
            with obs.trace_tool_execution(ctx, "kb.search", {"query": "机密查询词", "top_k": 5}) as result:
                result["output"] = "机密检索结果内容"
        tool_spans = [item for item in self.fake.observations if item.name == "tool.kb.search"]
        self.assertEqual(len(tool_spans), 1)
        meta = tool_spans[0].attrs["metadata"]
        self.assertEqual(meta["arg_names"], ["query", "top_k"])
        self.assertEqual(meta["arg_count"], 2)
        self.assertNotIn("args", meta)
        self.assertNotIn("机密查询词", str(meta))
        # output 不上报（默认关内容）
        output_payload = tool_spans[0].updates[-1]["output"]
        self.assertNotIn("output", output_payload)

    @override_settings(LANGFUSE_LOG_CONTENT=True)
    def test_tool_span_includes_masked_args_when_content_enabled(self):
        with obs.trace_agent_execution("s1", "u1", "q") as ctx:
            with obs.trace_tool_execution(ctx, "kb.search", {"query": "普通查询", "password": "secret123"}) as result:
                result["output"] = "普通结果内容"
        tool_spans = [item for item in self.fake.observations if item.name == "tool.kb.search"]
        meta = tool_spans[0].attrs["metadata"]
        self.assertEqual(meta["args"]["query"], "普通查询")
        self.assertEqual(meta["args"]["password"], "<redacted>")  # 内容开启仍不打密码
        output_payload = tool_spans[0].updates[-1]["output"]
        self.assertEqual(output_payload["output"], "普通结果内容")

    def test_error_message_masked_in_report(self):
        handle = obs.start_business_trace("chat.message")
        obs.report_model_call(
            name="llm.chat", scenario="chat", success=False,
            error_message="upstream failed for api_key=sk-secret999",
        )
        obs.close_business_trace(handle, status="failed", error="boom https://u:p@h")
        gen = self.fake.generations()[0]
        self.assertNotIn("sk-secret999", gen.attrs["status_message"])
        self.assertNotIn("api_key=sk", gen.attrs["status_message"])  # 内联凭证整体打码


class LangfuseFaultInjectionTests(LangfuseFakeMixin, SimpleTestCase):
    """A13：SDK 各阶段异常不外泄、不吞业务异常、不重复业务执行。"""

    def setUp(self):
        self.install_fake_client()

    def test_client_start_span_failure_returns_none(self):
        class ExplodingClient(FakeLangfuseClient):
            def start_span(self, *args, **kwargs):
                raise RuntimeError("langfuse down")

        obs._client = ExplodingClient()
        handle = obs.start_business_trace("chat.message", session_id="s1")
        self.assertIsNone(handle)  # 旁路降级，业务继续
        obs.report_model_call(name="llm.chat", scenario="chat")  # 不得抛异常
        obs.flush_langfuse()

    def test_child_span_update_failure_still_ends(self):
        handle = obs.start_business_trace("chat.message")
        with obs.child_span("retrieval") as span:
            span.update = None  # 模拟 SDK update 崩溃
        # close_child_span 吞掉 update 异常，span 仍然 end，不抛出
        self.assertTrue(span.ended)
        obs.close_business_trace(handle)

    def test_business_exception_propagates_and_span_closes(self):
        handle = obs.start_business_trace("chat.message")
        with self.assertRaisesRegex(ValueError, "business boom"):
            with obs.child_span("rag.retrieve"):
                raise ValueError("business boom")
        self.assertTrue(handle.span.ended is False)  # 根未自动结束
        retrieval = [item for item in self.fake.observations if item.name == "rag.retrieve"][0]
        self.assertTrue(retrieval.ended)
        obs.close_business_trace(handle)

    def test_close_business_trace_twice_is_safe(self):
        handle = obs.start_business_trace("chat.message")
        obs.close_business_trace(handle, output={"a": 1})
        obs.close_business_trace(handle, output={"a": 2})  # 二次关闭不抛、不改写
        self.assertEqual(handle.span.updates[0]["output"]["a"], 1)


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
        self.assertIs(generation.parent, handle.span)
        self.assertEqual(
            generation.usage_details,
            {"input": 8, "output": 5, "total": 15, "input_cached_tokens": 2},
        )
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
        self.assertIs(self.fake.generations()[0].parent, handle.span)
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

    def test_parse_metadata_omits_title_by_default(self):
        """§7.1：默认不上传文档标题；开启内容采集时才携带。"""
        tracker = SpanTracker(str(self.knowledge.id))
        tracker.open_attempt(attempt=1)
        roots = [item for item in self.fake.roots() if item.name == "knowledge.parse"]
        self.assertEqual(len(roots), 1)
        metadata = roots[0].attrs["metadata"]
        self.assertNotIn("title", metadata)
        self.assertEqual(metadata["knowledge_id"], str(self.knowledge.id))

    @override_settings(LANGFUSE_LOG_CONTENT=True)
    def test_parse_metadata_includes_title_when_content_enabled(self):
        tracker = SpanTracker(str(self.knowledge.id))
        tracker.open_attempt(attempt=1)
        roots = [item for item in self.fake.roots() if item.name == "knowledge.parse"]
        self.assertEqual(roots[0].attrs["metadata"].get("title"), "Langfuse Doc")

    def test_retry_attempt_creates_new_remote_root(self):
        """实际重试产生新的远端尝试根，不在远端复用同一次执行。"""
        tracker = SpanTracker(str(self.knowledge.id))
        tracker.open_attempt(attempt=1)
        tracker.finalize_attempt(attempt=1)
        tracker.open_attempt(attempt=2)
        roots = [item for item in self.fake.roots() if item.name == "knowledge.parse"]
        self.assertEqual(len(roots), 2)
        self.assertTrue(roots[0].ended)
        self.assertFalse(roots[1].ended)
        tracker.finalize_attempt(attempt=2)

    def test_stage_scope_nests_model_calls_and_restores(self):
        """阶段 scope：阶段内模型调用隶属阶段；阶段结束恢复父级。"""
        handle = tracker_root = obs.start_business_trace("knowledge.parse")
        tracker = SpanTracker(str(self.knowledge.id))
        tracker._lf_root = handle
        stage = tracker.begin_stage("chunking", attempt=1, input_data={"chunk_size": 512})
        # 阶段 scope 生效：当前上下文为阶段 span
        self.assertIs(obs._current_span.get(), tracker._lf_by_span_id[stage.span_id])
        mc = ModelCall().start(model="m", provider="p", scenario="summary")
        record_model_usage(
            self.tenant, model_name="m", model_type="summary", scenario="summary",
            total_tokens=5, model_call_id=mc.model_call_id, generation=mc.handle,
        )
        tracker.end_span(stage.span_id, output_data={"chunk_count": 1})
        # 阶段结束恢复到解析根
        self.assertIs(obs._current_span.get(), handle)
        generations = self.fake.generations()
        self.assertEqual(len(generations), 1)
        # 隶属阶段 span（解析根的第一个子节点）
        self.assertIs(generations[0].parent, handle.span.children[0])
        obs.close_business_trace(handle)
