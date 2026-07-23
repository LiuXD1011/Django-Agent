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
from .search import _hydrate_candidates, _vector_ranked, ensure_search_tables, hybrid_search_ex, index_chunk, pack_embedding, rrf_fuse


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

        result = _hydrate_candidates(entries)

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
