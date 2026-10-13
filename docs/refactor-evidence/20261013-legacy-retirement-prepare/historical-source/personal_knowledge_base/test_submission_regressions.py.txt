"""Commit-readiness regressions, using synthetic identities and isolated sinks."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase, override_settings

from . import event_log, observability as obs
from .authentication import issue_tokens
from .models import Session, Tenant, User
from .test_langfuse_observability import LangfuseFakeMixin
from .test_langfuse_sdk_contract import RealSdkContractMixin


@override_settings(LANGFUSE_TRACE_LINKS_ENABLED=True,
                   LANGFUSE_UI_BASE_URL="https://traces.example.test",
                   LANGFUSE_UI_PROJECT_ID="synthetic-project")
class BearerTraceLinkTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="submission-review", api_key="submission-review")
        self.user = User.objects.create(username="submission-admin", email="submission@fixture.invalid",
                                        tenant=self.tenant, is_system_admin=True)
        self.session = Session.objects.create(tenant=self.tenant, user_id=self.user.id)
        event_log.append_event(self.session, "turn", event_log.OBSERVABILITY_TRACE_LINKED,
                               {"provider": "langfuse", "trace_id": "a" * 32})
        self.token, _ = issue_tokens(self.user)

    def get_turn(self, **headers):
        response = Client().get(f"/api/v1/sessions/{self.session.id}/trajectory", **headers)
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]["turns"][0]

    def test_real_bearer_admin_receives_link(self):
        turn = self.get_turn(HTTP_AUTHORIZATION="Bearer " + self.token)
        self.assertEqual(turn["observability"].get("trace_url"),
                         "https://traces.example.test/project/synthetic-project/traces/" + "a" * 32)

    @override_settings(LANGFUSE_UI_PROJECT_ID="")
    def test_trace_link_uses_the_same_legacy_project_fallback_as_settings(self):
        with patch("personal_knowledge_base.langfuse_access.configuration", return_value={"project": "legacy-project"}):
            turn = self.get_turn(HTTP_AUTHORIZATION="Bearer " + self.token)
        self.assertEqual(turn["observability"].get("trace_url"),
                         "https://traces.example.test/project/legacy-project/traces/" + "a" * 32)

    def test_regular_user_and_api_key_receive_no_link(self):
        self.user.is_system_admin = False
        self.user.save(update_fields=["is_system_admin"])
        for headers in [{"HTTP_AUTHORIZATION": "Bearer " + self.token},
                        {"HTTP_X_API_KEY": self.tenant.api_key}]:
            with self.subTest(headers=list(headers)):
                self.assertNotIn("trace_url", self.get_turn(**headers)["observability"])

    @override_settings(LANGFUSE_TRACE_LINKS_ENABLED=False)
    def test_disabled_links_hide_admin_link(self):
        self.assertNotIn("trace_url", self.get_turn(HTTP_AUTHORIZATION="Bearer " + self.token)["observability"])

    def test_completion_keeps_association_when_trace_id_is_missing_or_empty(self):
        for value in [None, ""]:
            with self.subTest(value=value):
                data = {"content": "synthetic answer"}
                if value is not None:
                    data["langfuse_trace_id"] = value
                event_log.append_event(self.session, "turn", event_log.TURN_COMPLETED, data)
                turn = event_log.fold_trajectory(event_log.events_for_session(self.session.id))["turns"][0]
                self.assertEqual(turn["langfuse_trace_id"], "a" * 32)
                self.assertEqual(turn["observability"]["trace_id"], "a" * 32)

    def test_completion_can_provide_an_explicit_trace_id(self):
        event_log.append_event(self.session, "turn", event_log.TURN_COMPLETED,
                               {"content": "synthetic answer", "langfuse_trace_id": "b" * 32})
        turn = event_log.fold_trajectory(event_log.events_for_session(self.session.id))["turns"][0]
        self.assertEqual(turn["langfuse_trace_id"], "b" * 32)


class SdkSamplingConfigurationTests(RealSdkContractMixin):
    def test_facade_disables_sdk_sampling_even_when_environment_requests_half(self):
        from langfuse import Langfuse

        def local_client(**kwargs):
            return Langfuse(**kwargs, timeout=2, flush_interval=1)

        with override_settings(LANGFUSE_ENABLED=True, LANGFUSE_PUBLIC_KEY="pk-submission-" + uuid4().hex,
                               LANGFUSE_SECRET_KEY="sk-synthetic", LANGFUSE_BASE_URL=self.sink_host,
                               LANGFUSE_SAMPLE_RATE=0.5), \
             patch.dict(os.environ, {"LANGFUSE_SAMPLE_RATE": "0.5"}), \
             patch.object(obs, "_client", None), patch.object(obs, "_client_ready", False), \
             patch.object(obs, "Langfuse", side_effect=local_client):
            client = obs.get_langfuse()
            self.assertIsNotNone(client)
            self.assertEqual(client._resources.sample_rate, 1.0)


class RootSamplingTests(LangfuseFakeMixin, SimpleTestCase):
    def setUp(self):
        self.install_fake_client()

    def test_sampling_keeps_or_discards_the_whole_subtree(self):
        for rate, draw, expected in [(0, 0, 0), (0.5, 0.25, 3), (0.5, 0.75, 0), (1, 0.99, 3)]:
            with self.subTest(rate=rate, draw=draw), override_settings(LANGFUSE_SAMPLE_RATE=rate), \
                 patch.object(obs.random, "random", return_value=draw):
                before = len(self.fake.observations)
                root = obs.start_business_trace("sample.root")
                with obs.child_span("sample.child"):
                    call = obs.start_model_call(model_call_id="synthetic", model="synthetic")
                    obs.finish_model_call(call, usage={"prompt_tokens": 1})
                obs.close_business_trace(root)
                self.assertEqual(len(self.fake.observations) - before, expected)


class EvaluationObservationTests(LangfuseFakeMixin, SimpleTestCase):
    def setUp(self):
        self.install_fake_client()

    def test_original_row_and_failed_example_are_preserved(self):
        examples = [{"example_id": "failed-A", "row_index": 0, "valid": False,
                     "error": "synthetic answer failure"},
                    {"example_id": "scored-B", "row_index": 3, "valid": True, "faithfulness": 0.8}]
        for _ in range(2):
            obs.report_evaluation_run(name="synthetic.eval", task_run_id="task", examples=examples)
        children = [s for s in self.fake.observations if s.name == "evaluation.example"]
        self.assertEqual([s.attrs["metadata"]["row_index"] for s in children], [0, 3, 0, 3])
        self.assertEqual(children[0].score_calls, [])
        self.assertEqual(children[0].level, "ERROR")
        self.assertEqual(children[1].score_calls, children[3].score_calls)

    def test_invalid_example_never_emits_numeric_scores(self):
        obs.report_evaluation_run(name="synthetic.eval", task_run_id="task",
            examples=[{"example_id": "failed", "row_index": 2, "valid": False, "faithfulness": 0.8}])
        child = next(s for s in self.fake.observations if s.name == "evaluation.example")
        self.assertEqual(child.score_calls, [])


class BenchmarkScenarioTests(SimpleTestCase):
    def test_script_verifies_enabled_and_unreachable_scenarios_with_default_disabled(self):
        with tempfile.TemporaryDirectory(prefix="submission-bench-") as directory:
            env = {**os.environ, "DJANGO_DB_PATH": str(Path(directory) / "isolated.sqlite3"),
                   "LANGFUSE_ENABLED": "false", "LANGFUSE_AUTOSTART": "false",
                   "APP_TASKS_SYNC": "true", "LANGFUSE_SAMPLE_RATE": "0.5",
                   "LANGFUSE_BASE_URL": "https://must-not-contact.fixture.invalid"}
            completed = subprocess.run([sys.executable, str(settings.BASE_DIR / "scripts/bench_langfuse_overhead.py")],
                                       cwd=settings.BASE_DIR, env=env, text=True, capture_output=True, timeout=45)
        self.assertEqual(completed.returncode, 0, completed.stderr[-3000:])
        self.assertIn("validation=PASS", completed.stdout)
        self.assertIn("observations=600", completed.stdout)
        self.assertIn("observations=0", completed.stdout)
