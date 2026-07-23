from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from django.db import connection
from django.test import TestCase

from personal_knowledge_base.chunking import ChunkingConfig
from personal_knowledge_base.chunking.service import split_document
from personal_knowledge_base.chunking.structural import AtomicUnit
from personal_knowledge_base.chunking.semantic import SemanticSplitError, split_semantic_units
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
        units = [_unit(index, f"sentence {index}.", boundary_before=index == 8) for index in range(12)]

        def embed(texts):
            vectors = {
                "sentence 0.\nsentence 1.\nsentence 2.": [1.0, 0.0],
                "sentence 1.\nsentence 2.\nsentence 3.": [0.995, 0.1],
                "sentence 2.\nsentence 3.\nsentence 4.": [0.98, 0.2],
                "sentence 3.\nsentence 4.\nsentence 5.": [0.95, 0.3],
                "sentence 4.\nsentence 5.\nsentence 6.": [0.0, 1.0],
                "sentence 5.\nsentence 6.\nsentence 7.": [0.1, 0.995],
                "sentence 6.\nsentence 7.": [0.2, 0.98],
                "sentence 7.": [0.25, 0.97],
                "sentence 8.\nsentence 9.\nsentence 10.": [1.0, 0.0],
                "sentence 9.\nsentence 10.\nsentence 11.": [0.95, 0.3],
                "sentence 10.\nsentence 11.": [0.8, 0.6],
                "sentence 11.": [0.7, 0.7],
            }
            return [vectors.get(text, [1.0, 0.0]) for text in texts]

        boundary_config = replace(self.config, chunk_size=128)
        for expected in ([4, 8], [4, 8]):
            with self.subTest(expected=expected):
                result = split_semantic_units(units, boundary_config, embed=embed, model_signature="test:2")
                self.assertEqual(result.boundary_indices, expected)
                self.assertEqual(result.window_size, 3)
                self.assertEqual(result.percentile, 90.0)

        parsed = ParsedDocument(
            text_blocks=[TextBlock(f"unit-{index:02d}-text", index) for index in range(8)]
        )
        with self.subTest(case="minimum-size consolidation"):
            result = split_document(
                parsed,
                replace(self.config, chunk_size=128, semantic_breakpoint_percentile=0),
                title="Minimum",
                semantic_embed=lambda texts: [[1.0, 0.0] for _text in texts],
                semantic_model_signature="test:2",
            )
            self.assertEqual(result.diagnostics.selected_strategy, "semantic")
            self.assertEqual(len(result.children), 2)
            self.assertTrue(all(len(chunk.content.strip()) >= 32 for chunk in result.children))

        contiguous_units = [
            AtomicUnit(
                content="x" * 10,
                start=index * 10,
                end=(index + 1) * 10,
                block_index=index,
                block_type="paragraph",
            )
            for index in range(7)
        ]
        with self.subTest(case="minimum-size does not count synthetic separators"):
            result = split_semantic_units(
                contiguous_units,
                replace(self.config, chunk_size=128),
                embed=lambda texts: [
                    [0.0, 1.0] if index == 3 else [1.0, 0.0]
                    for index, _text in enumerate(texts)
                ],
                model_signature="contiguous-minimum:2",
            )
            self.assertEqual(result.boundary_indices, [])

    def test_semantic_cache_key_hits_and_invalidates(self):
        units = [_unit(index, f"segment {index}.") for index in range(6)]
        calls = []

        def embed(texts):
            calls.append(list(texts))
            return [[1.0, (index + 1) / 10] for index, _text in enumerate(texts)]

        with self.subTest(case="key hit and isolation"):
            first = split_semantic_units(units, self.config, embed=embed, model_signature="tenant-a-config-a:2")
            second = split_semantic_units(units, self.config, embed=embed, model_signature="tenant-a-config-a:2")
            split_semantic_units(
                units,
                replace(self.config, semantic_breakpoint_percentile=80),
                embed=embed,
                model_signature="tenant-a-config-a:2",
            )
            split_semantic_units(units, self.config, embed=embed, model_signature="tenant-a-config-b:2")

            self.assertEqual(len(calls), 3)
            self.assertFalse(first.cache_hit)
            self.assertTrue(second.cache_hit)
            self.assertEqual(SemanticChunkCache.objects.count(), 3)

        with self.subTest(case="cached expected dimension"):
            SemanticChunkCache.objects.all().delete()
            split_semantic_units(units, self.config, embed=embed, model_signature="malformed-cache:2")
            cached = SemanticChunkCache.objects.get()
            cached.vectors = [[1.0, 0.0, 0.0] for _text in cached.window_inputs]
            cached.save(update_fields=["vectors"])
            with self.assertRaisesRegex(SemanticSplitError, "invalid_vector_dimension"):
                split_semantic_units(
                    units,
                    self.config,
                    embed=lambda _texts: self.fail("malformed cache must not embed"),
                    model_signature="malformed-cache:2",
                )

        race_units = [_unit(index, f"race unit {index}.") for index in range(8)]

        def concurrent_winner(*, defaults, **_key):
            winner_vectors = [[1.0, 0.0] if index < 4 else [0.0, 1.0] for index in range(len(defaults["window_inputs"]))]
            return SimpleNamespace(window_inputs=defaults["window_inputs"], vectors=winner_vectors), False

        with self.subTest(case="concurrent winner is re-read"):
            SemanticChunkCache.objects.all().delete()
            with patch.object(SemanticChunkCache.objects, "get_or_create", side_effect=concurrent_winner):
                result = split_semantic_units(
                    race_units,
                    replace(self.config, chunk_size=128),
                    embed=lambda texts: [[1.0, 0.0] for _text in texts],
                    model_signature="race:2",
                )
            self.assertEqual(result.boundary_indices, [4])

        with self.subTest(case="concurrent winner is validated"):
            SemanticChunkCache.objects.all().delete()

            def malformed_winner(*, defaults, **_key):
                vectors = [[1.0, 0.0, 0.0] for _text in defaults["window_inputs"]]
                return SimpleNamespace(window_inputs=defaults["window_inputs"], vectors=vectors), False

            with patch.object(SemanticChunkCache.objects, "get_or_create", side_effect=malformed_winner):
                with self.assertRaisesRegex(SemanticSplitError, "invalid_vector_dimension"):
                    split_semantic_units(
                        race_units,
                        self.config,
                        embed=lambda texts: [[1.0, 0.0] for _text in texts],
                        model_signature="race-invalid:2",
                    )

    def test_embedding_failures_and_invalid_vectors_fall_back_with_diagnostics(self):
        parsed = ParsedDocument(
            text_blocks=[
                TextBlock("# Guide", 0, block_type="heading", metadata={"heading_level": 1}),
                TextBlock("Useful setup details.", 1, block_type="paragraph"),
            ]
        )
        cases = [
            ("embedding_error", lambda _texts: (_ for _ in ()).throw(RuntimeError("offline"))),
            ("invalid_vector_dimension", lambda texts: [[1.0] for _text in texts]),
            ("invalid_vector_non_finite", lambda texts: [[float("nan"), 0.0] for _text in texts]),
            ("invalid_vector_zero_norm", lambda texts: [[0.0, 0.0] for _text in texts]),
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

        with self.subTest(reason="invalid_vector_zero_norm_singleton_segment"):
            singleton_boundary_units = [
                _unit(0, "first segment"),
                _unit(1, "second segment", boundary_before=True),
            ]
            with self.assertRaisesRegex(SemanticSplitError, "invalid_vector_zero_norm"):
                split_semantic_units(
                    singleton_boundary_units,
                    self.config,
                    embed=lambda texts: [[0.0, 0.0] for _text in texts],
                    model_signature="singleton-zero:2",
                )

        knowledge = SimpleNamespace(tenant=SimpleNamespace(pk="tenant-setup"), embedding_model_id="embedding-42")
        with self.subTest(reason="semantic_setup_error"), patch(
            "personal_knowledge_base.document_processing.embedding_signature",
            side_effect=RuntimeError("configuration backend offline"),
        ):
            from personal_knowledge_base.document_processing import semantic_chunking_inputs

            try:
                options = semantic_chunking_inputs(knowledge, self.config)
            except RuntimeError as exc:
                self.fail(f"semantic setup exception escaped before fallback: {exc}")
            result = split_document(parsed, self.config, title="Guide", **options)
            self.assertEqual(result.diagnostics.selected_strategy, "heading")
            self.assertEqual(result.diagnostics.fallback_chain[0]["strategy"], "semantic")
            self.assertIn("semantic_setup_error", result.diagnostics.fallback_chain[0]["reason"])

    def test_production_semantic_embedding_is_tenant_bound_and_never_indexes_cache_rows(self):
        tenant = Tenant.objects.create(name="Semantic tenant", api_key="semantic-a")
        other_tenant = Tenant.objects.create(name="Other semantic tenant", api_key="semantic-b")
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
        resolved_a = {
            "model_id": "embedding-42",
            "provider": "provider-a",
            "base_url": "https://embedding-a.example/v1",
            "api_key": "secret-a",
            "model": "model-a",
            "dimension": 2,
        }
        resolved_b = {**resolved_a, "base_url": "https://embedding-b.example/v1", "api_key": "secret-b"}

        with patch(
            "personal_knowledge_base.document_processing.active_embedding_config",
            side_effect=[resolved_a, resolved_a, resolved_b],
            create=True,
        ):
            from personal_knowledge_base.document_processing import semantic_chunking_inputs

            options = semantic_chunking_inputs(knowledge, self.config)
            other_options = semantic_chunking_inputs(
                SimpleNamespace(tenant=other_tenant, embedding_model_id="embedding-42"), self.config
            )
            changed_options = semantic_chunking_inputs(knowledge, self.config)

        signatures = {
            options["semantic_model_signature"],
            other_options["semantic_model_signature"],
            changed_options["semantic_model_signature"],
        }
        self.assertEqual(len(signatures), 3)
        self.assertTrue(all(signature.endswith(":2") for signature in signatures))
        self.assertTrue(all("secret" not in signature for signature in signatures))

        def embed(bound_tenant, texts, *, model_id):
            self.assertEqual(bound_tenant, tenant)
            self.assertEqual(model_id, "embedding-42")
            return [[1.0, (index + 1) / 10] for index, _text in enumerate(texts)]

        with patch("personal_knowledge_base.document_processing.embedding", side_effect=embed) as embedding:
            split_document(parsed, self.config, title=knowledge.title, **options)

        embedding.assert_called_once_with(
            tenant,
            [
                "Sentence 0.\nSentence 1.\nSentence 2.",
                "Sentence 1.\nSentence 2.\nSentence 3.",
                "Sentence 2.\nSentence 3.\nSentence 4.",
                "Sentence 3.\nSentence 4.\nSentence 5.",
                "Sentence 4.\nSentence 5.",
                "Sentence 5.",
            ],
            model_id="embedding-42",
        )
        self.assertEqual(SemanticChunkCache.objects.count(), 1)
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM chunks_fts")
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT COUNT(*) FROM chunk_embeddings_vec")
            self.assertEqual(cursor.fetchone()[0], 0)

        with patch(
            "personal_knowledge_base.document_processing.active_embedding_config", create=True
        ) as config_resolution, patch("personal_knowledge_base.document_processing.embedding") as auto_embedding:
            auto_config = replace(self.config, strategy="auto")
            self.assertEqual(semantic_chunking_inputs(knowledge, auto_config), {})
            result = split_document(parsed, auto_config, title=knowledge.title)
            self.assertEqual(result.diagnostics.requested_strategy, "auto")
            config_resolution.assert_not_called()
            auto_embedding.assert_not_called()
