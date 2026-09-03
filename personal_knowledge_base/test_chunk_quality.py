import tempfile
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import SimpleTestCase, TestCase, override_settings

from personal_knowledge_base.chunking import ChunkingConfig
from personal_knowledge_base.chunking.service import split_document
from personal_knowledge_base.chunking.types import ChunkDraft, ChunkDiagnostics, ChunkingResult
from personal_knowledge_base.chunking.validator import minimum_chunk_size, validate_drafts
from personal_knowledge_base.document_parsing.types import ImageBlock, ParsedDocument, TextBlock
from personal_knowledge_base.document_processing import persist_chunking_result, relink_knowledge_chunks
from personal_knowledge_base.model_providers import ModelConfigurationError
from personal_knowledge_base.models import Chunk, Knowledge, KnowledgeBase, KnowledgeImage, Tenant
from personal_knowledge_base.multimodal import process_document_images


def mixed_heading_document():
    return ParsedDocument(
        text_blocks=[
            TextBlock("# Intro", 0, block_type="heading", metadata={"heading_level": 1}),
            TextBlock("Intro explains the topic with enough body text to pass the chunk floor.", 1, block_type="paragraph"),
            TextBlock("# Gap", 2, block_type="heading", metadata={"heading_level": 1}),
            TextBlock("# Next", 3, block_type="heading", metadata={"heading_level": 1}),
            TextBlock("Next section body with sufficient content length to exceed the floor.", 4, block_type="paragraph"),
        ]
    )


def _drafts_for(source: str, segments: list[str]) -> list[ChunkDraft]:
    drafts = []
    cursor = 0
    for segment in segments:
        drafts.append(ChunkDraft(content=segment, context_header="T", start_at=cursor, end_at=cursor + len(segment)))
        cursor += len(segment)
    return drafts


class CoalesceTinyDraftsTests(SimpleTestCase):
    def test_tiny_section_merges_into_following_section(self):
        result = split_document(mixed_heading_document(), ChunkingConfig(), title="Guide")

        self.assertEqual(result.diagnostics.selected_strategy, "heading")
        parent_contents = [parent.content for parent in result.parents]
        self.assertFalse(any(content.strip() == "# Gap" for content in parent_contents))
        merged = next(content for content in parent_contents if "Gap" in content)
        self.assertIn("# Next", merged)
        self.assertIn("Next section body", merged)

    def test_coalesce_keeps_source_coverage_valid(self):
        config = ChunkingConfig(enable_parent_child=False, chunk_size=512)
        parsed = mixed_heading_document()
        result = split_document(parsed, config, title="Guide")

        issues = validate_drafts(
            result.children,
            _canonical_source(parsed),
            target_size=config.chunk_size,
            token_counter=lambda value: (len(value) + 3) // 4,
        )
        self.assertEqual(issues, [])

    def test_split_children_never_reproduce_tiny_section_fragments(self):
        result = split_document(mixed_heading_document(), ChunkingConfig(), title="Guide")

        floor = minimum_chunk_size(ChunkingConfig().child_chunk_size)
        tiny = [child for child in result.children if len(child.content.strip()) < floor and len(result.children) > 1]
        self.assertEqual(tiny, [])


def _canonical_source(parsed: ParsedDocument) -> str:
    return "\n\n".join(block.text for block in parsed.text_blocks)


class ValidatorTinyThresholdTests(SimpleTestCase):
    def test_ratio_above_quarter_is_rejected(self):
        # 9 段中 4 个 tiny（44% > 25% 且 tiny > 2）→ 整层否决
        segments = ["tiny!!"] * 4 + [_canonical_source_value(10 + i) for i in range(5)]
        source = "".join(segments)
        drafts = _drafts_for(source, segments)

        issues = validate_drafts(drafts, source, target_size=512, token_counter=lambda value: (len(value) + 3) // 4)
        self.assertIn("excessive_tiny_chunks", issues)

    def test_two_tiny_chunks_among_many_are_accepted(self):
        # 9 段中只有 2 个 tiny：不满足 "tiny > 2"，不再触发阈值
        segments = [_canonical_source_value(0), _canonical_source_value(1)]
        segments += [_canonical_source_value(10 + i) for i in range(7)]
        source = "".join(segments)
        drafts = _drafts_for(source, segments)

        issues = validate_drafts(drafts, source, target_size=512, token_counter=lambda value: (len(value) + 3) // 4)
        self.assertNotIn("excessive_tiny_chunks", issues)


def _canonical_source_value(index: int) -> str:
    if index < 2:
        return "tiny!!"
    return f"segment {index} with plenty of body text to clear the sixty-four character floor threshold."


@override_settings(
    LLM_USE_ENV_CHAT=False,
    LLM_USE_ENV_SUMMARY=False,
    LLM_USE_ENV_QUESTION=False,
    LLM_USE_ENV_EXTRACT=False,
    LLM_USE_ENV_EMBEDDING=False,
)
class ChunkQualityInfrastructureTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.media_dir.cleanup)
        self.tenant = Tenant.objects.create(name="chunk-quality", api_key="chunk-quality-key")
        self.knowledge_base = KnowledgeBase.objects.create(tenant=self.tenant, name="chunk-quality-kb")
        content = b"body"
        path = default_storage.save("tests/chunk-quality.md", ContentFile(content))
        self.knowledge = Knowledge.objects.create(
            tenant=self.tenant,
            knowledge_base=self.knowledge_base,
            type="file",
            title="Chunk Quality Doc",
            source="chunk-quality.md",
            file_name="chunk-quality.md",
            file_type="md",
            file_path=path,
            file_size=len(content),
            storage_size=len(content),
        )

    def _image_block(self, index=0):
        return ImageBlock(b"img-bytes", "image/png", 10, 10, "pdf_embedded", f"page:{index}", index, index)

    @patch("personal_knowledge_base.multimodal.analyze_image")
    @patch("personal_knowledge_base.multimodal.resolve_vlm_model", return_value=("env", None))
    def test_total_image_failure_creates_no_placeholder_chunks(self, _resolve, analyze):
        analyze.return_value = ("", "", ["OCR: quota exhausted"], "OCR: quota exhausted")

        chunks, warnings = process_document_images(self.knowledge, [self._image_block()], [])

        self.assertEqual(chunks, [])
        self.assertTrue(warnings)
        image = KnowledgeImage.objects.get(knowledge=self.knowledge)
        self.assertEqual(image.status, "failed")
        self.assertIn("quota exhausted", image.error_message)
        self.assertFalse(Chunk.objects.filter(knowledge=self.knowledge).exists())

    @patch("personal_knowledge_base.multimodal.analyze_image")
    @patch("personal_knowledge_base.multimodal.resolve_vlm_model")
    def test_unavailable_vlm_short_circuits_before_any_request(self, resolve, analyze):
        resolve.side_effect = ModelConfigurationError("No VLM model configured")

        chunks, warnings = process_document_images(self.knowledge, [self._image_block(0), self._image_block(1)], [])

        self.assertEqual(chunks, [])
        analyze.assert_not_called()
        self.assertEqual(KnowledgeImage.objects.filter(knowledge=self.knowledge, status="failed").count(), 2)

    @patch("personal_knowledge_base.multimodal.analyze_image")
    @patch("personal_knowledge_base.multimodal.resolve_vlm_model", return_value=("env", None))
    def test_partial_success_keeps_container_with_ocr_child(self, _resolve, analyze):
        analyze.return_value = ("recognized text", "", [], "")

        chunks, _warnings = process_document_images(self.knowledge, [self._image_block()], [])

        types = sorted(chunk.chunk_type for chunk in chunks)
        self.assertEqual(types, ["image_container", "image_ocr"])
        container = next(chunk for chunk in chunks if chunk.chunk_type == "image_container")
        child = next(chunk for chunk in chunks if chunk.chunk_type == "image_ocr")
        self.assertFalse(container.is_enabled)
        self.assertEqual(child.media_parent_id, container.id)
        image = KnowledgeImage.objects.get(knowledge=self.knowledge)
        self.assertEqual(image.status, "partial")

    def test_persist_deduplicates_tiny_duplicate_children(self):
        result = ChunkingResult(
            parents=[],
            children=[
                ChunkDraft("dup", "T", 0, 3),
                ChunkDraft("body text long enough", "T", 10, 31),
                ChunkDraft("dup", "T", 40, 43),
            ],
            diagnostics=ChunkDiagnostics(requested_strategy="heading", selected_strategy="heading"),
        )

        chunks = persist_chunking_result(self.knowledge, result, tiny_floor=8)

        contents = [chunk.content for chunk in chunks if chunk.chunk_type == "text"]
        self.assertEqual(contents, ["dup", "body text long enough"])
        indexes = [chunk.chunk_index for chunk in chunks]
        self.assertEqual(indexes, list(range(len(indexes))))

    def test_relink_skips_disabled_and_media_chunks(self):
        container = Chunk.objects.create(
            tenant=self.tenant, knowledge_base=self.knowledge_base, knowledge=self.knowledge,
            content="[图片：page:1]", chunk_index=1, chunk_type="image_container", is_enabled=False,
        )
        first = Chunk.objects.create(
            tenant=self.tenant, knowledge_base=self.knowledge_base, knowledge=self.knowledge,
            content="first", chunk_index=0, chunk_type="text",
            next_chunk_id=container.id,
        )
        last = Chunk.objects.create(
            tenant=self.tenant, knowledge_base=self.knowledge_base, knowledge=self.knowledge,
            content="last", chunk_index=2, chunk_type="text",
            pre_chunk_id=container.id,
        )
        middle_disabled = Chunk.objects.create(
            tenant=self.tenant, knowledge_base=self.knowledge_base, knowledge=self.knowledge,
            content="disabled", chunk_index=3, chunk_type="text", is_enabled=False,
        )

        fixed = relink_knowledge_chunks(self.knowledge)

        first.refresh_from_db()
        last.refresh_from_db()
        container.refresh_from_db()
        self.assertGreaterEqual(fixed, 2)
        self.assertEqual(first.next_chunk_id, last.id)
        self.assertEqual(last.pre_chunk_id, first.id)
        self.assertNotEqual(container.next_chunk_id, first.id or last.id)
        self.assertEqual(middle_disabled.next_chunk_id, "")
