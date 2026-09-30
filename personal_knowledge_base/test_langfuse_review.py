"""Regression tests from the 2026-09-22 independent Langfuse review.
No real model calls or remote credentials; Django owns the isolated test DB.
"""
import contextvars
import json
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from chat import views
from personal_knowledge_base import event_log, observability as obs
from personal_knowledge_base.agent_engine import AgentResult
from personal_knowledge_base.model_usage import record_model_usage
from personal_knowledge_base.models import Message, Session, Tenant, User
from personal_knowledge_base.stream_manager import stream_manager
from personal_knowledge_base.test_langfuse_observability import LangfuseFakeMixin


@override_settings(LANGFUSE_ENABLED=True, LANGFUSE_LOG_CONTENT=False, LANGFUSE_SAMPLE_RATE=1.0)
class ReviewFacadeTests(LangfuseFakeMixin, SimpleTestCase):
    def setUp(self):
        self.install_fake_client()

    def test_disabled_switch_overrides_cached_client(self):
        with override_settings(LANGFUSE_ENABLED=False):
            self.assertIsNone(obs.get_langfuse())
            self.assertIsNone(obs.start_business_trace("disabled"))
        self.assertEqual(self.fake.observations, [])

    def test_exception_metadata_is_hidden_but_message_id_preserved(self):
        safe = obs._safe_metadata({"error": RuntimeError("PRIVATE_ERROR"), "assistant_message_id": "msg-1"})
        self.assertNotIn("PRIVATE_ERROR", json.dumps(safe))
        self.assertEqual(safe["assistant_message_id"], "msg-1")

    def test_standalone_lifecycle_creates_generation_without_parent(self):
        with override_settings(LANGFUSE_ORPHAN_MODE="standalone"):
            call = obs.start_model_call(model_call_id="call-1", model="m")
            self.assertIsNotNone(call)
            obs.finish_model_call(call, usage={"prompt_tokens": 3})
            self.assertEqual(len(self.fake.generations()), 1)
            self.assertTrue(self.fake.generations()[0].ended)

    def test_root_sampling_cannot_be_retried_by_nested_agent(self):
        with patch.object(obs, "_root_sampled", side_effect=[False, True]):
            root = obs.start_business_trace("chat.turn")
            child = obs.start_business_trace("agent.run")
            obs.close_business_trace(child)
            obs.close_business_trace(root)
        self.assertEqual(self.fake.observations, [])

    def test_sampled_out_root_blocks_orphan_standalone(self):
        with override_settings(LANGFUSE_ORPHAN_MODE="standalone"), patch.object(obs, "_root_sampled", return_value=False):
            root = obs.start_business_trace("chat.turn")
            obs.report_model_call(model="m", prompt_tokens=2)
            obs.close_business_trace(root)
        self.assertEqual(self.fake.observations, [])

    def test_cached_and_reasoning_usage_are_flat_exclusive_buckets(self):
        usage = obs._usage_details_from({"prompt_tokens": 100, "completion_tokens": 30,
            "total_tokens": 130, "cached_tokens": 80, "reasoning_tokens": 10})
        self.assertEqual(usage, {"input": 20, "output": 20, "total": 130,
            "input_cached_tokens": 80, "output_reasoning_tokens": 10})
        self.assertEqual(sum(v for k, v in usage.items() if k != "total"), usage["total"])

    def test_numeric_token_metadata_is_not_a_secret(self):
        safe = obs._safe_metadata({"prompt_tokens": 12, "total_tokens": 14, "api_key": "synthetic-key"})
        self.assertEqual(safe["prompt_tokens"], 12)
        self.assertNotIn("synthetic-key", json.dumps(safe))

    def test_content_disabled_covers_metadata_and_errors(self):
        root = obs.start_business_trace("chat.turn", metadata={"title": "PRIVATE_TITLE",
            "query": "PRIVATE_QUERY", "nested": {"content": "PRIVATE_DOCUMENT"}})
        obs.close_business_trace(root, output={"answer": "PRIVATE_ANSWER"},
            status="failed", error=RuntimeError("PRIVATE_EXCEPTION"))
        payload = json.dumps([{"metadata": s.attrs.get("metadata"), "updates": s.updates}
                             for s in self.fake.observations])
        self.assertNotIn("PRIVATE_", payload)

    def test_bearer_and_json_credentials_are_redacted(self):
        with override_settings(LANGFUSE_LOG_CONTENT=True):
            safe = obs._mask_secrets('Authorization: Bearer synthetic-bearer {"api_key": "synthetic-json"}')
        self.assertNotIn("synthetic-bearer", safe)
        self.assertNotIn("synthetic-json", safe)

    def test_child_scope_cleans_up_on_generator_exit(self):
        root = obs.start_business_trace("chat.turn")
        with self.assertRaises(GeneratorExit):
            with obs.child_span("cancelled-child"):
                raise GeneratorExit()
        self.assertIs(obs._current_span.get(), root)
        self.assertTrue(self.fake.observations[-1].ended)
        obs.close_business_trace(root)

    def test_failed_agent_is_not_reported_as_success(self):
        with self.assertRaises(RuntimeError):
            with obs.trace_agent_execution("s", "u", "question"):
                raise RuntimeError("synthetic failure")
        self.assertTrue(self.fake.roots()[0].ended)
        self.assertEqual(getattr(self.fake.roots()[0], "level", None), "ERROR")

    def test_tool_error_sets_error_level(self):
        root = obs.start_business_trace("chat.turn")
        with obs.trace_tool_execution(obs.TraceContext(trace_id=root.trace_id), "search", {}) as result:
            result["error"] = "synthetic failure"
        self.assertEqual(getattr(self.fake.observations[-1], "level", None), "ERROR")
        obs.close_business_trace(root)

    def test_failed_lifecycle_start_is_not_retried_after_call(self):
        root = obs.start_business_trace("chat.turn")
        with patch("personal_knowledge_base.model_usage.report_model_call") as legacy:
            record_model_usage(None, model_type="summary", model_call_id="already-attempted", generation=None)
        legacy.assert_not_called()
        obs.close_business_trace(root)

    def test_dataset_upload_has_stable_versioned_ids(self):
        with override_settings(LANGFUSE_UPLOAD_EVAL_DATASETS=True, LANGFUSE_LOG_CONTENT=True):
            for run, question in [("run-1", "synthetic one"), ("run-2", "synthetic one"), ("run-3", "synthetic two")]:
                obs.report_evaluation_run(name="eval", task_run_id=run, dataset_name="review",
                    entries=[{"question": question, "answer": "synthetic answer"}])
        items = self.fake.dataset_items
        self.assertTrue(items[0].get("id"))
        self.assertEqual(items[0]["id"], items[1]["id"])
        self.assertNotEqual(items[0]["id"], items[2]["id"])

    def test_dataset_upload_requires_content_opt_in(self):
        with override_settings(LANGFUSE_UPLOAD_EVAL_DATASETS=True):
            obs.report_evaluation_run(name="eval", task_run_id="r", dataset_name="review",
                entries=[{"question": "PRIVATE_QUERY", "answer": "PRIVATE_ANSWER"}])
        self.assertEqual(self.fake.dataset_items, [])


@override_settings(LANGFUSE_ENABLED=True, LANGFUSE_LOG_CONTENT=False, LANGFUSE_SAMPLE_RATE=1.0)
class ReviewChatTests(LangfuseFakeMixin, TestCase):
    def setUp(self):
        self.install_fake_client()
        self.tenant = Tenant.objects.create(name="review", api_key="review-key")
        self.user = User.objects.create(username="review", email="review@example.test",
            password_hash="unused", tenant=self.tenant, is_system_admin=True)
        self.session = Session.objects.create(tenant=self.tenant, title="review")
        self.factory = RequestFactory()

    def tearDown(self):
        for msg in Message.objects.filter(session=self.session):
            stream_manager.remove_stream(msg.id)

    def request(self, *, agent=False, stream=False, rag_error=None):
        req = self.factory.post("/", json.dumps({"query": "你好", "stream": stream, "enable_memory": False}),
            content_type="application/json")
        req.user = self.user
        rag = SimpleNamespace(intent="chitchat", search_query="hello", refs=[], degradations=[],
            memory_context="", system_prompt="synthetic", user_prompt="hello", kb_names="")
        self.jobs = []
        with ExitStack() as stack:
            stack.enter_context(patch.object(views, "auth_context", return_value=(self.user, self.tenant)))
            stack.enter_context(patch.object(views, "_build_agent_prefetch_context", return_value=("", "")))
            stack.enter_context(patch.object(views, "schedule_chat_maintenance"))
            stack.enter_context(patch.object(views, "run_database_background", side_effect=self.jobs.append))
            stack.enter_context(patch.object(views, "chat_completion", return_value="synthetic answer"))
            stack.enter_context(patch("personal_knowledge_base.rag_pipeline.run_rag_pipeline",
                side_effect=rag_error, return_value=rag))
            engine = stack.enter_context(patch.object(views, "AgentEngine"))
            engine.return_value.execute.return_value = AgentResult(content="synthetic answer", steps=[],
                total_iterations=1, duration_ms=1)
            return views.chat_endpoint(req, self.session.id, agent=agent)

    def test_sync_agent_completes(self):
        response = self.request(agent=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Message.objects.get(session=self.session, role="assistant").content, "synthetic answer")
        self.assertIsNone(obs._current_span.get())
        self.assertTrue(all(s.ended for s in self.fake.observations))

    def test_stream_handoff_does_not_leak_to_next_request(self):
        self.request(stream=True)
        self.assertIsNone(obs._current_span.get())
        self.request(stream=True)
        self.assertEqual(len(self.fake.roots()), 2)

    def test_rag_preparation_failure_closes_root_and_scope(self):
        with self.assertRaises(RuntimeError):
            self.request(rag_error=RuntimeError("synthetic retrieval failure"))
        self.assertIsNone(obs._current_span.get())
        self.assertTrue(self.fake.roots()[0].ended)
        self.assertEqual(self.fake.roots()[0].level, "ERROR")

    def test_agent_worker_failure_closes_root(self):
        msg = Message.objects.create(session=self.session, request_id="review-failure",
            role="assistant", content="", is_completed=False)
        with patch.object(views, "AgentEngine") as engine:
            engine.return_value.execute.side_effect = RuntimeError("synthetic agent failure")
            views._run_agent_generation(assistant_msg_id=msg.id, session_id=self.session.id,
                user_msg_id="unused", query="hello", history_msgs=[], agent_context="", agent_config={},
                refs=[], tenant=self.tenant, user_id=self.user.id, enable_memory=False,
                request_id=msg.request_id)
        self.assertIsNone(obs._current_span.get())
        self.assertTrue(self.fake.roots()[0].ended)
        self.assertEqual(self.fake.roots()[0].level, "ERROR")

    @override_settings(LANGFUSE_TRACE_LINKS_ENABLED=True, LANGFUSE_UI_BASE_URL="http://127.0.0.1:3000",
                       LANGFUSE_UI_PROJECT_ID="review-project")
    def test_real_system_admin_can_open_legacy_trace(self):
        event_log.append_event(self.session, "r", event_log.TURN_COMPLETED,
            {"content": "answer", "langfuse_trace_id": "a"*32})
        from django.test import Client
        from .authentication import issue_tokens
        token, _ = issue_tokens(self.user)
        response = Client().get(f"/api/v1/sessions/{self.session.id}/trajectory",
                                HTTP_AUTHORIZATION="Bearer " + token)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("/project/review-project/traces/" + "a"*32, json.dumps(data))

    def test_staff_attribute_is_not_platform_permission(self):
        self.assertFalse(views._langfuse_link_authorized(SimpleNamespace(is_staff=True,
            is_system_admin=False, is_active=True)))


    def test_sync_maintenance_uses_independent_root(self):
        from personal_knowledge_base.chat_runtime import schedule_chat_maintenance
        root = obs.start_business_trace("chat.turn")
        with patch("personal_knowledge_base.chat_runtime.run_database_background", side_effect=lambda fn: fn()), \
             patch("personal_knowledge_base.chat_runtime.close_old_connections"), \
             patch("personal_knowledge_base.chat_runtime._first_with_retry", return_value=None):
            schedule_chat_maintenance(tenant=self.tenant, user_message_id="u",
                assistant_message_id="a", session_id=self.session.id, query="q", answer="a", mode="rag")
        self.assertIs(obs._current_span.get(), root)
        roots = self.fake.roots()
        self.assertEqual(len(roots), 2)
        self.assertEqual(roots[1].name, "chat.maintenance")
        self.assertEqual(roots[1].attrs["metadata"]["originating_trace_id"], root.trace_id)
        self.assertTrue(roots[1].ended)
        obs.close_business_trace(root)


class ReviewDiagnosticsTests(SimpleTestCase):
    def test_display_endpoint_hides_credentials_and_query(self):
        from personal_knowledge_base.management.commands.langfuse_check import Command
        self.assertEqual(Command._display_url("https://user:secret@lf.example/path?token=private#fragment"),
                         "https://lf.example")

    def test_smoke_requires_root_parentage_and_ended_nodes(self):
        from personal_knowledge_base.management.commands.langfuse_check import Command
        def node(id, kind="SPAN", parent=None):
            return SimpleNamespace(id=id, type=kind, trace_id="t", parent_observation_id=parent,
                end_time="ended", usage=SimpleNamespace(input=42, output=17))
        root, child, gen = node("r"), node("c", parent="r"), node("g", "GENERATION", "r")
        trace = SimpleNamespace(id="t", session_id="s", observations=[root, child, gen])
        args = ("t", "s", "r", "c", "g", (42, 17))
        self.assertEqual(Command._remote_problems(trace, *args), [])
        gen.parent_observation_id = "c"
        self.assertIn("generation 父级不符", Command._remote_problems(trace, *args))
        gen.parent_observation_id = "r"
        root.end_time = None
        self.assertIn("root 尚未结束", Command._remote_problems(trace, *args))
        trace.observations.remove(root)
        self.assertIn("root 尚未入库", Command._remote_problems(trace, *args))

    def test_smoke_retries_incomplete_200_response(self):
        from io import StringIO
        from personal_knowledge_base.management.commands.langfuse_check import Command
        command = Command(stdout=StringIO())
        api = Mock()
        with patch("langfuse.api.client.FernLangfuse", return_value=api), \
             patch.object(command, "_remote_problems", side_effect=[["root 尚未入库"], []]), \
             patch("personal_knowledge_base.management.commands.langfuse_check.time.sleep"):
            result = command._verify_remote(trace_id="t", session_id="s", root_obs_id="r",
                child_obs_id="c", gen_obs_id="g", usage=(42,17), test_run_id="synthetic", deadline_s=2)
        self.assertEqual(result, 0)
        self.assertEqual(api.trace.get.call_count, 2)
