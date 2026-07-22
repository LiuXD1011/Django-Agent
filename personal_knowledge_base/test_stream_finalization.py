from unittest.mock import patch

from django.test import RequestFactory, TestCase

from personal_knowledge_base.agent_engine import AgentResult
from personal_knowledge_base.agent_tools import ToolResult
from personal_knowledge_base.authentication import issue_tokens
from personal_knowledge_base.models import Message, Session, Tenant, User
from personal_knowledge_base.stream_manager import stream_manager
from personal_knowledge_base.stream_protocol import complete_message_with_error


class _SuccessfulEngine:
    def __init__(self, *_args, **_kwargs):
        pass

    def execute(self, _query, history=None, context_str="", on_event=None):
        return AgentResult(
            content="late success",
            steps=[],
            total_iterations=1,
            duration_ms=7,
        )


class _FailingEngine:
    def __init__(self, *_args, **_kwargs):
        pass

    def execute(self, _query, history=None, context_str="", on_event=None):
        raise RuntimeError("secret upstream credential")


class StreamFinalizationTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Finalization tenant", api_key="finalization-key")
        self.user = User.objects.create(
            username="finalization-user",
            email="finalization@example.com",
            password_hash="unused",
            tenant=self.tenant,
        )
        token, _ = issue_tokens(self.user)
        self.authorization = f"Bearer {token}"
        self.session = Session.objects.create(tenant=self.tenant, title="Finalization test")
        self.message_ids = []

    def tearDown(self):
        for message_id in self.message_ids:
            stream_manager.remove_stream(message_id)

    def _message(self, suffix, *, content="", is_completed=False):
        message = Message.objects.create(
            session=self.session,
            request_id=f"finalization-{suffix}",
            role="assistant",
            content=content,
            rendered_content=content,
            is_completed=is_completed,
        )
        self.message_ids.append(message.id)
        return message

    def _generation_kwargs(self, message):
        return {
            "assistant_msg_id": message.id,
            "session_id": self.session.id,
            "user_msg_id": "user-message",
            "query": "query",
            "history_msgs": [],
            "agent_context": "",
            "agent_config": {},
            "refs": [],
            "tenant": self.tenant,
            "user_id": self.user.id,
            "enable_memory": False,
        }

    def test_error_compare_and_set_does_not_replace_existing_success(self):
        message = self._message("existing-success", content="successful answer", is_completed=True)

        complete_message_with_error(message.id, "等待超时")

        message.refresh_from_db()
        self.assertEqual(message.content, "successful answer")
        self.assertEqual(message.rendered_content, "successful answer")
        self.assertTrue(message.is_completed)

    def test_late_success_cannot_replace_timeout_in_active_or_legacy_worker(self):
        from chat import views as active_views
        from personal_knowledge_base import views as legacy_views

        cases = (
            (active_views, "chat.views.AgentEngine"),
            (legacy_views, "personal_knowledge_base.agent_engine.AgentEngine"),
        )
        for views_module, engine_target in cases:
            with self.subTest(module=views_module.__name__):
                message = self._message(views_module.__name__)
                complete_message_with_error(message.id, "等待超时")

                with (
                    patch(engine_target, _SuccessfulEngine),
                    patch.object(views_module, "schedule_chat_maintenance"),
                ):
                    views_module._run_agent_generation(**self._generation_kwargs(message))

                message.refresh_from_db()
                self.assertEqual(message.content, "等待超时")
                self.assertEqual(message.rendered_content, "等待超时")
                self.assertTrue(message.is_completed)

    def test_producer_failure_uses_generic_message_in_db_and_stream(self):
        from chat import views as active_views
        from personal_knowledge_base import views as legacy_views

        cases = (
            (active_views, "chat.views.AgentEngine"),
            (legacy_views, "personal_knowledge_base.agent_engine.AgentEngine"),
        )
        for views_module, engine_target in cases:
            with self.subTest(module=views_module.__name__):
                message = self._message(f"failure-{views_module.__name__}")
                stream = stream_manager.ensure_stream(message.id, self.session.id)

                with patch(engine_target, _FailingEngine):
                    views_module._run_agent_generation(**self._generation_kwargs(message))

                message.refresh_from_db()
                error_events = [event for event in stream.get_events() if event.event_type == "error"]
                self.assertEqual(message.content, "生成失败")
                self.assertEqual(message.rendered_content, "生成失败")
                self.assertEqual([event.data["content"] for event in error_events], ["生成失败"])
                self.assertNotIn("secret upstream credential", str(error_events))

    def test_late_producer_failure_does_not_publish_error_after_success(self):
        from chat import views as active_views
        from personal_knowledge_base import views as legacy_views

        cases = (
            (active_views, "chat.views.AgentEngine"),
            (legacy_views, "personal_knowledge_base.agent_engine.AgentEngine"),
        )
        for views_module, engine_target in cases:
            with self.subTest(module=views_module.__name__):
                message = self._message(
                    f"late-failure-{views_module.__name__}",
                    content="winning success",
                    is_completed=True,
                )
                stream = stream_manager.ensure_stream(message.id, self.session.id)

                with patch(engine_target, _FailingEngine):
                    views_module._run_agent_generation(**self._generation_kwargs(message))

                message.refresh_from_db()
                self.assertEqual(message.content, "winning success")
                self.assertFalse(any(event.event_type == "error" for event in stream.get_events()))

    def test_consumers_ignore_raw_error_event_content(self):
        from chat import views as active_views
        from personal_knowledge_base import views as legacy_views

        for views_module in (active_views, legacy_views):
            with self.subTest(module=views_module.__name__):
                message = self._message(f"consumer-{views_module.__name__}")
                stream = stream_manager.ensure_stream(message.id, self.session.id)
                stream.append_event("error", {"content": "private provider traceback"})
                request = RequestFactory().get(
                    f"/api/v1/sessions/continue-stream/{self.session.id}",
                    {"message_id": message.id},
                    HTTP_AUTHORIZATION=self.authorization,
                )

                response = views_module.continue_stream(request, self.session.id)
                body = b"".join(response.streaming_content).decode("utf-8")

                message.refresh_from_db()
                self.assertEqual(message.content, "生成失败")
                self.assertIn("生成失败", body)
                self.assertNotIn("private provider traceback", body)

    def test_timeout_consumer_replays_success_when_error_cas_loses(self):
        from chat import views as active_views
        from personal_knowledge_base import views as legacy_views

        for views_module in (active_views, legacy_views):
            with self.subTest(module=views_module.__name__):
                message = self._message(f"timeout-race-{views_module.__name__}")
                request = RequestFactory().get(
                    f"/api/v1/sessions/continue-stream/{self.session.id}",
                    {"message_id": message.id},
                    HTTP_AUTHORIZATION=self.authorization,
                )
                response = views_module.continue_stream(request, self.session.id)
                Message.objects.filter(id=message.id).update(
                    content="winning success",
                    rendered_content="winning success",
                    is_completed=True,
                )

                with patch.object(views_module, "CONTINUE_STREAM_MAX_WAIT_SECONDS", 0):
                    body = b"".join(response.streaming_content).decode("utf-8")

                self.assertIn("winning success", body)
                self.assertNotIn("等待超时", body)
                self.assertNotIn('"response_type": "error"', body)

    def test_tool_result_serialization_preserves_full_output(self):
        output = "x" * (16 * 1024 + 257)

        serialized = ToolResult(output=output).to_dict()

        self.assertEqual(serialized["output"], output)
