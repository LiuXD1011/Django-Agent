"""真实 Langfuse SDK 契约测试（第 2 层测试策略）。

使用真实 langfuse SDK 对象（固定 3.15.0），在传输/导出边界接本地内存 OTel
SpanExporter——不走网络、不用万能 Fake。验证点与 P0 实证一致：

- trace_id（远端 trace）与 observation_id（节点）是不同标识；
- session_id/user_id 只能经 update_trace 设置（start_span 传参会 TypeError）；
- 嵌套子节点共享 trace_id，父子关系经 parent span id 表达；
- usage_details 的键与导出属性格式；
- 跨线程用 TraceContext({trace_id, parent_span_id}) 显式接续；
- 门面句柄/生命周期/幂等结束/上下文恢复在真实 SDK 上的行为。

上报目标端口固定为无人监听的 127.0.0.1 端口，测试内将 no_proxy 收紧为
后缀形式，使导出器直连快速失败（进程内环境变量，不改动用户 shell）。
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from django.test import SimpleTestCase, override_settings

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

from personal_knowledge_base import observability as obs


class _OtelSinkHandler(BaseHTTPRequestHandler):
    """本地传输边界：接收 OTLP POST，丢弃 body，返回 200（HTTP 200 时 SDK 不重试）。"""

    def do_POST(self):  # noqa: N802
        try:
            length = int(self.headers.get("content-length", 0) or 0)
            if length:
                self.rfile.read(length)
            self.server.received_requests += 1
            self.send_response(200)
            self.end_headers()
        except Exception:
            pass

    def log_message(self, *args, **kwargs):  # 静默
        pass


class MemorySpanExporter(SpanExporter):
    """收集导出的 OTel span，供断言真实 SDK 的序列化结果。"""

    def __init__(self):
        super().__init__()
        self.spans = []
        self._lock = threading.Lock()

    def export(self, spans):
        with self._lock:
            self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def by_name(self, name):
        with self._lock:
            return [s for s in self.spans if s.name == name]


class RealSdkContractMixin(SimpleTestCase):
    """构造真实 SDK 客户端：内存导出器 + 本地 HTTP sink（真实传输边界）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sink = ThreadingHTTPServer(("127.0.0.1", 0), _OtelSinkHandler)
        cls.sink.received_requests = 0
        cls.sink_thread = threading.Thread(target=cls.sink.serve_forever, daemon=True)
        cls.sink_thread.start()
        cls.sink_host = f"http://127.0.0.1:{cls.sink.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        try:
            cls.sink.shutdown()
            cls.sink.server_close()
        except Exception:
            pass
        super().tearDownClass()

    def setUp(self):
        self.enterContext(override_settings(LANGFUSE_ENABLED=True))
        self.exporter = MemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        # 收紧 no_proxy（后缀形式），绕过 shell 里 127.* 通配不生效的代理劫持
        self._old_no_proxy = (os.environ.get("no_proxy"), os.environ.get("NO_PROXY"))
        os.environ["no_proxy"] = "127.0.0.1,localhost"
        os.environ["NO_PROXY"] = "127.0.0.1,localhost"

        from langfuse import Langfuse

        self.client = Langfuse(
            # 每个测试唯一 key：避免 LangfuseResourceManager 按 public_key 复用单例
            public_key=f"pk-test-{id(self)}",
            secret_key="sk-test-local",
            host=self.sink_host,
            tracer_provider=provider,
            timeout=5,
            flush_at=64,
            # SDK 双口径陷阱：批量处理器按毫秒、score 消费线程按秒解释 flush_interval；
            # 传 1（=1s）保证 atexit shutdown 的 join 在 1s 内返回，传 1000 会挂死进程退出。
            flush_interval=1,
        )
        # 门面注入真实客户端（等价测试文件中 Fake 的注入方式）
        self._old_client = obs._client
        self._old_ready = obs._client_ready
        obs._client = self.client
        obs._client_ready = True
        self.addCleanup(self._restore)

    def _restore(self):
        obs._client = self._old_client
        obs._client_ready = self._old_ready
        obs._current_span.set(None)
        # 注意：不调用 client.shutdown()——SDK 3.15.0 的 shutdown 会 join 阻塞在
        # queue.get() 的 score-ingestion 消费线程（空闲时永不返回）。用有界 flush。
        try:
            self.client.flush()
        except Exception:
            pass
        if self._old_no_proxy[0] is None:
            os.environ.pop("no_proxy", None)
        else:
            os.environ["no_proxy"] = self._old_no_proxy[0]
        if self._old_no_proxy[1] is None:
            os.environ.pop("NO_PROXY", None)
        else:
            os.environ["NO_PROXY"] = self._old_no_proxy[1]

    @staticmethod
    def _hex_trace(span) -> str:
        return format(span.context.trace_id, "032x")

    @staticmethod
    def _hex_span_id(span) -> str:
        return format(span.context.span_id, "016x")


class SdkIdContractTests(RealSdkContractMixin):
    def test_start_span_rejects_session_kwargs(self):
        """v3 契约：start_span 不接受 session_id/user_id（历史实现的静默丢失点）。"""
        with self.assertRaises(TypeError):
            self.client.start_span(name="chat.turn", session_id="s1", user_id="u1")

    def test_trace_and_observation_ids_are_distinct(self):
        handle = obs.start_business_trace("chat.turn", metadata={"request_id": "req-1"})
        self.assertIsNotNone(handle)
        self.assertNotEqual(handle.trace_id, "")
        self.assertNotEqual(handle.observation_id, "")
        self.assertNotEqual(handle.trace_id, handle.observation_id)
        self.assertEqual(len(handle.trace_id), 32)
        self.assertEqual(len(handle.observation_id), 16)
        obs.close_business_trace(handle, output={"status": "completed"})

        exported = self.exporter.by_name("chat.turn")
        self.assertEqual(len(exported), 1)
        self.assertEqual(self._hex_trace(exported[0]), handle.trace_id)
        self.assertEqual(self._hex_span_id(exported[0]), handle.observation_id)

    def test_update_trace_sets_session_and_user(self):
        handle = obs.start_business_trace("chat.turn", session_id="sess-42", user_id="user-7")
        self.assertIsNotNone(handle)
        obs.close_business_trace(handle)

        exported = self.exporter.by_name("chat.turn")
        self.assertEqual(len(exported), 1)
        attrs = exported[0].attributes or {}
        self.assertEqual(attrs.get("session.id"), "sess-42")
        self.assertEqual(attrs.get("user.id"), "user-7")

    def test_child_nesting_shares_trace(self):
        handle = obs.start_business_trace("chat.turn")
        with obs.child_span("rag.retrieve", metadata={"kb_count": 2}) as child:
            self.assertIsNotNone(child)
        obs.close_business_trace(handle)

        roots = self.exporter.by_name("chat.turn")
        children = self.exporter.by_name("rag.retrieve")
        self.assertEqual(len(roots), 1)
        self.assertEqual(len(children), 1)
        self.assertEqual(self._hex_trace(children[0]), self._hex_trace(roots[0]))
        self.assertEqual(format(children[0].parent.span_id, "016x"), self._hex_span_id(roots[0]))

    def test_generation_usage_details_contract(self):
        handle = obs.start_business_trace("chat.turn")
        mc = obs.start_model_call(
            model_call_id="mc-1", model="test-model", provider="unit", scenario="chat",
        )
        self.assertIsNotNone(mc)
        obs.finish_model_call(
            mc,
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150,
                   "cached_tokens": 20, "reasoning_tokens": 10},
            output_preview="ok",
        )
        obs.close_business_trace(handle)

        exported = self.exporter.by_name("llm.chat")
        self.assertEqual(len(exported), 1)
        attrs = exported[0].attributes or {}
        self.assertEqual(attrs.get("langfuse.observation.type"), "generation")
        self.assertEqual(attrs.get("langfuse.observation.model.name"), "test-model")
        usage = attrs.get("langfuse.observation.usage_details")
        if isinstance(usage, str):  # 属性以 JSON 字符串序列化
            usage = json.loads(usage)
        self.assertEqual(usage["input"], 80)
        self.assertEqual(usage["output"], 40)
        self.assertEqual(usage["total"], 150)
        self.assertEqual(usage["input_cached_tokens"], 20)
        self.assertEqual(usage["output_reasoning_tokens"], 10)
        # metadata 关联 model_call_id：SDK 将 metadata 扁平化为 metadata.<key> 属性
        attrs_map = exported[0].attributes or {}
        nested_meta = attrs_map.get("langfuse.observation.metadata")
        if isinstance(nested_meta, str):
            nested_meta = json.loads(nested_meta)
        model_call_id = (nested_meta or {}).get("model_call_id") if isinstance(nested_meta, dict) else None
        if model_call_id is None:
            model_call_id = attrs_map.get("langfuse.observation.metadata.model_call_id")
        self.assertEqual(model_call_id, "mc-1")
        # LOG_CONTENT=false 时 output 预览不上报
        self.assertNotIn("langfuse.observation.output", attrs)

    def test_rerank_span_finishes_with_error_without_usage_argument(self):
        root = obs.start_business_trace("chat.turn")
        call = obs.start_model_call(model_call_id="rerank-1", model="reranker",
                                    scenario="rerank", as_type="span")
        self.assertIsNotNone(call)
        obs.finish_model_call(call, usage={"prompt_tokens": 4}, status="failed", error="synthetic failure")
        obs.close_business_trace(root)
        exported = self.exporter.by_name("llm.rerank")
        self.assertEqual(len(exported), 1)
        self.assertEqual(exported[0].attributes.get("langfuse.observation.level"), "ERROR")
        self.assertNotIn("langfuse.observation.usage_details", exported[0].attributes)

    def test_standalone_lifecycle_with_real_sdk(self):
        with override_settings(LANGFUSE_ORPHAN_MODE="standalone"):
            call = obs.start_model_call(model_call_id="standalone-1", model="m", scenario="standalone")
            self.assertIsNotNone(call)
            obs.finish_model_call(call, usage={"prompt_tokens": 4})
        self.assertEqual(len(self.exporter.by_name("llm.standalone")), 1)

    def test_finish_model_call_is_idempotent(self):
        handle = obs.start_business_trace("chat.turn")
        mc = obs.start_model_call(model_call_id="mc-2", model="m", scenario="chat")
        obs.finish_model_call(mc, usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})
        obs.finish_model_call(mc, usage={"prompt_tokens": 9, "completion_tokens": 9, "total_tokens": 18})
        obs.close_business_trace(handle)

        exported = self.exporter.by_name("llm.chat")
        self.assertEqual(len(exported), 1)
        usage = (exported[0].attributes or {}).get("langfuse.observation.usage_details")
        if isinstance(usage, str):
            usage = json.loads(usage)
        self.assertEqual((usage or {}).get("input"), 1)  # 晚到的第二次 finish 不覆盖

    def test_cross_thread_trace_context_propagation(self):
        """v3 跨线程契约：TraceContext({trace_id, parent_span_id}) 显式接续。"""
        handle = obs.start_business_trace("agent.run")
        self.assertIsNotNone(handle)

        errors = []

        def worker():
            try:
                child = self.client.start_span(
                    trace_context={"trace_id": handle.trace_id, "parent_span_id": handle.observation_id},
                    name="agent.iteration",
                    metadata={"iteration": 1},
                )
                child.end()
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertEqual(errors, [])

        exported = self.exporter.by_name("agent.iteration")
        self.assertEqual(len(exported), 1)
        self.assertEqual(self._hex_trace(exported[0]), handle.trace_id)
        self.assertEqual(format(exported[0].parent.span_id, "016x"), handle.observation_id)
        obs.close_business_trace(handle)


class SdkFacadeLifecycleTests(RealSdkContractMixin):
    def test_close_restores_parent_scope(self):
        root = obs.start_business_trace("chat.turn")
        self.assertIsNotNone(root)
        inner = obs.start_business_trace("agent.run")  # 嵌套业务节点
        self.assertIsNotNone(inner)
        self.assertIs(obs._current_span.get(), inner)
        obs.close_business_trace(inner)
        # 内层结束恢复外层，而不是清空（A11 场景）
        self.assertIs(obs._current_span.get(), root)
        obs.close_business_trace(root)
        self.assertIsNone(obs._current_span.get())

    def test_close_is_idempotent_under_race(self):
        handle = obs.start_business_trace("chat.turn")
        self.assertIsNotNone(handle)
        results = []
        barrier = threading.Barrier(4)

        def closer():
            barrier.wait()
            results.append(handle.close(output={"status": "completed"}))

        threads = [threading.Thread(target=closer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count(True), 1)
        self.assertEqual(len(self.exporter.by_name("chat.turn")), 1)
        obs.close_business_trace(handle)  # 兼容入口的二次关闭也安全
        self.assertEqual(len(self.exporter.by_name("chat.turn")), 1)

    def test_business_exception_propagates_through_child_span(self):
        handle = obs.start_business_trace("chat.turn")
        with self.assertRaises(RuntimeError):
            with obs.child_span("rag.retrieve"):
                raise RuntimeError("business failure")
        # 业务异常原样传播；child span 仍被关闭；root 需显式关闭
        self.assertEqual(len(self.exporter.by_name("rag.retrieve")), 1)
        obs.close_business_trace(handle, status="failed", error="business failure")

        exported = self.exporter.by_name("chat.turn")
        self.assertEqual(len(exported), 1)
        self.assertEqual(exported[0].status.status_code.name, "ERROR")

    def test_llm_call_context_copy_on_write(self):
        token = obs.set_llm_call_context(session_id="s1", request_id="r1", iteration=1)
        snapshot = dict(obs.get_llm_call_context())
        obs.update_llm_call_context(iteration=2)
        current = obs.get_llm_call_context()
        # 快照不被原地修改，当前值整体替换
        self.assertEqual(snapshot["iteration"], 1)
        self.assertEqual(current["iteration"], 2)
        self.assertIsNot(snapshot, current)
        obs.reset_llm_call_context(token)
        self.assertIsNone(obs.get_llm_call_context())

    def test_disabled_by_switch_makes_no_calls(self):
        # ENABLED=False 时（客户端未初始化态）不创建任何对象、不出网
        obs._client = None
        obs._client_ready = False
        with override_settings(LANGFUSE_ENABLED=False):
            handle = obs.start_business_trace("chat.turn")
            self.assertIsNone(handle)
            self.assertFalse(obs.langfuse_enabled())
        self.assertEqual(len(self.exporter.spans), 0)
