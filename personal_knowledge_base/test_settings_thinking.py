"""Feature contracts: policy persistence, role isolation, transport and local auth."""
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase, SimpleTestCase, RequestFactory, override_settings
from . import thinking
from .models import Tenant, User, TenantMember, ModelConfig
from .llm_providers import ProviderConfig, BaseLLMProvider
from .langfuse_access import langfuse_access, configuration
from models_config.thinking_views import thinking_settings

BASE = "https://api.deepseek.com"
MODEL = "deepseek-v4-flash"
CAP = thinking.capability(BASE, MODEL)


class ThinkingUnitTests(SimpleTestCase):
    def test_known_endpoint_and_exact_model(self):
        self.assertEqual(CAP["efforts"], ["low", "high", "max"])
        for base, model in [("https://evil.example", MODEL), (BASE, "unknown"), (BASE + ".evil", MODEL)]:
            self.assertEqual(thinking.capability(base, model)["modes"], ["default"])

    def test_validation(self):
        for value in [{"mode": "off", "effort": "max"}, {"mode": "on", "effort": "ultra"},
                      {"mode": "on", "extra": 1}, None, "high"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                thinking.normalize(value, CAP)

    def test_default_off_and_internal_override(self):
        self.assertEqual(thinking.wire_options(BASE, MODEL)[0], {})
        chosen = thinking.Thinking("on", "max", "tenant_env", 2, CAP["profile"])
        body, meta = thinking.wire_options(BASE, MODEL, chosen, False)
        self.assertEqual(body, {"thinking": {"type": "disabled"}})
        self.assertEqual(meta["think_policy_source"], "internal")
        self.assertEqual(thinking.wire_options(BASE, MODEL, chosen)[0]["reasoning_effort"], "max")

    def test_raw_wrapper_forwards_thinking(self):
        from . import model_providers as mp
        chosen = thinking.Thinking("on", "max")
        with patch.object(mp._provider_factory, "create") as factory:
            factory.return_value.chat.return_value = {"choices": []}
            mp.openai_compatible_chat_raw(BASE, "fixture", MODEL, [], thinking=chosen)
            self.assertIs(factory.return_value.chat.call_args.kwargs["thinking"], chosen)

    def test_unknown_fallback_rejects_requested_effort(self):
        with self.assertRaises(ValueError):
            thinking.adapt(thinking.Thinking("on", "max"), "https://unknown.example", "other")

    def test_generator_scope_does_not_leak(self):
        @thinking.scoped
        def generator():
            self.assertIsNotNone(thinking._snapshot.get())
            yield 1
        stream = generator()
        self.assertEqual(next(stream), 1)
        self.assertIsNone(thinking._snapshot.get())
        stream.close()
        self.assertIsNone(thinking._snapshot.get())

    def test_real_litellm_wire_nonstream_and_stream(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append(body)
                self.send_response(200)
                if body.get("stream"):
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    payload = {"id": "capture", "object": "chat.completion.chunk", "model": MODEL,
                               "choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": None}]}
                    self.wfile.write(("data: " + json.dumps(payload) + "\n\ndata: [DONE]\n\n").encode())
                else:
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"id": "capture", "model": MODEL,
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}).encode())
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            provider = BaseLLMProvider(ProviderConfig(base_url=f"http://127.0.0.1:{server.server_port}/v1",
                api_key="fixture-only", model_name=MODEL, num_retries=0))
            # Substitute ONLY capability lookup for the local capture endpoint.
            with patch("personal_knowledge_base.thinking.capability", return_value=CAP):
                for stream in [False, True]:
                    for mode, effort in [("default", None), ("off", None), ("on", "low"), ("on", "high"), ("on", "max")]:
                        chosen = thinking.Thinking(mode, effort)
                        call = provider.chat_stream if stream else provider.chat
                        result = call([{"role": "user", "content": "fixture"}], thinking=chosen)
                        if stream:
                            list(result)
                        payload = received[-1]
                        if mode == "default":
                            self.assertNotIn("thinking", payload)
                            self.assertNotIn("reasoning_effort", payload)
                        else:
                            self.assertEqual(payload["thinking"]["type"], "enabled" if mode == "on" else "disabled")
                            if effort:
                                self.assertEqual(payload["reasoning_effort"], effort)
                        self.assertNotIn("extra_body", payload)
            self.assertEqual(len(received), 10)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)


@override_settings(LLM_CHAT_BASE_URL=BASE, LLM_CHAT_MODEL=MODEL, LLM_CHAT_API_KEY="fixture",
                   LLM_USE_ENV_CHAT=True, LLM_SUMMARY_MODEL=MODEL, LLM_USE_ENV_SUMMARY=True,
                   LANGFUSE_ENABLED=False)
class ThinkingPersistenceTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="thinking", api_key="thinking-fixture")
        self.other = Tenant.objects.create(name="other", api_key="other-fixture")
        self.user = User.objects.create(username="thinking-owner", email="thinking@fixture.invalid", tenant=self.tenant)
        TenantMember.objects.create(user=self.user, tenant=self.tenant, role="owner")
        self.factory = RequestFactory()
        from .model_providers import env_models
        self.model_id = next(m["id"] for m in env_models(self.tenant) if m["type"] == "KnowledgeQA")

    def invoke(self, body=None, user=True, model_id=None):
        path = "/api/v1/models/x/thinking"
        request = self.factory.get(path) if body is None else self.factory.put(path, json.dumps(body), content_type="application/json")
        with patch("models_config.thinking_views.auth_context", return_value=(self.user if user else None, self.tenant)):
            response = thinking_settings(request, model_id or self.model_id)
        return response, json.loads(response.content)

    def save(self, role="chat", revision=0):
        return self.invoke({"role": role, "revision": revision, "policy": {"mode": "on", "effort": "max"}})

    def test_env_save_role_isolation_and_no_model_row(self):
        self.assertEqual(self.save()[0].status_code, 200)
        self.assertEqual(ModelConfig.objects.count(), 0)
        self.assertEqual(thinking.resolve(self.tenant, role="chat").effort, "max")
        self.assertEqual(thinking.resolve(self.tenant, role="summary").mode, "default")
        self.assertEqual(thinking.resolve(self.other, role="chat").mode, "default")

    def test_revision_conflict(self):
        self.save()
        self.assertEqual(self.save()[0].status_code, 409)

    def test_api_key_and_member_cannot_write(self):
        body = {"role": "chat", "revision": 0, "policy": {"mode": "off", "effort": None}}
        self.assertEqual(self.invoke(body, user=False)[0].status_code, 403)
        TenantMember.objects.filter(user=self.user).update(role="viewer")
        self.assertEqual(self.invoke(body)[0].status_code, 403)

    def test_snapshot_and_next_turn(self):
        with thinking.thinking_scope():
            self.assertEqual(thinking.resolve(self.tenant).mode, "default")
            self.save()
            self.assertEqual(thinking.resolve(self.tenant).mode, "default")
        self.assertEqual(thinking.resolve(self.tenant).effort, "max")

    def test_stale_endpoint(self):
        self.save()
        with override_settings(LLM_CHAT_BASE_URL="https://other.example"):
            self.assertEqual(thinking.resolve(self.tenant).source, "stale")

    def test_db_policy_and_cross_tenant_404(self):
        model = ModelConfig.objects.create(id="db-thinking", tenant=self.tenant, name=MODEL,
            type="KnowledgeQA", source="misleading-provider", parameters={"base_url": BASE, "model": MODEL})
        body = {"role": "model", "revision": 0, "policy": {"mode": "off", "effort": None}}
        self.assertEqual(self.invoke(body, model_id=model.id)[0].status_code, 200)
        self.assertEqual(thinking.resolve(self.tenant, model=model).mode, "off")
        model.tenant = self.other
        model.save()
        self.assertEqual(self.invoke(model_id=model.id)[0].status_code, 404)

    def test_env_nonstream_agent_stream_and_auxiliary_options(self):
        self.save()
        from . import model_providers as mp
        result = {"choices": [{"message": {"content": "ok", "reasoning_content": ""}}], "usage": {"total_tokens": 2}}
        with patch.object(mp, "openai_compatible_chat_raw", return_value=result) as raw:
            self.assertEqual(mp.chat_completion(self.tenant, [{"role": "user", "content": "hi"}]), "ok")
            self.assertEqual(raw.call_args.kwargs["thinking"].effort, "max")
            mp.chat_completion_raw(self.tenant, [{"role": "user", "content": "hi"}])
            self.assertEqual(raw.call_args.kwargs["thinking"].effort, "max")
            mp.role_completion("summary", "fixture", tenant=self.tenant)
            self.assertNotIn("thinking", raw.call_args.kwargs)
            mp.chat_completion(self.tenant, [], enable_thinking=False)
            self.assertEqual(raw.call_args.kwargs["thinking"].mode, "off")
        with patch.object(mp, "openai_compatible_chat_stream", return_value=iter([{"choices": [{"delta": {"content": "ok"}}]}])) as stream:
            self.assertEqual(list(mp.chat_completion_stream(self.tenant, [])), ["ok"])
            self.assertEqual(stream.call_args.kwargs["thinking"].effort, "max")

    def test_typed_field_cannot_be_overwritten_via_legacy_kv(self):
        from accounts.views import tenant_kv
        request = self.factory.put("/unused", '{"roles": {}}', content_type="application/json")
        with patch("accounts.views.auth_context", return_value=(self.user, self.tenant)):
            response = tenant_kv(request, "model-thinking")
        self.assertEqual(response.status_code, 400)


class LangfuseAccessTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.admin = SimpleNamespace(id="fixture-admin", is_active=True, is_system_admin=True)
        self.cfg = {"base": "http://127.0.0.1:3000", "project": "fixture-project",
                    "email": "fixture@example.invalid", "password": "fixture-password", "auto": True}

    def request(self, action="session", **headers):
        return self.factory.post("/", {}, content_type="application/json",
            HTTP_HOST="127.0.0.1:8000", HTTP_ORIGIN=headers.pop("origin", "http://127.0.0.1:8000"), **headers)

    def invoke(self, request, user=True, action="session", cfg=None):
        with patch("personal_knowledge_base.langfuse_access.configuration", return_value=cfg or self.cfg), \
             patch("personal_knowledge_base.langfuse_access.auth_context", return_value=(self.admin if user else None, None)):
            return langfuse_access(request, action)

    def test_denies_api_key_and_regular_user(self):
        self.assertEqual(self.invoke(self.request(), user=False).status_code, 403)
        self.admin.is_system_admin = False
        self.assertEqual(self.invoke(self.request()).status_code, 403)

    def test_explicit_local_user_binding_without_admin_promotion(self):
        self.admin.is_system_admin = False
        cfg = {**self.cfg, "local_user_id": self.admin.id}
        with patch("personal_knowledge_base.langfuse_access.httpx.Client") as factory:
            factory.return_value.__enter__.return_value.get.return_value.status_code = 200
            request = self.factory.get("/", HTTP_HOST="127.0.0.1:8000")
            self.assertEqual(self.invoke(request, cfg=cfg, action="status").status_code, 200)
            self.assertEqual(self.invoke(request, cfg={**cfg, "local_user_id": "other"}, action="status").status_code, 403)
            self.admin.is_active = False
            self.assertEqual(self.invoke(request, cfg=cfg, action="status").status_code, 403)

    def test_origin_remote_and_mismatched_host_denied(self):
        self.assertEqual(self.invoke(self.request(origin="https://other.example")).status_code, 403)
        self.assertEqual(self.invoke(self.request(REMOTE_ADDR="192.0.2.1")).status_code, 400)
        self.assertEqual(self.invoke(self.request(), cfg={**self.cfg, "base": "http://localhost:3000"}).status_code, 400)

    def test_login_only_transfers_allowlisted_httponly_cookie(self):
        session = {"user": {"email": self.cfg["email"], "organizations": [{"projects": [{"id": self.cfg["project"]}]}]}}
        client = MagicMock()
        client.get.side_effect = [SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"csrfToken": "fixture-csrf"}),
                                  SimpleNamespace(json=lambda: session)]
        client.cookies.jar = [SimpleNamespace(name="next-auth.session-token", value="fixture-session"),
                              SimpleNamespace(name="next-auth.csrf-token", value="not-transferred")]
        with patch("personal_knowledge_base.langfuse_access.httpx.Client") as factory:
            factory.return_value.__enter__.return_value = client
            response = self.invoke(self.request())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.cookies), ["next-auth.session-token"])
        self.assertTrue(response.cookies["next-auth.session-token"]["httponly"])
        self.assertNotIn(b"fixture-password", response.content)
        self.assertNotIn(b"fixture-session", response.content)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_clear_only_langfuse_session(self):
        request = self.request()
        request.COOKIES = {"next-auth.session-token.0": "a", "app-cookie": "b"}
        response = self.invoke(request, user=False, action="clear")
        self.assertEqual(list(response.cookies), ["next-auth.session-token.0"])
        self.assertEqual(response.cookies["next-auth.session-token.0"]["max-age"], 0)

    def test_other_browser_account_is_not_overwritten(self):
        client = MagicMock()
        client.get.return_value.json.return_value = {"user": {"email": "other@example.invalid"}}
        request = self.request()
        request.COOKIES = {"next-auth.session-token": "fixture"}
        with patch("personal_knowledge_base.langfuse_access.httpx.Client") as factory:
            factory.return_value.__enter__.return_value = client
            response = self.invoke(request)
        self.assertEqual(response.status_code, 409)
        client.post.assert_not_called()

    def test_real_local_credentials_contract_when_explicitly_enabled(self):
        if os.getenv("TEST_LOCAL_LANGFUSE") != "true":
            self.skipTest("opt-in real local Langfuse session contract")
        response = self.invoke(self.request(), cfg=configuration())
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.cookies)
        self.assertTrue(all(c["httponly"] for c in response.cookies.values()))


class LocalStartupTests(SimpleTestCase):
    def test_disabled_never_calls_docker(self):
        from scripts.local_services import ensure_langfuse
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {"LANGFUSE_AUTOSTART": "false"}), \
             patch("scripts.local_services.subprocess.run") as run:
            self.assertEqual(ensure_langfuse(directory)["state"], "disabled")
            run.assert_not_called()

    def test_missing_config_is_nonfatal(self):
        from scripts.local_services import ensure_langfuse
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LANGFUSE_AUTOSTART": "true"}):
            self.assertEqual(ensure_langfuse(directory)["state"], "missing_server_configuration")

    def test_existing_stack_is_started_and_health_checked(self):
        from scripts.local_services import ensure_langfuse
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {"LANGFUSE_AUTOSTART": "true"}), \
             patch("scripts.local_services.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run, \
             patch("scripts.local_services.build_opener") as opener:
            Path(directory, ".env.langfuse").touch()
            opener.return_value.open.return_value.__enter__.return_value.status = 200
            self.assertEqual(ensure_langfuse(directory)["state"], "healthy")
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.args[0][-2:], ["up", "-d"])
            self.assertGreater(run.call_args.kwargs["timeout"], 0)
