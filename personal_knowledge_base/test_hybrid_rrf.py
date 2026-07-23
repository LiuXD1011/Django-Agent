"""BGE-M3 双路召回 + RRF + BGE-Reranker 检索链测试。

覆盖：RRF 公式与双路命中奖励、未配置时的显式降级、维度不匹配硬报错、检索端点 API 契约。
"""

import json
from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from .model_providers import EmbeddingDimensionMismatchError
from .models import Chunk, Knowledge, KnowledgeBase, Tenant
from .search import _hydrate_candidates, hybrid_search_ex, index_chunk, rrf_fuse


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
