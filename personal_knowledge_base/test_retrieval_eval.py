"""检索评估（MRR@10 / Recall@20）测试：指标计算、提升阈值判定、端点契约。"""

import json
from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from .models import Chunk, Knowledge, KnowledgeBase, Tenant
from .retrieval_eval import hit_at_k, mrr_at_k, recall_at_k, run_retrieval_comparison


class RetrievalMetricTests(TestCase):
    def test_mrr_and_recall_math(self):
        self.assertEqual(hit_at_k(["a", "b", "c"], {"b"}, 10), 1.0)
        self.assertEqual(hit_at_k(["a", "b"], {"z"}, 10), 0.0)
        self.assertEqual(mrr_at_k(["a", "b", "c"], {"b"}, 10), 0.5)
        self.assertEqual(mrr_at_k(["a", "b"], {"z"}, 10), 0.0)
        self.assertAlmostEqual(recall_at_k(["a", "b", "c"], {"a", "c", "z"}, 3), 2 / 3)
        self.assertEqual(recall_at_k([], {"a"}, 5), 0.0)


class RetrievalComparisonTests(TestCase):
    def test_v2_dataset_uses_source_spans_and_reports_hit_at_10(self):
        tenant = Tenant.objects.create(name="Eval", api_key="eval-key")
        knowledge_base = KnowledgeBase.objects.create(name="Eval KB", tenant=tenant)
        knowledge = Knowledge.objects.create(
            tenant=tenant,
            knowledge_base=knowledge_base,
            type="file",
            title="Architecture",
            source="upload",
            file_hash="sha256:architecture-v1",
        )
        relevant = Chunk.objects.create(
            tenant=tenant,
            knowledge_base=knowledge_base,
            knowledge=knowledge,
            content="retrieval evidence",
            chunk_index=0,
            start_at=20,
            end_at=80,
        )
        unrelated = Chunk.objects.create(
            tenant=tenant,
            knowledge_base=knowledge_base,
            knowledge=knowledge,
            content="unrelated",
            chunk_index=1,
            start_at=100,
            end_at=140,
        )
        dataset = [{
            "query": "How does retrieval work?",
            "documents": [{"knowledge_id": knowledge.id, "file_hash": knowledge.file_hash}],
            "evidence": [{"knowledge_id": knowledge.id, "source_start": 30, "source_end": 60}],
        }]

        with patch(
            "personal_knowledge_base.retrieval_eval.hybrid_search_ex",
            return_value=([{"chunk_id": relevant.id}], {"rrf_k": 60, "embedding_model": "bge-m3", "rerank_model": "bge-reranker"}),
        ), patch(
            "personal_knowledge_base.retrieval_eval._baseline_score_addition_search",
            return_value=[unrelated.id],
        ):
            result = run_retrieval_comparison(tenant.id, dataset=dataset)

        self.assertTrue(result["verified"])
        self.assertEqual(result["dataset_format"], "retrieval_v2")
        self.assertEqual(result["hit_at_10_new"], 1.0)
        self.assertEqual(result["hit_at_10_baseline"], 0.0)
        self.assertEqual(result["pipeline"]["embedding_models"], ["bge-m3"])
        self.assertEqual(result["pipeline"]["rerank_models"], ["bge-reranker"])

    def test_pass_threshold_on_stubs(self):
        dataset = [{"query": "q", "kb_ids": [], "relevant_chunk_ids": ["a", "b"]}]
        # 新管线把相关项排第一；基线完全没命中
        with patch(
            "personal_knowledge_base.retrieval_eval.hybrid_search_ex",
            return_value=([{"chunk_id": "a"}, {"chunk_id": "b"}], {"degradations": []}),
        ), patch(
            "personal_knowledge_base.retrieval_eval._baseline_score_addition_search",
            return_value=["x", "y"],
        ):
            result = run_retrieval_comparison(1, dataset=dataset)
        self.assertGreaterEqual(result["delta_pct"], 5.0)
        self.assertTrue(result["pass"])
        self.assertEqual(result["questions"], 1)


class RetrievalTemplateDatasetTests(TestCase):
    def test_template_dataset_returns_template_status_without_computing_metrics(self):
        # 全是占位符 / 空标注：必须返回 dataset_status="template"，且不调用检索
        with patch("personal_knowledge_base.retrieval_eval.hybrid_search_ex") as hs, patch(
            "personal_knowledge_base.retrieval_eval._baseline_score_addition_search"
        ) as baseline:
            result = run_retrieval_comparison(
                1,
                dataset=[{"query": "q", "kb_ids": [], "relevant_chunk_ids": ["<chunk-id-1>", "<chunk-id-2>"]}],
            )
        self.assertEqual(result["dataset_status"], "template")
        self.assertFalse(result["verified"])
        self.assertFalse(result["pass"])
        self.assertIsNone(result["mrr_new"])
        self.assertIsNone(result["hit_at_10_new"])
        self.assertTrue(result["reasons"])
        self.assertEqual(result["per_question"], [])
        hs.assert_not_called()
        baseline.assert_not_called()

    def test_empty_dataset_returns_template_status(self):
        result = run_retrieval_comparison(1, dataset=[])
        self.assertEqual(result["dataset_status"], "template")

    def test_mixed_template_and_real_annotations_remain_unverified(self):
        with patch(
            "personal_knowledge_base.retrieval_eval.hybrid_search_ex",
            return_value=([{"chunk_id": "real"}], {"degradations": []}),
        ), patch(
            "personal_knowledge_base.retrieval_eval._baseline_score_addition_search",
            return_value=["other"],
        ):
            result = run_retrieval_comparison(
                1,
                dataset=[
                    {"query": "tpl", "kb_ids": [], "relevant_chunk_ids": ["<chunk-id>"]},
                    {"query": "real", "kb_ids": [], "relevant_chunk_ids": ["real"]},
                ],
            )
        self.assertEqual(result["dataset_status"], "template")
        self.assertFalse(result["verified"])
        self.assertIsNone(result["mrr_new"])
        self.assertEqual(result["questions"], 2)


@override_settings(ALLOW_AUTO_SETUP=True)
class RetrievalEvalEndpointTests(TestCase):
    def setUp(self):
        self.client = Client()
        resp = self.client.post("/api/v1/auth/auto-setup", content_type="application/json")
        self.assertEqual(resp.status_code, 201)
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {resp.json()['data']['token']}"}

    def test_endpoint_without_dataset_returns_template_status(self):
        # 不传 dataset 时加载默认模板，端点应明确返回 template 状态而非误导性的 pass=false
        resp = self.client.post(
            "/api/v1/rag-eval/retrieval",
            data=json.dumps({}),
            content_type="application/json", **self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["dataset_status"], "template")
        self.assertFalse(data["verified"])
        self.assertIn("run_id", data)
        self.assertIn("dataset", data)
        report = self.client.get(data["report_url"], **self.headers)
        self.assertEqual(report.status_code, 200)

    def test_endpoint_contract(self):
        resp = self.client.post(
            "/api/v1/rag-eval/retrieval",
            data=json.dumps({"dataset": []}),
            content_type="application/json", **self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        for key in ("hit_at_10_new", "mrr_new", "mrr_baseline", "recall_new", "recall_baseline", "delta_pct", "pass", "provenance"):
            self.assertIn(key, data)
