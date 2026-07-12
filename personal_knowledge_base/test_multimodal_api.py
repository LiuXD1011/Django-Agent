import tempfile

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import Client, TestCase, override_settings

from personal_knowledge_base.models import Knowledge, KnowledgeBase, KnowledgeImage, ModelConfig, Tenant


class MultimodalApiTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.media_dir.cleanup)
        self.client = Client()
        response = self.client.post("/api/v1/auth/auto-setup", content_type="application/json")
        self.token = response.json()["data"]["token"]
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}
        self.tenant = Tenant.objects.first()
        self.kb = KnowledgeBase.objects.create(tenant=self.tenant, name="预览知识库")
        self.knowledge = Knowledge.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            type="file",
            title="预览文档",
            source="preview.png",
            file_name="preview.png",
        )

    def create_image(self):
        path = default_storage.save("tests/preview.png", ContentFile(b"image-content"))
        return KnowledgeImage.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.knowledge,
            content_hash="a" * 64,
            storage_path=path,
            mime_type="image/png",
            width=100,
            height=80,
            source_type="docx",
        )

    def test_image_preview_is_inline_and_tenant_scoped(self):
        image = self.create_image()

        response = self.client.get(f"/api/v1/knowledge/{self.knowledge.id}/images/{image.id}", **self.headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(b"".join(response.streaming_content), b"image-content")
        other = Tenant.objects.create(name="其他租户", api_key="other-preview")
        image.tenant = other
        image.save(update_fields=["tenant"])
        response = self.client.get(f"/api/v1/knowledge/{self.knowledge.id}/images/{image.id}", **self.headers)
        self.assertEqual(response.status_code, 404)

    def test_parser_engine_api_reports_real_capabilities(self):
        response = self.client.get("/api/v1/system/parser-engines", **self.headers)
        self.assertEqual(response.status_code, 200)
        engine = response.json()["data"]["items"][0]
        self.assertEqual(engine["name"], "builtin")
        self.assertIn("pptx", engine["formats"])
        self.assertIn("scanned_pdf", engine["capabilities"])
        self.assertIn("PyMuPDF", engine["dependencies"])
        self.assertIn("vlm_available", engine)

        response = self.client.post("/api/v1/system/parser-engines/check", data="{}", content_type="application/json", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn("dependencies", response.json()["data"])

    def test_parser_capabilities_reports_recent_vlm_access_denial(self):
        from personal_knowledge_base.model_providers import (
            ModelAccessDeniedError,
            clear_vlm_access_denied,
            mark_vlm_access_denied,
        )

        ModelConfig.objects.create(
            tenant=self.tenant,
            name="denied-vlm",
            type="VLLM",
            source="openai",
            is_default=True,
            parameters={
                "base_url": "https://example.test/v1",
                "api_key": "never-expose-this-api-key",
                "model": "vision-model",
            },
        )
        self.addCleanup(clear_vlm_access_denied, self.tenant)
        mark_vlm_access_denied(
            self.tenant,
            ModelAccessDeniedError(403, "AllocationQuota.FreeTierOnly", "free quota exhausted"),
        )

        response = self.client.get("/api/v1/system/parser-engines", **self.headers)

        self.assertEqual(response.status_code, 200)
        engine = response.json()["data"]["items"][0]
        self.assertFalse(engine["vlm_available"])
        self.assertEqual(engine["vlm_unavailable_reason"]["code"], "AllocationQuota.FreeTierOnly")
        self.assertNotIn("never-expose-this-api-key", response.content.decode())
