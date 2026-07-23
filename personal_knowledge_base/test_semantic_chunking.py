from dataclasses import replace
from unittest.mock import patch

from django.db import connection
from django.test import TestCase

from personal_knowledge_base.chunking import ChunkingConfig
from personal_knowledge_base.chunking.service import split_document
from personal_knowledge_base.chunking.structural import AtomicUnit
from personal_knowledge_base.chunking.semantic import split_semantic_units
from personal_knowledge_base.document_parsing.types import ParsedDocument, TextBlock
from personal_knowledge_base.models import Knowledge, KnowledgeBase, SemanticChunkCache, Tenant


def _unit(index, content, *, boundary_before=False):
    return AtomicUnit(
        content=content,
        start=index * 20,
        end=index * 20 + len(content),
        block_index=index,
        block_type="paragraph",
        boundary_before=boundary_before,
    )


class SemanticChunkingTests(TestCase):
    def setUp(self):
        self.config = ChunkingConfig(
            strategy="semantic",
            enable_parent_child=False,
            chunk_size=256,
            chunk_overlap=0,
            semantic_window_size=3,
            semantic_breakpoint_percentile=90.0,
        )

    def test_percentile_boundaries_are_deterministic_and_respect_hard_boundaries(self):
        units = [_unit(index, f"sentence {index}.", boundary_before=index == 6) for index in range(9)]

        def embed(texts):
            vectors = {
                "sentence 0.\nsentence 1.\nsentence 2.": [1.0, 0.0],
                "sentence 3.\nsentence 4.\nsentence 5.": [0.95, 0.05],
                "sentence 6.\nsentence 7.\nsentence 8.": [0.0, 1.0],
            }
            return [vectors[text] for text in texts]

        for expected in ([3, 6], [3, 6]):
            with self.subTest(expected=expected):
                result = split_semantic_units(units, self.config, embed=embed, model_signature="test:2")
                self.assertEqual(result.boundary_indices, expected)
                self.assertEqual(result.window_size, 3)
                self.assertEqual(result.percentile, 90.0)

    def test_semantic_cache_key_hits_and_invalidates(self):
        units = [_unit(index, f"segment {index}.") for index in range(6)]
        calls = []

        def embed(texts):
            calls.append(list(texts))
            return [[1.0, 0.0], [0.0, 1.0]]

        first = split_semantic_units(units, self.config, embed=embed, model_signature="test:2")
        second = split_semantic_units(units, self.config, embed=embed, model_signature="test:2")
        split_semantic_units(units, replace(self.config, semantic_breakpoint_percentile=80), embed=embed, model_signature="test:2")

        self.assertEqual(len(calls), 2)
        self.assertFalse(first.cache_hit)
        self.assertTrue(second.cache_hit)
        self.assertEqual(SemanticChunkCache.objects.count(), 2)

    def test_embedding_failures_and_invalid_vectors_fall_back_with_diagnostics(self):
        parsed = ParsedDocument(
            text_blocks=[
                TextBlock("# Guide", 0, block_type="heading", metadata={"heading_level": 1}),
                TextBlock("Useful setup details.", 1, block_type="paragraph"),
            ]
        )
        cases = [
            ("embedding_error", lambda _texts: (_ for _ in ()).throw(RuntimeError("offline"))),
            ("invalid_vector", lambda _texts: [[float("nan")]]),
        ]

        for reason, embed in cases:
            with self.subTest(reason=reason):
                result = split_document(
                    parsed,
                    self.config,
                    title="Guide",
                    semantic_embed=embed,
                    semantic_model_signature="test:2",
                )
                self.assertEqual(result.diagnostics.selected_strategy, "heading")
                self.assertEqual(result.diagnostics.fallback_chain[0]["strategy"], "semantic")
                self.assertIn(reason, result.diagnostics.fallback_chain[0]["reason"])

    def test_production_semantic_embedding_is_tenant_bound_and_never_indexes_cache_rows(self):
        tenant = Tenant.objects.create(name="Semantic tenant")
        knowledge_base = KnowledgeBase.objects.create(name="Semantic base", tenant=tenant)
        knowledge = Knowledge.objects.create(
            tenant=tenant,
            knowledge_base=knowledge_base,
            type="file",
            title="Guide",
            source="upload",
            embedding_model_id="embedding-42",
        )
        parsed = ParsedDocument(text_blocks=[TextBlock(f"Sentence {index}.", index) for index in range(6)])

        with patch("personal_knowledge_base.document_processing.embedding", return_value=[[1.0, 0.0], [0.0, 1.0]]) as embedding, patch(
            "personal_knowledge_base.document_processing.embedding_signature", return_value="bound:2"
        ):
            from personal_knowledge_base.document_processing import semantic_chunking_inputs

            options = semantic_chunking_inputs(knowledge, self.config)
            split_document(parsed, self.config, title=knowledge.title, **options)

        embedding.assert_called_once_with(
            tenant,
            ["Sentence 0.\nSentence 1.\nSentence 2.", "Sentence 3.\nSentence 4.\nSentence 5."],
            model_id="embedding-42",
        )
        self.assertEqual(SemanticChunkCache.objects.count(), 1)
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM chunks_fts")
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT COUNT(*) FROM chunk_embeddings_vec")
            self.assertEqual(cursor.fetchone()[0], 0)
