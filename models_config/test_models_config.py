"""models_config 测试：模型 test 端点校验、凭证脱敏、Embedding 变更触发重建。"""

import json
from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from personal_knowledge_base.models import Tenant


@override_settings(ALLOW_AUTO_SETUP=True)
class ModelTestEndpointTests(TestCase):
    def setUp(self):
        self.client = Client()
        resp = self.client.post("/api/v1/auth/auto-setup", content_type="application/json")
        self.assertEqual(resp.status_code, 201)
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {resp.json()['data']['token']}"}

    def test_unsupported_type_returns_400(self):
        with patch("models_config.views.testable_model_config", return_value=("KnowledgeQA", None)):
            resp = self.client.post("/api/v1/models/any/test", content_type="application/json", **self.headers)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "unsupported_model_type")

    def test_model_not_found_returns_404(self):
        with patch("models_config.views.testable_model_config", return_value=None):
            resp = self.client.post("/api/v1/models/any/test", content_type="application/json", **self.headers)
        self.assertEqual(resp.status_code, 404)

    def test_embedding_success_redacts_credentials(self):
        cfg_with_secret = {"model": "bge-m3", "base_url": "https://x", "api_key": "super-secret"}
        with patch("models_config.views.testable_model_config", return_value=("Embedding", cfg_with_secret)), patch(
            "models_config.views.test_embedding_config",
            return_value={"ok": True, "model": "bge-m3", "dimension": 1024, "latency_ms": 12},
        ):
            resp = self.client.post("/api/v1/models/emb-1/test", content_type="application/json", **self.headers)
        self.assertEqual(resp.status_code, 200)
        body = json.dumps(resp.json()["data"])
        self.assertNotIn("super-secret", body)
        self.assertNotIn("parameters", body)
        self.assertNotIn("api_key", body)

    def test_failed_validation_returns_model_test_failed(self):
        from personal_knowledge_base.model_providers import ModelConfigurationError

        with patch("models_config.views.testable_model_config", return_value=("Embedding", {"model": "bge-m3"})), patch(
            "models_config.views.test_embedding_config",
            side_effect=ModelConfigurationError("boom"),
        ):
            resp = self.client.post("/api/v1/models/emb-1/test", content_type="application/json", **self.headers)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "model_test_failed")


@override_settings(ALLOW_AUTO_SETUP=True)
class EmbeddingChangeNotifyTests(TestCase):
    def setUp(self):
        self.client = Client()
        resp = self.client.post("/api/v1/auth/auto-setup", content_type="application/json")
        self.assertEqual(resp.status_code, 201)
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {resp.json()['data']['token']}"}

    def test_notify_on_embedding_create(self):
        with patch("models_config.views.notify_embedding_config_changed") as notify:
            resp = self.client.post(
                "/api/v1/models",
                data=json.dumps({"type": "embedding", "name": "emb"}),
                content_type="application/json", **self.headers,
            )
        self.assertEqual(resp.status_code, 201)
        notify.assert_called_once()

    def test_no_notify_for_non_embedding_create(self):
        with patch("models_config.views.notify_embedding_config_changed") as notify:
            resp = self.client.post(
                "/api/v1/models",
                data=json.dumps({"type": "chat", "name": "chat-model"}),
                content_type="application/json", **self.headers,
            )
        self.assertEqual(resp.status_code, 201)
        notify.assert_not_called()


@override_settings(ALLOW_AUTO_SETUP=True)
class FallbackPriorityTests(TestCase):
    """AC #15: 模型创建/更新接口接受 fallback_priority 参数。"""

    def setUp(self):
        self.client = Client()
        resp = self.client.post("/api/v1/auth/auto-setup", content_type="application/json")
        self.assertEqual(resp.status_code, 201)
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {resp.json()['data']['token']}"}

    def test_create_model_with_fallback_priority(self):
        resp = self.client.post(
            "/api/v1/models",
            data=json.dumps({"type": "chat", "name": "primary", "source": "openai", "fallback_priority": 10}),
            content_type="application/json", **self.headers,
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["data"]["fallback_priority"], 10)

    def test_update_model_fallback_priority(self):
        create = self.client.post(
            "/api/v1/models",
            data=json.dumps({"type": "chat", "name": "backup"}),
            content_type="application/json", **self.headers,
        )
        model_id = create.json()["data"]["id"]
        self.assertEqual(create.json()["data"]["fallback_priority"], 0)

        resp = self.client.put(
            f"/api/v1/models/{model_id}",
            data=json.dumps({"fallback_priority": 5}),
            content_type="application/json", **self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["fallback_priority"], 5)

    def test_provider_types_contains_five_vendors(self):
        resp = self.client.get("/api/v1/models/providers", content_type="application/json", **self.headers)
        names = [p["name"] for p in resp.json()["data"]["providers"]]
        for expected in ("openai", "deepseek", "aliyun-bailian", "qwen", "zhipu"):
            self.assertIn(expected, names)
