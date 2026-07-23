import tempfile
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import connection
from django.test import TestCase, override_settings
from django.conf import settings

from personal_knowledge_base.document_processing import process_knowledge
from personal_knowledge_base.models import Chunk, Knowledge, KnowledgeBase, Tenant
from personal_knowledge_base.search import ensure_search_tables, index_chunk, rebuild_vector_index


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

    def test_direct_parent_indexing_creates_no_fts_or_vector_rows(self):
        parent = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.knowledge_base,
            knowledge=self.knowledge,
            content="parent context",
            chunk_index=0,
            chunk_type="parent_text",
        )
        ensure_search_tables()

        index_chunk(parent)

        with connection.cursor() as cursor:
            fts_count = cursor.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunk_id = %s", [parent.id]).fetchone()[0]
            vector_count = cursor.execute(
                "SELECT COUNT(*) FROM chunk_embeddings_vec WHERE rowid = %s", [parent.seq_id or 0]
            ).fetchone()[0]
        self.assertEqual(fts_count, 0)
        self.assertEqual(vector_count, 0)

    @patch("personal_knowledge_base.model_providers.embedding")
    def test_vector_rebuild_excludes_parents_and_embeds_contextual_children(self, embedding):
        Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.knowledge_base,
            knowledge=self.knowledge,
            content="parent context",
            chunk_index=0,
            chunk_type="parent_text",
        )
        Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.knowledge_base,
            knowledge=self.knowledge,
            content="child body",
            context_header="Installation Guide > Install",
            chunk_index=1,
            chunk_type="text",
        )
        embedding.return_value = [[0.0] * settings.LLM_EMBEDDING_DIM]

        rebuild_vector_index()

        self.assertEqual(embedding.call_args.args[1], ["Installation Guide > Install\n\nchild body"])
