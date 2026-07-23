"""BGE-M3 双路召回 + RRF + BGE-Reranker 检索链测试。

覆盖：RRF 公式与双路命中奖励、未配置时的显式降级、维度不匹配硬报错、检索端点 API 契约。
"""

import json
from unittest.mock import patch

from django.conf import settings
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .model_providers import EmbeddingDimensionMismatchError
from .models import Chunk, Knowledge, KnowledgeBase, Tenant
from .search import (
    _hydrate_candidates,
    _vector_ranked,
    ensure_search_tables,
    expand_short_chunks,
    hybrid_search,
    hybrid_search_ex,
    index_chunk,
    pack_embedding,
    rrf_fuse,
)


ENV_OFF = override_settings(LLM_USE_ENV_EMBEDDING=False, LLM_USE_ENV_RERANK=False)
AUTO_SETUP_ENABLED = override_settings(ALLOW_AUTO_SETUP=True)


class RrfFuseTests(TestCase):
    def test_formula_and_double_hit_bonus(self):
        # A 命中双路（keyword rank1 + vector rank1），应高于仅单路的 B、C
        fused = rrf_fuse(["A", "B", "C"], ["A", "C"], rrf_k=60)
        scores = {f["chunk_id"]: f["rrf_score"] for f in fused}
        a = next(f for f in fused if f["chunk_id"] == "A")
        self.assertAlmostEqual(scores["A"], 1 / 61 + 1 / 61)
        self.assertIsNotNone(a["keyword_rank"])
        self.assertIsNotNone(a["vector_rank"])
        self.assertGreater(scores["A"], scores["B"])
        self.assertGreater(scores["A"], scores["C"])


@ENV_OFF
class HybridSearchExTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="rrf", api_key="rrf-key")
        self.kb = KnowledgeBase.objects.create(tenant=self.tenant, name="rrf-kb")
        knowledge = Knowledge.objects.create(tenant=self.tenant, knowledge_base=self.kb, title="t", embedding_model_id="")
        self.chunk = Chunk.objects.create(
            tenant=self.tenant, knowledge_base=self.kb, knowledge=knowledge,
            content="Django 是 Python Web 框架", chunk_index=0,
        )
        index_chunk(self.chunk)

    def test_vector_and_rerank_degradation_when_unconfigured(self):
        results, meta = hybrid_search_ex(self.tenant.id, [str(self.kb.id)], "Python 框架", 5)
        stages = {d["stage"] for d in meta["degradations"]}
        self.assertIn("vector", stages)  # embedding 未配置
        self.assertIn("rerank", stages)  # rerank 未配置
        self.assertTrue(meta["degraded"])
        self.assertTrue(any(r["chunk_id"] == self.chunk.id for r in results))

    def test_dimension_mismatch_propagates(self):
        # D1 严格模式：维度不匹配直接报错，绝不静默降级到 FTS-only
        with patch("personal_knowledge_base.model_providers.embedding", side_effect=EmbeddingDimensionMismatchError("dim")):
            with self.assertRaises(EmbeddingDimensionMismatchError):
                index_chunk(self.chunk)

    def test_hydration_does_not_emit_ambiguous_parent_chunk_id(self):
        entries = [
            {
                "chunk_id": self.chunk.id,
                "rrf_score": 1.0,
                "keyword_rank": 1,
                "vector_rank": None,
                "match_sources": ["keyword"],
            }
        ]

        result = _hydrate_candidates(
            entries,
            tenant_id=self.tenant.id,
            kb_ids=[self.kb.id],
        )

        self.assertEqual(len(result), 1)
        self.assertNotIn("parent_chunk_id", result[0])

    def test_stale_nonsearchable_physical_candidates_do_not_reach_rerank(self):
        enabled_container = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="gateword image container",
            chunk_index=1,
            chunk_type="image_container",
            seq_id=8101,
        )
        deleted_child = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="gateword deleted child",
            chunk_index=2,
            deleted_at=timezone.now(),
            seq_id=8102,
        )
        disabled_knowledge = Knowledge.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            title="disabled",
            enable_status="disabled",
        )
        disabled_child = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=disabled_knowledge,
            content="gateword disabled knowledge",
            chunk_index=0,
            seq_id=8103,
        )
        deleted_knowledge = Knowledge.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            title="deleted",
            deleted_at=timezone.now(),
        )
        deleted_knowledge_child = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=deleted_knowledge,
            content="gateword deleted knowledge",
            chunk_index=0,
            seq_id=8104,
        )
        eligible_near = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="gateword eligible near",
            chunk_index=3,
            seq_id=8105,
        )
        eligible_far = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="gateword eligible far",
            chunk_index=4,
            seq_id=8106,
        )
        stale_chunks = [enabled_container, deleted_child, disabled_child, deleted_knowledge_child]
        ensure_search_tables()
        with connection.cursor() as cursor:
            for chunk in [*stale_chunks, eligible_near, eligible_far]:
                cursor.execute(
                    "INSERT INTO chunks_fts(chunk_id, tenant_id, knowledge_base_id, knowledge_id, title, content) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    [chunk.id, self.tenant.id, self.kb.id, chunk.knowledge_id, "stale", chunk.content],
                )
                value = 0.0 if chunk in stale_chunks else 0.1 if chunk == eligible_near else 0.2
                cursor.execute(
                    "INSERT INTO chunk_embeddings_vec(rowid, embedding) VALUES (%s, %s)",
                    [chunk.seq_id, pack_embedding([value] * settings.LLM_EMBEDDING_DIM)],
                )

        with patch("personal_knowledge_base.model_providers.embedding", return_value=[[0.0] * settings.LLM_EMBEDDING_DIM]):
            self.assertEqual(
                _vector_ranked(self.tenant.id, {self.kb.id}, "gateword", 6, self.tenant),
                [eligible_near.id, eligible_far.id],
            )

        with (
            patch("personal_knowledge_base.model_providers.active_embedding_config", return_value={"model": "test"}),
            patch("personal_knowledge_base.model_providers.embedding", return_value=[[0.0] * settings.LLM_EMBEDDING_DIM]),
            patch("personal_knowledge_base.model_providers.active_rerank_config", return_value={"model": "test"}),
            patch("personal_knowledge_base.model_providers.rerank", side_effect=lambda _query, candidates, **_kwargs: candidates) as rerank,
        ):
            results, meta = hybrid_search_ex(
                self.tenant.id,
                [self.kb.id],
                "gateword",
                5,
                keyword_top_k=10,
                vector_top_k=10,
                rerank_top_k=10,
            )

        self.assertEqual({item["chunk_id"] for item in rerank.call_args.args[1]}, {eligible_near.id, eligible_far.id})
        self.assertEqual({item["chunk_id"] for item in results}, {eligible_near.id, eligible_far.id})
        self.assertEqual(meta["candidate_counts"]["rerank_input"], 2)

    def test_stale_fts_row_cannot_hydrate_foreign_tenant_chunk(self):
        foreign_tenant = Tenant.objects.create(name="foreign", api_key="foreign-rrf-key")
        foreign_kb = KnowledgeBase.objects.create(tenant=foreign_tenant, name="foreign-kb")
        foreign_knowledge = Knowledge.objects.create(
            tenant=foreign_tenant,
            knowledge_base=foreign_kb,
            title="foreign",
        )
        foreign_chunk = Chunk.objects.create(
            tenant=foreign_tenant,
            knowledge_base=foreign_kb,
            knowledge=foreign_knowledge,
            content="tenantleak secret evidence",
            chunk_index=0,
        )
        ensure_search_tables()
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO chunks_fts(chunk_id, tenant_id, knowledge_base_id, knowledge_id, title, content) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [
                    foreign_chunk.id,
                    self.tenant.id,
                    self.kb.id,
                    self.chunk.knowledge_id,
                    "forged owner",
                    foreign_chunk.content,
                ],
            )

        with (
            patch("personal_knowledge_base.model_providers.active_rerank_config", return_value={"model": "test"}),
            patch(
                "personal_knowledge_base.model_providers.rerank",
                side_effect=lambda _query, candidates, **_kwargs: candidates,
            ) as rerank,
        ):
            results, _meta = hybrid_search_ex(
                self.tenant.id,
                [self.kb.id],
                "tenantleak",
                5,
            )

        rerank_ids = {
            item["chunk_id"]
            for item in (rerank.call_args.args[1] if rerank.call_args else [])
        }
        self.assertNotIn(foreign_chunk.id, rerank_ids)
        self.assertNotIn(foreign_chunk.id, {item["chunk_id"] for item in results})
        self.assertNotIn("secret evidence", " ".join(item["content"] for item in results))

    def test_stale_fts_row_cannot_hydrate_chunk_from_unrequested_kb(self):
        other_kb = KnowledgeBase.objects.create(tenant=self.tenant, name="other-kb")
        other_knowledge = Knowledge.objects.create(
            tenant=self.tenant,
            knowledge_base=other_kb,
            title="other",
        )
        other_chunk = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=other_kb,
            knowledge=other_knowledge,
            content="kbleak private evidence",
            chunk_index=0,
        )
        ensure_search_tables()
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO chunks_fts(chunk_id, tenant_id, knowledge_base_id, knowledge_id, title, content) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [
                    other_chunk.id,
                    self.tenant.id,
                    self.kb.id,
                    self.chunk.knowledge_id,
                    "forged kb",
                    other_chunk.content,
                ],
            )

        with (
            patch("personal_knowledge_base.model_providers.active_rerank_config", return_value={"model": "test"}),
            patch(
                "personal_knowledge_base.model_providers.rerank",
                side_effect=lambda _query, candidates, **_kwargs: candidates,
            ) as rerank,
        ):
            results, _meta = hybrid_search_ex(
                self.tenant.id,
                [self.kb.id],
                "kbleak",
                5,
            )

        rerank_ids = {
            item["chunk_id"]
            for item in (rerank.call_args.args[1] if rerank.call_args else [])
        }
        self.assertNotIn(other_chunk.id, rerank_ids)
        self.assertNotIn(other_chunk.id, {item["chunk_id"] for item in results})
        self.assertNotIn("private evidence", " ".join(item["content"] for item in results))

    def test_direct_search_reranks_children_then_collapses_parent_siblings(self):
        parent = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="first child-----second child",
            chunk_index=10,
            chunk_type="parent_text",
            is_enabled=False,
            start_at=0,
            end_at=28,
        )
        child_a = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="first child",
            chunk_index=11,
            context_parent_id=parent.id,
            start_at=0,
            end_at=11,
        )
        child_b = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="second child",
            chunk_index=12,
            context_parent_id=parent.id,
            start_at=16,
            end_at=28,
        )

        def rerank_children(_query, candidates, **_kwargs):
            self.assertEqual([item["content"] for item in candidates], ["first child", "second child"])
            return [{**candidates[1], "score": 0.95, "rerank_score": 0.95}, candidates[0]]

        with (
            patch("personal_knowledge_base.search._fts_ranked", return_value=[child_a.id, child_b.id]),
            patch("personal_knowledge_base.search._vector_recall", return_value=[]),
            patch("personal_knowledge_base.model_providers.active_rerank_config", return_value={"model": "test"}),
            patch("personal_knowledge_base.model_providers.rerank", side_effect=rerank_children),
        ):
            results, _meta = hybrid_search_ex(self.tenant.id, [self.kb.id], "child", 5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["chunk_id"], child_b.id)
        self.assertEqual(results[0]["parent_chunk_id"], parent.id)
        self.assertEqual(results[0]["matched_child_ids"], [child_b.id, child_a.id])
        self.assertEqual(results[0]["content"], parent.content)

    def test_partial_reranker_order_survives_parent_collapse_and_top_k(self):
        parent = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="grouped first grouped second",
            chunk_index=13,
            chunk_type="parent_text",
            is_enabled=False,
            start_at=0,
            end_at=28,
        )
        child_a = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="grouped first",
            chunk_index=14,
            context_parent_id=parent.id,
            start_at=0,
            end_at=13,
        )
        standalone_a = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="standalone omitted",
            chunk_index=15,
        )
        child_b = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="grouped second",
            chunk_index=16,
            context_parent_id=parent.id,
            start_at=14,
            end_at=28,
        )
        standalone_scored = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="standalone provider winner",
            chunk_index=17,
        )

        def partial_rerank(_query, candidates, **_kwargs):
            by_id = {item["chunk_id"]: item for item in candidates}
            return [
                {
                    **by_id[standalone_scored.id],
                    "score": 0.01,
                    "rerank_score": 0.01,
                },
                by_id[child_a.id],
                by_id[standalone_a.id],
                by_id[child_b.id],
            ]

        with (
            patch(
                "personal_knowledge_base.search._fts_ranked",
                return_value=[child_a.id, standalone_a.id, child_b.id, standalone_scored.id],
            ),
            patch("personal_knowledge_base.search._vector_recall", return_value=[]),
            patch("personal_knowledge_base.model_providers.active_rerank_config", return_value={"model": "test"}),
            patch("personal_knowledge_base.model_providers.rerank", side_effect=partial_rerank),
        ):
            results, _meta = hybrid_search_ex(self.tenant.id, [self.kb.id], "evidence", 2)

        self.assertEqual(
            [item["chunk_id"] for item in results],
            [standalone_scored.id, child_a.id],
        )
        self.assertEqual([item["final_rank"] for item in results], [1, 2])
        self.assertEqual(results[1]["matched_child_ids"], [child_a.id, child_b.id])

    def test_direct_search_applies_top_k_after_sibling_collapse(self):
        ranked_children = []
        expected_parents = []
        parent_contents = [
            "alpha quartz installation evidence",
            "bravo cedar authorization details",
            "charlie lunar retention policy",
        ]
        for parent_index, parent_content in enumerate(parent_contents):
            parent = Chunk.objects.create(
                tenant=self.tenant,
                knowledge_base=self.kb,
                knowledge=self.chunk.knowledge,
                content=parent_content,
                chunk_index=100 + parent_index * 10,
                chunk_type="parent_text",
                is_enabled=False,
                start_at=0,
                end_at=len(parent_content),
            )
            expected_parents.append(parent.id)
            sibling_count = 4 if parent_index == 0 else 1
            for sibling_index in range(sibling_count):
                child = Chunk.objects.create(
                    tenant=self.tenant,
                    knowledge_base=self.kb,
                    knowledge=self.chunk.knowledge,
                    content=parent_content,
                    chunk_index=101 + parent_index * 10 + sibling_index,
                    context_parent_id=parent.id,
                    start_at=0,
                    end_at=len(parent_content),
                )
                ranked_children.append(child.id)

        with (
            patch("personal_knowledge_base.search._fts_ranked", return_value=ranked_children),
            patch("personal_knowledge_base.search._vector_recall", return_value=[]),
        ):
            results, _meta = hybrid_search_ex(self.tenant.id, [self.kb.id], "evidence", 3)

        self.assertEqual(len(results), 3)
        self.assertEqual({item["parent_chunk_id"] for item in results}, set(expected_parents))

    def test_query_expansion_combines_raw_siblings_before_single_parent_resolution(self):
        parent = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="alpha evidence and beta evidence",
            chunk_index=20,
            chunk_type="parent_text",
            is_enabled=False,
            start_at=0,
            end_at=32,
        )
        child_a = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="alpha evidence",
            chunk_index=21,
            context_parent_id=parent.id,
            start_at=0,
            end_at=14,
        )
        child_b = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="beta evidence",
            chunk_index=22,
            context_parent_id=parent.id,
            start_at=19,
            end_at=32,
        )

        with (
            patch("personal_knowledge_base.search._fts_ranked", side_effect=[[child_a.id], [child_b.id]]),
            patch("personal_knowledge_base.search._vector_recall", return_value=[]),
            patch("personal_knowledge_base.search.expand_query", return_value=["beta"]),
            patch("personal_knowledge_base.graph_rag.graph_search_results", return_value=[]),
            patch("personal_knowledge_base.graph_rag.expand_relation_context", return_value=[]),
        ):
            results = hybrid_search(self.tenant.id, [self.kb.id], "alpha", top_k=2)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["parent_chunk_id"], parent.id)
        self.assertEqual(results[0]["matched_child_ids"], [child_a.id, child_b.id])

    def test_query_expansion_underfill_counts_unique_parent_groups(self):
        parent_a = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="alpha one alpha two",
            chunk_index=40,
            chunk_type="parent_text",
            is_enabled=False,
            start_at=0,
            end_at=19,
        )
        child_a = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="alpha one",
            chunk_index=41,
            context_parent_id=parent_a.id,
            start_at=0,
            end_at=9,
        )
        child_b = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="alpha two",
            chunk_index=42,
            context_parent_id=parent_a.id,
            start_at=10,
            end_at=19,
        )
        parent_b = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="expanded beta",
            chunk_index=50,
            chunk_type="parent_text",
            is_enabled=False,
            start_at=0,
            end_at=13,
        )
        child_c = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="expanded beta",
            chunk_index=51,
            context_parent_id=parent_b.id,
            start_at=0,
            end_at=13,
        )

        with (
            patch(
                "personal_knowledge_base.search._fts_ranked",
                side_effect=[[child_a.id, child_b.id], [child_c.id]],
            ),
            patch("personal_knowledge_base.search._vector_recall", return_value=[]),
            patch("personal_knowledge_base.search.expand_query", return_value=["beta"]),
            patch("personal_knowledge_base.graph_rag.graph_search_results", return_value=[]),
            patch("personal_knowledge_base.graph_rag.expand_relation_context", return_value=[]),
        ):
            results = hybrid_search(self.tenant.id, [self.kb.id], "alpha question", top_k=2)

        self.assertEqual(
            {item["parent_chunk_id"] for item in results},
            {parent_a.id, parent_b.id},
        )

    def test_media_only_results_satisfy_query_expansion_context_threshold(self):
        media_content = ("alpha quartz evidence", "bravo cedar evidence")
        media = [
            Chunk.objects.create(
                tenant=self.tenant,
                knowledge_base=self.kb,
                knowledge=self.chunk.knowledge,
                content=media_content[index],
                chunk_index=52 + index,
                chunk_type=chunk_type,
            )
            for index, chunk_type in enumerate(("image_ocr", "image_caption"))
        ]

        with (
            patch("personal_knowledge_base.search._fts_ranked", return_value=[item.id for item in media]) as fts,
            patch("personal_knowledge_base.search._vector_recall", return_value=[]),
            patch("personal_knowledge_base.search.expand_query", return_value=["unnecessary"]) as expand,
            patch("personal_knowledge_base.graph_rag.graph_search_results", return_value=[]),
            patch("personal_knowledge_base.graph_rag.expand_relation_context", return_value=[]),
        ):
            results = hybrid_search(self.tenant.id, [self.kb.id], "media", top_k=2)

        expand.assert_not_called()
        fts.assert_called_once()
        self.assertEqual({item["chunk_id"] for item in results}, {item.id for item in media})

    def test_mixed_text_and_media_results_satisfy_query_expansion_context_threshold(self):
        parent = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="grouped text evidence",
            chunk_index=54,
            chunk_type="parent_text",
            is_enabled=False,
            start_at=0,
            end_at=21,
        )
        text_child = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content=parent.content,
            chunk_index=55,
            context_parent_id=parent.id,
            start_at=0,
            end_at=21,
        )
        media = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="ocr evidence",
            chunk_index=56,
            chunk_type="image_ocr",
        )

        with (
            patch("personal_knowledge_base.search._fts_ranked", return_value=[text_child.id, media.id]) as fts,
            patch("personal_knowledge_base.search._vector_recall", return_value=[]),
            patch("personal_knowledge_base.search.expand_query", return_value=["unnecessary"]) as expand,
            patch("personal_knowledge_base.graph_rag.graph_search_results", return_value=[]),
            patch("personal_knowledge_base.graph_rag.expand_relation_context", return_value=[]),
        ):
            results = hybrid_search(self.tenant.id, [self.kb.id], "evidence", top_k=2)

        expand.assert_not_called()
        fts.assert_called_once()
        self.assertEqual({item["chunk_id"] for item in results}, {text_child.id, media.id})

    def test_original_and_expansion_children_share_final_rerank_and_provenance(self):
        parents_and_children = []
        for index, content in enumerate(("original evidence", "expanded evidence")):
            parent = Chunk.objects.create(
                tenant=self.tenant,
                knowledge_base=self.kb,
                knowledge=self.chunk.knowledge,
                content=content,
                chunk_index=60 + index * 2,
                chunk_type="parent_text",
                is_enabled=False,
                start_at=0,
                end_at=len(content),
            )
            child = Chunk.objects.create(
                tenant=self.tenant,
                knowledge_base=self.kb,
                knowledge=self.chunk.knowledge,
                content=content,
                chunk_index=61 + index * 2,
                context_parent_id=parent.id,
                start_at=0,
                end_at=len(content),
            )
            parents_and_children.append((parent, child))
        original = parents_and_children[0][1]
        expanded = parents_and_children[1][1]

        def rerank_combined(_query, candidates, **_kwargs):
            self.assertEqual({item["chunk_id"] for item in candidates}, {original.id, expanded.id})
            by_id = {item["chunk_id"]: item for item in candidates}
            return [
                {**by_id[expanded.id], "score": 0.95, "rerank_score": 0.95},
                {**by_id[original.id], "score": 0.7, "rerank_score": 0.7},
            ]

        with (
            patch(
                "personal_knowledge_base.search._fts_ranked",
                side_effect=[[original.id], [expanded.id]],
            ),
            patch("personal_knowledge_base.search._vector_recall", return_value=[]),
            patch("personal_knowledge_base.search.expand_query", return_value=["expanded"]),
            patch("personal_knowledge_base.model_providers.active_rerank_config", return_value={"model": "test"}),
            patch("personal_knowledge_base.model_providers.rerank", side_effect=rerank_combined) as rerank,
            patch("personal_knowledge_base.graph_rag.graph_search_results", return_value=[]),
            patch("personal_knowledge_base.graph_rag.expand_relation_context", return_value=[]),
        ):
            results = hybrid_search(self.tenant.id, [self.kb.id], "question", top_k=2)

        rerank.assert_called_once()
        self.assertEqual(results[0]["chunk_id"], expanded.id)
        self.assertEqual(results[0]["rerank_score"], 0.95)
        self.assertIn("keyword_expansion", results[0]["match_sources"])
        self.assertEqual(
            results[0]["matched_child_provenance"][0]["chunk_id"],
            expanded.id,
        )

    def test_parent_child_hit_skips_short_chunk_neighbor_expansion(self):
        parent = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="parent",
            chunk_index=30,
            chunk_type="parent_text",
            is_enabled=False,
        )
        child = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="short child",
            chunk_index=31,
            context_parent_id=parent.id,
        )
        Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="neighbor text",
            chunk_index=32,
        )
        raw = {
            "chunk_id": child.id,
            "id": child.id,
            "content": child.content,
            "score": 1.0,
            "retrieval_path": "document",
            "chunk_type": "text",
        }

        expanded = expand_short_chunks([raw], min_chars=350, max_chars=850)

        self.assertEqual(expanded[0]["content"], child.content)

    def test_short_chunk_neighbors_are_enabled_flat_text_in_same_tenant_knowledge_and_kb(self):
        target = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="target flat text",
            chunk_index=90,
        )
        eligible = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="eligible local neighbor",
            chunk_index=91,
        )
        other_kb = KnowledgeBase.objects.create(tenant=self.tenant, name="neighbor-other-kb")
        Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=other_kb,
            knowledge=self.chunk.knowledge,
            content="wrong kb neighbor",
            chunk_index=89,
        )
        other_tenant = Tenant.objects.create(name="neighbor-foreign", api_key="neighbor-foreign-key")
        Chunk.objects.create(
            tenant=other_tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="wrong tenant neighbor",
            chunk_index=88,
        )
        Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="disabled neighbor",
            chunk_index=92,
            is_enabled=False,
        )
        Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="deleted neighbor",
            chunk_index=93,
            deleted_at=timezone.now(),
        )
        parent = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="parent source",
            chunk_index=94,
            chunk_type="parent_text",
            is_enabled=False,
        )
        Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="parent linked neighbor",
            chunk_index=95,
            context_parent_id=parent.id,
        )
        raw = {
            "chunk_id": target.id,
            "id": target.id,
            "content": target.content,
            "score": 1.0,
            "retrieval_path": "document",
            "chunk_type": "text",
        }

        content = expand_short_chunks([raw], min_chars=350, max_chars=850)[0]["content"]

        self.assertIn(eligible.content, content)
        self.assertNotIn("wrong kb neighbor", content)
        self.assertNotIn("wrong tenant neighbor", content)
        self.assertNotIn("disabled neighbor", content)
        self.assertNotIn("deleted neighbor", content)
        self.assertNotIn("parent linked neighbor", content)

    def test_public_search_does_not_neighbor_expand_graph_results(self):
        graph_chunk = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="graph evidence",
            chunk_index=70,
        )
        Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="unrelated graph neighbor",
            chunk_index=71,
        )
        graph_result = {
            "chunk_id": graph_chunk.id,
            "id": graph_chunk.id,
            "content": graph_chunk.content,
            "score": 1.0,
            "chunk_type": "text",
            "knowledge_id": graph_chunk.knowledge_id,
            "knowledge_base_id": graph_chunk.knowledge_base_id,
        }

        with (
            patch("personal_knowledge_base.search._fts_ranked", return_value=[]),
            patch("personal_knowledge_base.search._vector_recall", return_value=[]),
            patch("personal_knowledge_base.search.expand_query", return_value=[]),
            patch("personal_knowledge_base.graph_rag.graph_search_results", return_value=[graph_result]),
            patch("personal_knowledge_base.graph_rag.expand_relation_context", return_value=[]),
        ):
            results = hybrid_search(self.tenant.id, [self.kb.id], "graph", top_k=1)

        self.assertEqual(results[0]["retrieval_path"], "graph")
        self.assertEqual(results[0]["content"], graph_chunk.content)

    def test_mixed_graph_result_merges_into_mmr_noop_pool_without_reordering_documents(self):
        documents = [
            Chunk.objects.create(
                tenant=self.tenant,
                knowledge_base=self.kb,
                knowledge=self.chunk.knowledge,
                content=(f"shared retrieval evidence item document{index} " * 12).strip(),
                chunk_index=100 + index,
            )
            for index in range(3)
        ]
        graph_chunk = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content=("shared retrieval evidence item graphresult " * 12).strip(),
            chunk_index=103,
        )
        graph_result = {
            "chunk_id": graph_chunk.id,
            "id": graph_chunk.id,
            "content": graph_chunk.content,
            "score": 1.0,
            "chunk_type": "text",
            "knowledge_id": graph_chunk.knowledge_id,
            "knowledge_base_id": graph_chunk.knowledge_base_id,
        }

        def equal_rerank(_query, candidates, **_kwargs):
            return [{**candidate, "score": 1.0, "rerank_score": 1.0} for candidate in candidates]

        with (
            patch("personal_knowledge_base.search._fts_ranked", return_value=[item.id for item in documents]),
            patch("personal_knowledge_base.search._vector_recall", return_value=[]),
            patch("personal_knowledge_base.model_providers.active_rerank_config", return_value={"model": "test"}),
            patch("personal_knowledge_base.model_providers.rerank", side_effect=equal_rerank),
            patch("personal_knowledge_base.graph_rag.graph_search_results", return_value=[graph_result]),
            patch("personal_knowledge_base.graph_rag.expand_relation_context", return_value=[]),
        ):
            results = hybrid_search(self.tenant.id, [self.kb.id], "evidence", top_k=3)

        self.assertEqual(
            [item["chunk_id"] for item in results],
            [documents[0].id, graph_chunk.id, documents[1].id],
        )

    def test_mixed_graph_result_merges_into_active_mmr_pool_without_reordering_documents(self):
        shared_tokens = "alpha bravo charlie delta echo foxtrot golf hotel"
        documents = [
            Chunk.objects.create(
                tenant=self.tenant,
                knowledge_base=self.kb,
                knowledge=self.chunk.knowledge,
                content=(
                    f"{shared_tokens} document{index} individual{index} marker{index} " * 20
                    if index < 2
                    else f"unique{index} retrieval diversity evidence " * 20
                ),
                chunk_index=110 + index,
            )
            for index in range(7)
        ]
        graph_chunk = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=self.chunk.knowledge,
            content="graph retrieval attribution evidence " * 20,
            chunk_index=117,
        )
        graph_result = {
            "chunk_id": graph_chunk.id,
            "id": graph_chunk.id,
            "content": graph_chunk.content,
            "score": 0.955,
            "chunk_type": "text",
            "knowledge_id": graph_chunk.knowledge_id,
            "knowledge_base_id": graph_chunk.knowledge_base_id,
        }

        def ranked_for_relevance(_query, candidates, **_kwargs):
            return [
                {**candidate, "score": 0.99 - index * 0.01, "rerank_score": 0.99 - index * 0.01}
                for index, candidate in enumerate(candidates)
            ]

        with (
            patch("personal_knowledge_base.search._fts_ranked", return_value=[item.id for item in documents]),
            patch("personal_knowledge_base.search._vector_recall", return_value=[]),
            patch("personal_knowledge_base.model_providers.active_rerank_config", return_value={"model": "test"}),
            patch("personal_knowledge_base.model_providers.rerank", side_effect=ranked_for_relevance),
            patch("personal_knowledge_base.graph_rag.graph_search_results", return_value=[graph_result]),
            patch("personal_knowledge_base.graph_rag.expand_relation_context", return_value=[]),
        ):
            results = hybrid_search(self.tenant.id, [self.kb.id], "evidence", top_k=3)

        self.assertEqual(
            [item["chunk_id"] for item in results],
            [documents[0].id, graph_chunk.id, documents[1].id],
        )
        self.assertEqual([results[0]["final_rank"], results[2]["final_rank"]], [1, 2])

    def test_content_overlap_graph_duplicate_keeps_reranked_parent_document_and_graph_provenance(self):
        cases = (
            ("exact", "exact graph document overlap evidence", "exact graph document overlap evidence", "supports"),
            (
                "near",
                "alpha bravo charlie delta echo foxtrot golf hotel",
                "alpha bravo charlie delta echo foxtrot golf india",
                "near_supports",
            ),
        )
        for index, (name, document_content, graph_content, relation_type) in enumerate(cases):
            with self.subTest(overlap=name):
                parent = Chunk.objects.create(
                    tenant=self.tenant,
                    knowledge_base=self.kb,
                    knowledge=self.chunk.knowledge,
                    content=document_content,
                    chunk_index=120 + index * 10,
                    chunk_type="parent_text",
                    is_enabled=False,
                    start_at=0,
                    end_at=len(document_content),
                )
                child = Chunk.objects.create(
                    tenant=self.tenant,
                    knowledge_base=self.kb,
                    knowledge=self.chunk.knowledge,
                    content=document_content,
                    chunk_index=121 + index * 10,
                    context_parent_id=parent.id,
                    start_at=0,
                    end_at=len(document_content),
                )
                graph_chunk = Chunk.objects.create(
                    tenant=self.tenant,
                    knowledge_base=self.kb,
                    knowledge=self.chunk.knowledge,
                    content=graph_content,
                    chunk_index=122 + index * 10,
                )
                graph_result = {
                    "chunk_id": graph_chunk.id,
                    "id": graph_chunk.id,
                    "content": graph_chunk.content,
                    "score": 99.0,
                    "chunk_type": "text",
                    "knowledge_id": graph_chunk.knowledge_id,
                    "knowledge_base_id": graph_chunk.knowledge_base_id,
                    "relation_type": relation_type,
                }

                with (
                    patch("personal_knowledge_base.search._fts_ranked", return_value=[child.id]),
                    patch("personal_knowledge_base.search._vector_recall", return_value=[]),
                    patch("personal_knowledge_base.search.expand_query", return_value=[]),
                    patch("personal_knowledge_base.model_providers.active_rerank_config", return_value={"model": "test"}),
                    patch(
                        "personal_knowledge_base.model_providers.rerank",
                        side_effect=lambda _query, candidates, **_kwargs: [
                            {**candidates[0], "score": 0.5, "rerank_score": 0.5}
                        ],
                    ),
                    patch("personal_knowledge_base.graph_rag.graph_search_results", return_value=[graph_result]),
                    patch("personal_knowledge_base.graph_rag.expand_relation_context", return_value=[]),
                ):
                    results = hybrid_search(self.tenant.id, [self.kb.id], "evidence", top_k=2)

                self.assertEqual(len(results), 1)
                self.assertEqual(results[0]["chunk_id"], child.id)
                self.assertEqual(results[0]["final_rank"], 1)
                self.assertEqual(results[0]["parent_chunk_id"], parent.id)
                self.assertEqual(results[0]["matched_child_ids"], [child.id])
                self.assertIn("graph", results[0]["match_sources"])
                self.assertEqual(results[0]["graph_provenance"][0]["chunk_id"], graph_chunk.id)
                self.assertEqual(results[0]["graph_provenance"][0]["relation_type"], relation_type)

    def test_public_search_does_not_neighbor_expand_media_results(self):
        for index, chunk_type in enumerate(("image_ocr", "image_caption")):
            with self.subTest(chunk_type=chunk_type):
                media_knowledge = Knowledge.objects.create(
                    tenant=self.tenant,
                    knowledge_base=self.kb,
                    title=f"media-{chunk_type}",
                )
                media = Chunk.objects.create(
                    tenant=self.tenant,
                    knowledge_base=self.kb,
                    knowledge=media_knowledge,
                    content=f"{chunk_type} evidence",
                    chunk_index=80 + index * 10,
                    chunk_type=chunk_type,
                )
                Chunk.objects.create(
                    tenant=self.tenant,
                    knowledge_base=self.kb,
                    knowledge=media_knowledge,
                    content=f"unrelated {chunk_type} neighbor",
                    chunk_index=81 + index * 10,
                )

                with (
                    patch("personal_knowledge_base.search._fts_ranked", return_value=[media.id]),
                    patch("personal_knowledge_base.search._vector_recall", return_value=[]),
                    patch("personal_knowledge_base.search.expand_query", return_value=[]),
                    patch("personal_knowledge_base.graph_rag.graph_search_results", return_value=[]),
                    patch("personal_knowledge_base.graph_rag.expand_relation_context", return_value=[]),
                ):
                    results = hybrid_search(self.tenant.id, [self.kb.id], "media", top_k=1)

                self.assertEqual(results[0]["chunk_id"], media.id)
                self.assertEqual(results[0]["content"], media.content)


@ENV_OFF
@AUTO_SETUP_ENABLED
class HybridSearchApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        resp = self.client.post("/api/v1/auth/auto-setup", content_type="application/json")
        self.assertEqual(resp.status_code, 201)
        self.tenant = Tenant.objects.first()
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {resp.json()['data']['token']}"}
        kb_resp = self.client.post(
            "/api/v1/knowledge-bases", data=json.dumps({"name": "api-kb"}),
            content_type="application/json", **self.headers,
        )
        self.kb = KnowledgeBase.objects.get(id=kb_resp.json()["data"]["id"])
        knowledge = Knowledge.objects.create(tenant=self.tenant, knowledge_base=self.kb, title="t", embedding_model_id="")
        chunk = Chunk.objects.create(
            tenant=self.tenant, knowledge_base=self.kb, knowledge=knowledge,
            content="Python Web 框架", chunk_index=0,
        )
        index_chunk(chunk)

    def test_endpoint_returns_retrieval_meta(self):
        resp = self.client.post(
            f"/api/v1/knowledge-bases/{self.kb.id}/hybrid-search",
            data=json.dumps({"query": "Python 框架", "top_k": 3, "rrf_k": 60}),
            content_type="application/json", **self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertIn("retrieval", data)
        self.assertIn("degradations", data["retrieval"])
        self.assertEqual(data["candidate_params"]["rrf_k"], 60)
        self.assertIn("latency_ms", data["observability"])
