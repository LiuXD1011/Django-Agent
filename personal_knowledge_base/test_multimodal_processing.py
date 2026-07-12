import io
import random
import tempfile
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from PIL import Image

from personal_knowledge_base.document_parsing.types import ImageBlock, ParsedDocument, TextBlock
from personal_knowledge_base.document_processing import create_text_chunks, process_knowledge, split_text
from personal_knowledge_base.multimodal import process_document_images
from personal_knowledge_base.model_providers import vision_completion
from personal_knowledge_base.models import Chunk, Knowledge, KnowledgeBase, KnowledgeImage, ModelConfig, Tenant


def noisy_png(size=(96, 96)):
    image = Image.frombytes("RGB", size, random.Random(7).randbytes(size[0] * size[1] * 3))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@override_settings(
    LLM_USE_ENV_CHAT=False,
    LLM_USE_ENV_SUMMARY=False,
    LLM_USE_ENV_QUESTION=False,
    LLM_USE_ENV_EXTRACT=False,
    LLM_USE_ENV_EMBEDDING=False,
    LLM_USE_ENV_VLM=False,
)
class MultimodalProcessingTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.media_dir.cleanup)
        self.tenant = Tenant.objects.create(name="图片租户", api_key="image-tenant")
        self.kb = KnowledgeBase.objects.create(tenant=self.tenant, name="图片知识库")

    def create_file_knowledge(self, name, data):
        path = default_storage.save(f"tests/{name}", ContentFile(data))
        return Knowledge.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            type="file",
            title=name,
            source=name,
            file_name=name,
            file_type=name.rsplit(".", 1)[-1],
            file_path=path,
            file_size=len(data),
            storage_size=len(data),
        )

    def test_standalone_image_creates_asset_ocr_caption_and_container(self):
        knowledge = self.create_file_knowledge("diagram.png", noisy_png())

        with patch(
            "personal_knowledge_base.multimodal.vision_completion",
            side_effect=["表格中的金额为 100 元", "一张展示季度收入趋势的柱状图"],
        ) as vision:
            process_knowledge(knowledge.id)

        image = KnowledgeImage.objects.get(knowledge=knowledge)
        self.assertEqual(image.status, "completed")
        self.assertFalse(image.storage_owned)
        self.assertEqual(vision.call_count, 2)
        chunks = list(Chunk.objects.filter(knowledge=knowledge).order_by("chunk_index"))
        self.assertEqual([chunk.chunk_type for chunk in chunks], ["image_container", "image_ocr", "image_caption"])
        self.assertFalse(chunks[0].is_enabled)
        self.assertEqual(chunks[1].parent_chunk_id, chunks[0].id)
        self.assertEqual(chunks[2].parent_chunk_id, chunks[0].id)
        self.assertEqual(chunks[1].image_info["image_id"], image.id)

    def test_pdf_layout_blocks_are_merged_before_chunking(self):
        knowledge = Knowledge.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            type="file",
            title="chart.pdf",
            source="chart.pdf",
            file_name="chart.pdf",
            file_type="pdf",
        )
        parsed = ParsedDocument(
            text_blocks=[
                TextBlock("250", 0, page_index=0),
                TextBlock("200", 1, page_index=0),
                TextBlock("150", 2, page_index=0),
                TextBlock("intensity", 3, page_index=0),
                TextBlock("100", 4, page_index=0),
                TextBlock("The chart compares acceleration methods and reports stable reconstruction quality.", 5, page_index=0),
            ]
        )

        chunks = create_text_chunks(knowledge, parsed)

        self.assertEqual(len(chunks), 1)
        self.assertIn("150\nintensity\n100", chunks[0].content)
        self.assertNotIn(chunks[0].content, {"250", "200", "150", "intensity", "100"})
        self.assertEqual(chunks[0].metadata["source_block_start"], 0)
        self.assertEqual(chunks[0].metadata["source_block_end"], 5)

    def test_split_text_does_not_emit_overlap_only_short_tail(self):
        text = "A" * 520

        pieces = split_text(text, {"chunk_size": 512, "chunk_overlap": 50})

        self.assertEqual(len(pieces), 1)
        self.assertEqual(pieces[0], (0, 520, text))

    def test_short_pdf_labels_after_an_image_join_the_previous_chunk(self):
        knowledge = Knowledge.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            type="file",
            title="chart-with-image.pdf",
            source="chart-with-image.pdf",
            file_name="chart-with-image.pdf",
            file_type="pdf",
        )
        parsed = ParsedDocument(
            text_blocks=[
                TextBlock("A detailed paragraph explaining the chart. " * 5, 0, page_index=0),
                TextBlock("150", 2, page_index=0),
                TextBlock("intensity", 3, page_index=0),
                TextBlock("100", 4, page_index=0),
            ],
            images=[ImageBlock(b"image", "image/png", 100, 100, "pdf_embedded", "page:1", 1, page_index=0)],
        )

        chunks = create_text_chunks(knowledge, parsed)

        self.assertEqual(len(chunks), 1)
        self.assertIn("150\nintensity\n100", chunks[0].content)

    def test_short_pdf_labels_preserve_offsets_on_a_later_chunk(self):
        knowledge = Knowledge.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            type="file",
            title="long-chart-with-image.pdf",
            source="long-chart-with-image.pdf",
            file_name="long-chart-with-image.pdf",
            file_type="pdf",
        )
        parsed = ParsedDocument(
            text_blocks=[
                TextBlock("A" * 500, 0, page_index=0),
                TextBlock("150", 2, page_index=0),
                TextBlock("intensity", 3, page_index=0),
                TextBlock("100", 4, page_index=0),
            ],
            images=[ImageBlock(b"image", "image/png", 100, 100, "pdf_embedded", "page:1", 1, page_index=0)],
        )

        chunks = create_text_chunks(
            knowledge,
            parsed,
            {"chunking_config": {"chunk_size": 128, "chunk_overlap": 20}},
        )

        last_chunk = chunks[-1]
        self.assertGreater(last_chunk.start_at, 0)
        self.assertTrue(last_chunk.content.endswith("150\nintensity\n100"))
        self.assertGreater(last_chunk.end_at, last_chunk.start_at)
        self.assertEqual(last_chunk.end_at, last_chunk.start_at + len(last_chunk.content))

    def test_markdown_image_chunks_attach_to_preceding_text_chunk(self):
        import base64

        data_uri = base64.b64encode(noisy_png()).decode()
        content = f"正文介绍\n\n![图](data:image/png;base64,{data_uri})\n\n结论"
        knowledge = self.create_file_knowledge("guide.md", content.encode())

        with patch(
            "personal_knowledge_base.multimodal.vision_completion",
            side_effect=["图中文字", "图形描述"],
        ):
            process_knowledge(knowledge.id)

        text_chunks = list(Chunk.objects.filter(knowledge=knowledge, chunk_type="text").order_by("chunk_index"))
        image_chunks = list(Chunk.objects.filter(knowledge=knowledge, chunk_type__in=["image_ocr", "image_caption"]))
        self.assertEqual(len(text_chunks), 2)
        self.assertEqual({chunk.parent_chunk_id for chunk in image_chunks}, {text_chunks[0].id})

    def test_standalone_image_fails_when_both_vlm_calls_fail(self):
        knowledge = self.create_file_knowledge("unreadable.png", noisy_png())

        with patch("personal_knowledge_base.multimodal.vision_completion", side_effect=RuntimeError("VLM unavailable")):
            with self.assertRaises(ValueError):
                process_knowledge(knowledge.id)

        knowledge.refresh_from_db()
        self.assertEqual(knowledge.parse_status, "failed")
        self.assertEqual(KnowledgeImage.objects.get(knowledge=knowledge).status, "failed")

    def test_vlm_403_stops_remaining_image_calls(self):
        from personal_knowledge_base.model_providers import ModelAccessDeniedError

        knowledge = self.create_file_knowledge("denied.pdf", b"pdf")
        image_blocks = [
            ImageBlock(noisy_png((96, 96)), "image/png", 96, 96, "pdf_embedded", "page:1", 0, page_index=0),
            ImageBlock(noisy_png((97, 96)), "image/png", 97, 96, "pdf_embedded", "page:2", 1, page_index=1),
        ]

        with patch(
            "personal_knowledge_base.multimodal.vision_completion",
            side_effect=ModelAccessDeniedError(403, "AllocationQuota.FreeTierOnly", "free quota exhausted"),
        ) as vision:
            process_document_images(knowledge, image_blocks, [])

        self.assertEqual(vision.call_count, 1)
        images = list(KnowledgeImage.objects.filter(knowledge=knowledge).order_by("block_index"))
        self.assertEqual([image.status for image in images], ["failed", "failed"])
        self.assertTrue(all("AllocationQuota.FreeTierOnly" in image.error_message for image in images))

    def test_vlm_circuit_resets_for_next_document(self):
        from personal_knowledge_base.model_providers import ModelAccessDeniedError

        failed_knowledge = self.create_file_knowledge("denied-first.pdf", b"first")
        next_knowledge = self.create_file_knowledge("allowed-next.pdf", b"next")
        first_image = ImageBlock(noisy_png((96, 96)), "image/png", 96, 96, "pdf_embedded", "page:1", 0, page_index=0)
        next_image = ImageBlock(noisy_png((97, 96)), "image/png", 97, 96, "pdf_embedded", "page:1", 0, page_index=0)

        with patch("personal_knowledge_base.multimodal.vision_completion") as vision:
            vision.side_effect = ModelAccessDeniedError(
                403, "AllocationQuota.FreeTierOnly", "free quota exhausted"
            )
            process_document_images(failed_knowledge, [first_image], [])
            self.assertEqual(vision.call_count, 1)

            vision.reset_mock()
            vision.side_effect = ["OCR", "Caption"]
            process_document_images(next_knowledge, [next_image], [])

        self.assertEqual(vision.call_count, 2)
        image = KnowledgeImage.objects.get(knowledge=next_knowledge)
        self.assertEqual((image.status, image.ocr_text, image.caption), ("completed", "OCR", "Caption"))

    def test_vlm_circuit_marks_cached_duplicates_after_denial(self):
        from personal_knowledge_base.model_providers import ModelAccessDeniedError

        knowledge = self.create_file_knowledge("duplicate-after-denial.pdf", b"pdf")
        first_data = noisy_png((96, 96))
        blocks = [
            ImageBlock(first_data, "image/png", 96, 96, "pdf_embedded", "page:1", 0, page_index=0),
            ImageBlock(noisy_png((97, 96)), "image/png", 97, 96, "pdf_embedded", "page:2", 1, page_index=1),
            ImageBlock(first_data, "image/png", 96, 96, "pdf_embedded", "page:3", 2, page_index=2),
        ]

        with patch(
            "personal_knowledge_base.multimodal.vision_completion",
            side_effect=[
                "OCR",
                "Caption",
                ModelAccessDeniedError(403, "AllocationQuota.FreeTierOnly", "free quota exhausted"),
            ],
        ) as vision:
            process_document_images(knowledge, blocks, [])

        self.assertEqual(vision.call_count, 3)
        images = list(KnowledgeImage.objects.filter(knowledge=knowledge).order_by("block_index"))
        self.assertEqual([image.status for image in images], ["completed", "failed", "failed"])
        self.assertIn("AllocationQuota.FreeTierOnly", images[2].error_message)

    def test_image_container_is_not_sent_to_indexer(self):
        knowledge = self.create_file_knowledge("indexed.png", noisy_png())

        with (
            patch("personal_knowledge_base.multimodal.vision_completion", side_effect=["OCR", "Caption"]),
            patch("personal_knowledge_base.document_processing.index_chunk") as indexer,
        ):
            process_knowledge(knowledge.id)

        indexed_types = [call.args[0].chunk_type for call in indexer.call_args_list]
        self.assertEqual(indexed_types, ["image_ocr", "image_caption"])

    def test_vision_completion_uses_tenant_default_vlm_when_env_is_disabled(self):
        ModelConfig.objects.create(
            id="tenant-vlm",
            tenant=self.tenant,
            name="vision-model",
            type="VLLM",
            source="openai",
            is_default=True,
            parameters={"base_url": "https://example.test/v1", "api_key": "secret", "model": "vision-model"},
        )
        response = {"choices": [{"message": {"content": "图片结果"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}

        with patch("personal_knowledge_base.model_providers.openai_compatible_chat_raw", return_value=response) as request:
            result = vision_completion(self.tenant, "data:image/jpeg;base64,AA==", "识别", "image_ocr")

        self.assertEqual(result, "图片结果")
        self.assertEqual(request.call_args.args[:3], ("https://example.test/v1", "secret", "vision-model"))

    def test_model_access_denial_handles_string_error_payload(self):
        from personal_knowledge_base.model_providers import ModelAccessDeniedError, _raise_for_model_status

        response = type(
            "Response",
            (),
            {"status_code": 403, "json": lambda self: {"error": "Unauthorized"}},
        )()

        with self.assertRaises(ModelAccessDeniedError) as raised:
            _raise_for_model_status(response)

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.upstream_code, "model_access_denied")
        self.assertEqual(raised.exception.safe_message, "Unauthorized")
