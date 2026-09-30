"""Thinking concurrency and detached context contracts on a disposable SQLite file."""
import json
import sqlite3
import tempfile
import threading
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.db import connections, OperationalError
from django.db.backends.sqlite3.base import DatabaseWrapper
from django.test import RequestFactory, SimpleTestCase, override_settings

from models_config import thinking_views
from . import thinking, observability
from .agent_actor import ActorRunner
from .models import Tenant, User, TenantMember, ModelConfig

BASE = "https://api.deepseek.com"
MODEL = "deepseek-v4-flash"


@override_settings(LLM_CHAT_BASE_URL=BASE, LLM_CHAT_MODEL=MODEL,
                   LLM_CHAT_API_KEY="fixture", LLM_USE_ENV_CHAT=True,
                   LANGFUSE_ENABLED=False)
class ThinkingRegressionTests(SimpleTestCase):
    databases = {"default"}

    def setUp(self):
        # Preserve the runner connection; every worker gets this temporary file.
        self.original_connection = connections["default"]
        self.original_config = connections.settings["default"]
        self.directory = tempfile.TemporaryDirectory(prefix="thinking-regressions-")
        config = deepcopy(self.original_connection.settings_dict)
        config["NAME"] = str(Path(self.directory.name, "thinking.sqlite3"))
        config["OPTIONS"] = {"timeout": 0.01}
        connections.settings["default"] = config
        connections["default"] = DatabaseWrapper(config, "default")
        with connections["default"].schema_editor() as editor:
            for model in (Tenant, User, TenantMember, ModelConfig):
                editor.create_model(model)
        # The app's connection hook sets a 30s busy timeout. Keep only this
        # disposable test connection short so retry contracts run promptly.
        with connections["default"].cursor() as cursor:
            cursor.execute("PRAGMA busy_timeout=10")
        self.tenant = Tenant.objects.create(name="fixture", api_key="thinking-regression")
        self.user = User.objects.create(username="fixture", email="fixture@example.invalid",
                                       tenant=self.tenant, is_system_admin=True)
        self.model = ModelConfig.objects.create(id="fixture-model", tenant=self.tenant,
            name=MODEL, type="KnowledgeQA", source="fixture",
            parameters={"base_url": BASE, "model": MODEL, "api_key": "fixture-old"})
        self.factory = RequestFactory()

    def tearDown(self):
        connections["default"].close()
        connections.settings["default"] = self.original_config
        connections["default"] = self.original_connection
        self.directory.cleanup()

    def put(self, revision=0, mode="off", *, role="model", model_id=None):
        request = self.factory.put("/unused", json.dumps({"revision": revision,
            "role": role, "policy": {"mode": mode, "effort": None}}),
            content_type="application/json")
        return thinking_views.thinking_settings(request, model_id or self.model.pk)

    def _simultaneous_put(self, *, role="model", model_id=None):
        barrier = threading.Barrier(2)
        outcomes = []
        normalize = thinking_views.normalize
        local = threading.local()

        def synchronized_normalize(*args):
            policy = normalize(*args)
            if not getattr(local, "validated", False):
                local.validated = True
                barrier.wait(timeout=5)
            return policy

        def update():
            try:
                response = self.put(role=role, model_id=model_id)
                outcomes.append((response.status_code, json.loads(response.content)))
            except Exception as exc:
                outcomes.append((type(exc).__name__, str(exc)))
            finally:
                connections["default"].close()

        with patch.object(thinking_views, "auth_context", return_value=(self.user, self.tenant)), \
             patch.object(thinking_views, "normalize", side_effect=synchronized_normalize):
            workers = [threading.Thread(target=update) for _ in range(2)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=10)
            self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(sorted(str(code) for code, _ in outcomes), ["200", "409"], outcomes)
        conflict = next(body for code, body in outcomes if code == 409)
        self.assertEqual(conflict["error"]["code"], "revision_conflict")

    def test_simultaneous_same_revision_has_one_winner(self):
        self._simultaneous_put()
        self.tenant.refresh_from_db()
        self.model.refresh_from_db()
        self.assertEqual(self.tenant.model_thinking_config["revision"], 1)
        self.assertEqual(self.model.parameters["thinking"]["mode"], "off")

    def test_simultaneous_environment_policy_has_one_winner(self):
        model_id = next(item["id"] for item in thinking_views.env_models(self.tenant)
                        if item["type"] == "KnowledgeQA")
        self._simultaneous_put(role="chat", model_id=model_id)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.model_thinking_config["revision"], 1)
        self.assertEqual(self.tenant.model_thinking_config["roles"]["chat"]["policy"]["mode"], "off")
        self.assertEqual(ModelConfig.objects.count(), 1)

    def test_model_failure_rolls_back_revision_and_policy(self):
        with patch.object(thinking_views, "auth_context", return_value=(self.user, self.tenant)), \
             patch.object(ModelConfig, "save", side_effect=RuntimeError("fixture save failure")):
            with self.assertRaisesRegex(RuntimeError, "fixture save failure"):
                self.put()
        self.tenant.refresh_from_db()
        self.model.refresh_from_db()
        self.assertEqual(self.tenant.model_thinking_config, {})
        self.assertNotIn("thinking", self.model.parameters)

    def test_claim_is_first_transaction_statement(self):
        statements = []

        def record(execute, sql, params, many, context):
            if context["connection"].in_atomic_block:
                statements.append(sql)
            return execute(sql, params, many, context)

        with connections["default"].execute_wrapper(record), \
             patch.object(thinking_views, "auth_context", return_value=(self.user, self.tenant)):
            self.assertEqual(self.put().status_code, 200)
        self.assertTrue(statements)
        self.assertTrue(statements[0].startswith('UPDATE "tenants"'), statements)

    def test_parameter_changes_during_validation_survive(self):
        normalize = thinking_views.normalize
        changed = False

        def change_credentials(*args):
            nonlocal changed
            result = normalize(*args)
            if not changed:
                changed = True
                ModelConfig.objects.filter(pk=self.model.pk).update(parameters={
                    **self.model.parameters, "api_key": "fixture-new", "temperature": 0.42})
            return result

        with patch.object(thinking_views, "auth_context", return_value=(self.user, self.tenant)), \
             patch.object(thinking_views, "normalize", side_effect=change_credentials):
            self.assertEqual(self.put().status_code, 200)
        self.model.refresh_from_db()
        self.assertEqual(self.model.parameters["api_key"], "fixture-new")
        self.assertEqual(self.model.parameters["temperature"], 0.42)
        self.assertEqual(self.model.parameters["thinking"]["mode"], "off")

    def test_endpoint_change_is_revalidated_and_claim_rolled_back(self):
        normalize = thinking_views.normalize
        changed = False

        def change_endpoint(*args):
            nonlocal changed
            result = normalize(*args)
            if not changed:
                changed = True
                ModelConfig.objects.filter(pk=self.model.pk).update(parameters={
                    **self.model.parameters, "base_url": "https://unknown.example"})
            return result

        with patch.object(thinking_views, "auth_context", return_value=(self.user, self.tenant)), \
             patch.object(thinking_views, "normalize", side_effect=change_endpoint):
            self.assertEqual(self.put().status_code, 400)
        self.tenant.refresh_from_db()
        self.model.refresh_from_db()
        self.assertEqual(self.tenant.model_thinking_config, {})
        self.assertNotIn("thinking", self.model.parameters)
        self.assertEqual(self.model.parameters["base_url"], "https://unknown.example")

    def test_sustained_sqlite_contention_returns_busy_without_changes(self):
        locker = sqlite3.connect(connections["default"].settings_dict["NAME"])
        locker.execute("BEGIN IMMEDIATE")
        try:
            with patch.object(thinking_views, "auth_context", return_value=(self.user, self.tenant)), \
                 patch("models_config.thinking_views.time.sleep") as sleep:
                response = self.put()
            self.assertEqual(response.status_code, 503)
            self.assertEqual(json.loads(response.content)["error"]["code"], "configuration_busy")
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.05, 0.1, 0.2])
        finally:
            locker.rollback()
            locker.close()
        self.tenant.refresh_from_db()
        self.model.refresh_from_db()
        self.assertEqual(self.tenant.model_thinking_config, {})
        self.assertNotIn("thinking", self.model.parameters)

    def test_retry_reloads_revision_outside_failed_transaction(self):
        locker = sqlite3.connect(connections["default"].settings_dict["NAME"])
        locker.execute("BEGIN IMMEDIATE")

        def release_and_update(delay):
            self.assertFalse(connections["default"].in_atomic_block)
            locker.rollback()
            self.assertEqual(self.put().status_code, 200)

        try:
            with patch.object(thinking_views, "auth_context", return_value=(self.user, self.tenant)), \
                 patch("models_config.thinking_views.time.sleep", side_effect=release_and_update) as sleep:
                response = self.put()
            self.assertEqual(response.status_code, 409)
            self.assertEqual(json.loads(response.content)["error"]["code"], "revision_conflict")
            sleep.assert_called_once_with(0.05)
        finally:
            locker.rollback()
            locker.close()
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.model_thinking_config["revision"], 1)

    def test_unrelated_database_error_is_raised_without_retry(self):
        with patch.object(thinking_views, "auth_context", return_value=(self.user, self.tenant)), \
             patch.object(ModelConfig, "save", side_effect=OperationalError("no such table: fixture")), \
             patch("models_config.thinking_views.time.sleep") as sleep:
            with self.assertRaisesRegex(OperationalError, "no such table"):
                self.put()
            sleep.assert_not_called()
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.model_thinking_config, {})

    @override_settings(APP_TASKS_SYNC=True)
    def test_sync_child_policy_and_context_do_not_change_parent_identity(self):
        child = SimpleNamespace(actor_id="fixture-child", agent_type="doc_retriever")
        parent = SimpleNamespace(session=SimpleNamespace(id="fixture-session"))
        captured = {}

        def execute(actor, context, timeout_ms):
            with patch.object(thinking_views, "auth_context", return_value=(self.user, self.tenant)):
                self.assertEqual(self.put().status_code, 200)
            captured["policy"] = thinking.resolve(self.tenant, model=self.model)
            observability.update_llm_call_context(model_id="fixture-child-model")
            captured["identity"] = observability.get_llm_call_context()

        token = observability.set_llm_call_context(session_id="fixture-session",
            request_id="fixture-request", actor_id="fixture-parent", agent_type="main")
        observability.update_llm_call_context(model_id="fixture-parent-model")
        try:
            with thinking.thinking_scope(), \
                 patch("personal_knowledge_base.agent_actor.ActorRegistry.create_subagent", return_value=child), \
                 patch.object(ActorRunner, "_execute_actor", side_effect=execute):
                original = thinking.resolve(self.tenant, model=self.model)
                ActorRunner.spawn_subagent(parent, child.agent_type, "fixture", {"session_id": "fixture-session"})
                self.assertEqual(captured["policy"], original)
                self.assertEqual(captured["identity"]["actor_id"], child.actor_id)
                self.assertEqual(observability.get_llm_call_context()["actor_id"], "fixture-parent")
                self.assertEqual(observability.get_llm_call_context()["model_id"], "fixture-parent-model")
        finally:
            observability.reset_llm_call_context(token)

    @override_settings(APP_TASKS_SYNC=False)
    def test_background_child_keeps_parent_policy_snapshot(self):
        started, release, done = threading.Event(), threading.Event(), threading.Event()
        captured = {}
        errors = []
        child = SimpleNamespace(actor_id="fixture-child", agent_type="doc_retriever")
        parent = SimpleNamespace(session=SimpleNamespace(id="fixture-session"))

        def execute(actor, context, timeout_ms):
            try:
                started.set()
                if not release.wait(timeout=5):
                    raise AssertionError("parent never released child")
                with thinking.thinking_scope():
                    captured["policy"] = thinking.resolve(self.tenant, model=self.model)
                    captured["span"] = observability._current_span.get()
                    captured["identity"] = observability.get_llm_call_context()
            except Exception as exc:
                errors.append(exc)
            finally:
                connections["default"].close()
                done.set()

        span = object()
        span_token = observability._current_span.set(span)
        call_token = observability.set_llm_call_context(session_id="fixture-session",
            request_id="fixture-request", actor_id="fixture-parent", agent_type="main")
        try:
            with thinking.thinking_scope(), \
                 patch("personal_knowledge_base.agent_actor.ActorRegistry.create_subagent", return_value=child), \
                 patch.object(ActorRunner, "_execute_actor", side_effect=execute):
                original = thinking.resolve(self.tenant, model=self.model)
                ActorRunner.spawn_subagent(parent, child.agent_type, "fixture",
                    {"tenant": self.tenant, "session_id": "fixture-session"})
                self.assertTrue(started.wait(timeout=5))
                with patch.object(thinking_views, "auth_context", return_value=(self.user, self.tenant)):
                    self.assertEqual(self.put().status_code, 200)
                release.set()
                self.assertTrue(done.wait(timeout=5))
                self.assertEqual(errors, [])
                self.assertEqual(captured["policy"], original)
                self.assertIsNone(captured["span"])
                self.assertEqual(captured["identity"]["actor_id"], child.actor_id)
                self.assertEqual(captured["identity"]["request_id"], "fixture-request")
                self.assertIs(observability._current_span.get(), span)
                self.assertEqual(observability.get_llm_call_context()["actor_id"], "fixture-parent")
            with thinking.thinking_scope():
                self.assertEqual(thinking.resolve(self.tenant, model=self.model).mode, "off")
        finally:
            release.set()
            done.wait(timeout=5)
            observability._current_span.reset(span_token)
            observability.reset_llm_call_context(call_token)
