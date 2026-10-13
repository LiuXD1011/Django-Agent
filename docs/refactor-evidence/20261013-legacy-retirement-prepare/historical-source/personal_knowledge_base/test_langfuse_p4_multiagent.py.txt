"""P4：并行工具与多 Agent 的追踪语义测试（A08/A09/A10/A11 聚焦单元）。

- 并行任务：父线程为每个任务独立 copy_context()，worker 内创建的 span 嵌套在
  同一 trace 下且 observation id 互不相同（无串扰）；
- detached 子代理：不继承父 _current_span（引擎建新根），LLM 归属上下文显式
  携带 actor_id/agent_type/父 request_id；
- 工具 span 包围真实执行时间（串行路径内联包裹）。
"""
import contextvars
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.test import TestCase, override_settings

from personal_knowledge_base import observability as obs
from personal_knowledge_base.models import Tenant

from personal_knowledge_base.test_langfuse_observability import LangfuseFakeMixin


class ParallelContextPropagationTests(LangfuseFakeMixin, TestCase):
    """A08/A10：每个并行任务独立复制 Context，父级正确、无串扰。"""

    def setUp(self):
        self.install_fake_client()
        self.tenant = Tenant.objects.create(name="p4-parallel", api_key="p4-parallel")

    def test_parallel_tasks_nest_under_root_without_cross_talk(self):
        handle = obs.start_business_trace("agent.run", session_id="s1")
        results = {}

        def work(name: str, sleep_s: float):
            # 模拟 _execute_single_tool 在 worker 内创建子 span
            with obs.child_span(f"tool.{name}", metadata={"worker": name}) as span:
                time.sleep(sleep_s)
            # child_span 退出后恢复的当前节点是根句柄
            results[name] = {"span": span, "current": obs._current_span.get()}
            return name

        with ThreadPoolExecutor(max_workers=2) as pool:
            # 与 agent_engine 并行工具路径一致：父线程 copy_context，任务独立运行
            futures = [
                pool.submit(contextvars.copy_context().run, work, "a", 0.03),
                pool.submit(contextvars.copy_context().run, work, "b", 0.01),
            ]
            names = [f.result() for f in futures]

        self.assertEqual(sorted(names), ["a", "b"])
        tool_spans = [item for item in self.fake.observations if item.name.startswith("tool.")]
        self.assertEqual(len(tool_spans), 2)
        # 两个 worker 都看到同一个根（trace 一致），span 对象互不相同
        for info in results.values():
            self.assertIs(info["current"], handle)
        self.assertIsNot(results["a"]["span"], results["b"]["span"])
        # 两个工具 span 都是根的直接子节点
        for span in tool_spans:
            self.assertIs(span.parent, handle.span)
            self.assertTrue(span.ended)
        obs.close_business_trace(handle)

    def test_root_sample_rate_zero_disables_subtree(self):
        """根级采样为 0 时不建根，子树整体消失（子节点随根继承）。"""
        from django.test import override_settings
        with override_settings(LANGFUSE_SAMPLE_RATE=0.0):
            handle = obs.start_business_trace("agent.run", session_id="s1")
            self.assertIsNone(handle.span)
            self.assertEqual(handle.trace_id, "")
            with obs.child_span("tool.x") as span:
                self.assertIsNone(span)
            obs.close_business_trace(handle)
            self.assertIsNone(obs._current_span.get())
        self.assertEqual(self.fake.observations, [])


class ToolSpanWrapsExecutionTests(LangfuseFakeMixin, TestCase):
    """A08：工具 span 包围真实执行（时间覆盖 sleep），而非事后补造。"""

    def setUp(self):
        self.install_fake_client()

    @override_settings(LANGFUSE_LOG_CONTENT=True)
    def test_serial_tool_span_covers_real_execution_time(self):
        handle = obs.start_business_trace("agent.run", session_id="s1")
        ctx = obs.TraceContext(trace_id=handle.trace_id)
        sleep_s = 0.05

        with obs.trace_tool_execution(ctx, "kb.search", {"query": "q"}) as span:
            time.sleep(sleep_s)
            span["output"] = "result"

        tool_span = [i for i in self.fake.observations if i.name == "tool.kb.search"][0]
        self.assertTrue(tool_span.ended)
        output_payload = tool_span.updates[-1]["output"]
        self.assertGreaterEqual(output_payload["duration_ms"], int(sleep_s * 1000) - 5)
        self.assertEqual(output_payload["output"], "result")
        obs.close_business_trace(handle)


class DetachedSubagentTests(LangfuseFakeMixin, TestCase):
    """A09：detached 子代理建新根；LLM 归属上下文携带 actor 信息与父 request_id。"""

    def setUp(self):
        self.install_fake_client()
        self.tenant = Tenant.objects.create(name="p4-detached", api_key="p4-detached")

    @override_settings(APP_TASKS_SYNC=True)
    def test_spawn_does_not_inherit_parent_span(self):
        from personal_knowledge_base.agent_actor import ActorRunner
        from personal_knowledge_base.models import Session

        session = Session.objects.create(tenant=self.tenant, title="p4")
        parent_actor = __import__("personal_knowledge_base.agent_actor", fromlist=["ActorRegistry"]).ActorRegistry.ensure_main_actor(session)
        captured = {}

        def fake_execute(actor, context, timeout_ms=120000):
            captured["current_span"] = obs._current_span.get()
            captured["call_context"] = dict(obs.get_llm_call_context() or {})
            captured["context"] = context
            return None

        handle = obs.start_business_trace("chat.turn", session_id=str(session.id))
        token = obs.set_llm_call_context(session_id=str(session.id), request_id="req-parent", actor_id="", agent_type="main")
        try:
            with patch.object(ActorRunner, "_execute_actor", side_effect=fake_execute):
                actor = ActorRunner.spawn_subagent(
                    parent_actor, "doc_retriever", "do research",
                    {"session_id": str(session.id), "tenant": self.tenant},
                )
        finally:
            obs.reset_llm_call_context(token)
        obs.close_business_trace(handle)

        # worker 内无父 span（新根），上下文携带 actor 身份与父 request_id
        self.assertIsNone(captured["current_span"])
        self.assertEqual(captured["call_context"]["actor_id"], actor.actor_id)
        self.assertEqual(captured["call_context"]["agent_type"], actor.agent_type)
        self.assertEqual(captured["call_context"]["request_id"], "req-parent")
        # 父 trace 引用进入子上下文，供引擎写入新根 metadata
        self.assertEqual(captured["context"]["parent_trace_id"], handle.trace_id)
        self.assertEqual(captured["context"]["originating_request_id"], "req-parent")
