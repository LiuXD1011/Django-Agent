import tempfile
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import connection
from django.test import TestCase, override_settings
from django.conf import settings

from personal_knowledge_base.chunking.types import ChunkDiagnostics, ChunkDraft, ChunkingResult
from personal_knowledge_base.document_parsing.types import ParsedDocument, TextBlock
from personal_knowledge_base.document_processing import persist_chunking_result, process_knowledge
from personal_knowledge_base.models import Chunk, Knowledge, KnowledgeBase, KnowledgeImage, Tenant
from personal_knowledge_base.search import ensure_search_tables, index_chunk, pack_embedding, rebuild_vector_index


@override_settings(
    LLM_USE_ENV_CHAT=False,
    LLM_USE_ENV_SUMMARY=False,
    LLM_USE_ENV_QUESTION=False,
    LLM_USE_ENV_EXTRACT=False,
    LLM_USE_ENV_EMBEDDING=False,
)
class ParentChildProcessingTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.media_dir.cleanup)
        self.tenant = Tenant.objects.create(name="parent-child", api_key="parent-child-key")
        self.knowledge_base = KnowledgeBase.objects.create(tenant=self.tenant, name="parent-child-kb")
        content = ("# Install\n\n" + "Configure the service and verify the result. " * 30).encode()
        path = default_storage.save("tests/parent-child.md", ContentFile(content))
        self.knowledge = Knowledge.objects.create(
            tenant=self.tenant,
            knowledge_base=self.knowledge_base,
            type="file",
            title="Installation Guide",
            source="parent-child.md",
            file_name="parent-child.md",
            file_type="md",
            file_path=path,
            file_size=len(content),
            storage_size=len(content),
        )

    @patch("personal_knowledge_base.document_processing.index_chunk")
    def test_only_children_are_indexed(self, index_chunk):
        process_knowledge(self.knowledge.id)

        parents = Chunk.objects.filter(knowledge=self.knowledge, chunk_type="parent_text")
        children = Chunk.objects.filter(knowledge=self.knowledge, chunk_type="text")
        self.assertTrue(parents.exists())
        self.assertTrue(children.filter(context_parent_id__gt="").exists())
        indexed_ids = {call.args[0].id for call in index_chunk.call_args_list}
        self.assertEqual(indexed_ids, set(children.values_list("id", flat=True)))
        self.knowledge.refresh_from_db()
        self.assertIn("chunking_diagnostics", self.knowledge.metadata)

    def test_embedding_content_keeps_raw_offsets_stable(self):
        chunk = Chunk(content="body", context_header="Guide > Install", start_at=10, end_at=14)

        self.assertEqual(chunk.embedding_content(), "Guide > Install\n\nbody")
        self.assertEqual(chunk.end_at - chunk.start_at, len(chunk.content))

    def _chunking_result(self, parent_index=0):
        return ChunkingResult(
            parents=[ChunkDraft("parent body", "Guide", 0, 11, chunk_type="parent_text")],
            children=[
                ChunkDraft(
                    "child body",
                    "Guide",
                    0,
                    10,
                    context_parent_index=parent_index,
                )
            ],
            diagnostics=ChunkDiagnostics(requested_strategy="layout", selected_strategy="layout"),
        )

    def test_invalid_parent_indices_are_rejected_before_any_write(self):
        for invalid_index in (-1, 1, "0", True):
            with self.subTest(context_parent_index=invalid_index):
                with self.assertRaisesRegex(ValueError, "invalid context parent index"):
                    persist_chunking_result(self.knowledge, self._chunking_result(invalid_index))
                self.assertFalse(Chunk.objects.filter(knowledge=self.knowledge).exists())

    def test_persist_chunking_result_rolls_back_parents_when_child_insert_fails(self):
        original_bulk_create = Chunk.objects.bulk_create
        calls = 0

        def fail_after_insert(objects, *args, **kwargs):
            nonlocal calls
            calls += 1
            created = original_bulk_create(objects, *args, **kwargs)
            if calls == 2:
                raise RuntimeError("injected child persistence failure")
            return created

        with patch(
            "personal_knowledge_base.document_processing.Chunk.objects.bulk_create",
            side_effect=fail_after_insert,
        ):
            with self.assertRaisesRegex(RuntimeError, "injected child persistence failure"):
                persist_chunking_result(self.knowledge, self._chunking_result())

        self.assertFalse(Chunk.objects.filter(knowledge=self.knowledge).exists())

    def test_processing_replacement_rolls_back_old_images_chunks_and_indexes_when_child_persistence_fails(self):
        image_path = default_storage.save("tests/old-owned-image.png", ContentFile(b"old owned image"))
        image = KnowledgeImage.objects.create(
            tenant=self.tenant,
            knowledge_base=self.knowledge_base,
            knowledge=self.knowledge,
            content_hash="old-owned-image",
            storage_path=image_path,
            storage_owned=True,
            source_type="embedded",
        )
        container = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.knowledge_base,
            knowledge=self.knowledge,
            content="[image]",
            chunk_index=0,
            chunk_type="image_container",
            is_enabled=False,
            seq_id=7001,
            image_info={"image_id": image.id},
        )
        old_chunk = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.knowledge_base,
            knowledge=self.knowledge,
            content="old searchable content",
            chunk_index=1,
            chunk_type="image_ocr",
            media_parent_id=container.id,
            seq_id=7002,
            image_info={"image_id": image.id},
        )
        ensure_search_tables()
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO chunks_fts(chunk_id, tenant_id, knowledge_base_id, knowledge_id, title, content) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [old_chunk.id, self.tenant.id, self.knowledge_base.id, self.knowledge.id, "Old", old_chunk.content],
            )
            cursor.execute(
                "INSERT INTO chunk_embeddings_vec(rowid, embedding) VALUES (%s, %s)",
                [old_chunk.seq_id, pack_embedding([0.0] * settings.LLM_EMBEDDING_DIM)],
            )

        original_bulk_create = Chunk.objects.bulk_create
        bulk_create_calls = 0

        def fail_after_child_insert(objects, *args, **kwargs):
            nonlocal bulk_create_calls
            bulk_create_calls += 1
            created = original_bulk_create(objects, *args, **kwargs)
            if bulk_create_calls == 2:
                raise RuntimeError("injected child persistence failure")
            return created

        parsed = ParsedDocument(text_blocks=[TextBlock("replacement body", 0)])
        with (
            patch("personal_knowledge_base.document_processing.parse_document", return_value=parsed),
            patch("personal_knowledge_base.document_processing.split_document", return_value=self._chunking_result()),
            patch("personal_knowledge_base.document_processing.Chunk.objects.bulk_create", side_effect=fail_after_child_insert),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected child persistence failure"):
                process_knowledge(self.knowledge.id)

        self.assertEqual(
            list(Chunk.objects.filter(knowledge=self.knowledge).order_by("chunk_index").values_list("id", flat=True)),
            [container.id, old_chunk.id],
        )
        self.assertTrue(KnowledgeImage.objects.filter(id=image.id).exists())
        self.assertTrue(default_storage.exists(image_path))
        with connection.cursor() as cursor:
            self.assertEqual(
                cursor.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunk_id = %s", [old_chunk.id]).fetchone()[0],
                1,
            )
            self.assertEqual(
                cursor.execute(
                    "SELECT COUNT(*) FROM chunk_embeddings_vec WHERE rowid = %s", [old_chunk.seq_id]
                ).fetchone()[0],
                1,
            )

    def test_direct_parent_indexing_creates_no_fts_or_vector_rows(self):
        parent = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.knowledge_base,
            knowledge=self.knowledge,
            content="parent context",
            chunk_index=0,
            chunk_type="parent_text",
            seq_id=7002,
        )
        ensure_search_tables()
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO chunks_fts(chunk_id, tenant_id, knowledge_base_id, knowledge_id, title, content) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [parent.id, self.tenant.id, self.knowledge_base.id, self.knowledge.id, "Stale", parent.content],
            )
            cursor.execute(
                "INSERT INTO chunk_embeddings_vec(rowid, embedding) VALUES (%s, %s)",
                [parent.seq_id, pack_embedding([0.0] * settings.LLM_EMBEDDING_DIM)],
            )

        index_chunk(parent)

        with connection.cursor() as cursor:
            fts_count = cursor.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunk_id = %s", [parent.id]).fetchone()[0]
            vector_count = cursor.execute(
                "SELECT COUNT(*) FROM chunk_embeddings_vec WHERE rowid = %s", [parent.seq_id]
            ).fetchone()[0]
        self.assertEqual(fts_count, 0)
        self.assertEqual(vector_count, 0)

    @patch("personal_knowledge_base.model_providers.embedding")
    def test_vector_rebuild_excludes_parents_and_embeds_contextual_children(self, embedding):
        parent = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.knowledge_base,
            knowledge=self.knowledge,
            content="parent context",
            chunk_index=0,
            chunk_type="parent_text",
            seq_id=7101,
        )
        child = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.knowledge_base,
            knowledge=self.knowledge,
            content="child body",
            context_header="Installation Guide > Install",
            chunk_index=1,
            chunk_type="text",
            seq_id=7102,
        )
        disabled = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.knowledge_base,
            knowledge=self.knowledge,
            content="disabled child",
            chunk_index=2,
            chunk_type="text",
            is_enabled=False,
            seq_id=7103,
        )
        container = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.knowledge_base,
            knowledge=self.knowledge,
            content="image container",
            chunk_index=3,
            chunk_type="image_container",
            is_enabled=True,
            seq_id=7104,
        )
        orphan_id = "deleted-orphan-chunk"
        orphan_rowid = 7105
        ensure_search_tables()
        stale_chunks = [parent, disabled, container]
        with connection.cursor() as cursor:
            for stale in stale_chunks:
                cursor.execute(
                    "INSERT INTO chunks_fts(chunk_id, tenant_id, knowledge_base_id, knowledge_id, title, content) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    [stale.id, self.tenant.id, self.knowledge_base.id, self.knowledge.id, "Stale", stale.content],
                )
                cursor.execute(
                    "INSERT INTO chunk_embeddings_vec(rowid, embedding) VALUES (%s, %s)",
                    [stale.seq_id, pack_embedding([1.0] * settings.LLM_EMBEDDING_DIM)],
                )
            cursor.execute(
                "INSERT INTO chunks_fts(chunk_id, tenant_id, knowledge_base_id, knowledge_id, title, content) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [orphan_id, self.tenant.id, self.knowledge_base.id, self.knowledge.id, "Stale", "deleted"],
            )
            cursor.execute(
                "INSERT INTO chunk_embeddings_vec(rowid, embedding) VALUES (%s, %s)",
                [orphan_rowid, pack_embedding([1.0] * settings.LLM_EMBEDDING_DIM)],
            )
        embedding.return_value = [[0.0] * settings.LLM_EMBEDDING_DIM]

        rebuild_vector_index()

        self.assertEqual(embedding.call_args.args[1], ["Installation Guide > Install\n\nchild body"])
        with connection.cursor() as cursor:
            vector_rowids = {
                row[0] for row in cursor.execute("SELECT rowid FROM chunk_embeddings_vec").fetchall()
            }
            fts_ids = {row[0] for row in cursor.execute("SELECT chunk_id FROM chunks_fts").fetchall()}
        self.assertEqual(vector_rowids, {child.seq_id})
        self.assertTrue({parent.id, disabled.id, container.id, orphan_id}.isdisjoint(fts_ids))
