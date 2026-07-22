"""检索评估（MRR@10 / Recall@20）测试：指标计算、提升阈值判定、端点契约。"""

import json
from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from .retrieval_eval import mrr_at_k, recall_at_k, run_retrieval_comparison


class RetrievalMetricTests(TestCase):
    def test_mrr_and_recall_math(self):
        self.assertEqual(mrr_at_k(["a", "b", "c"], {"b"}, 10), 0.5)
        self.assertEqual(mrr_at_k(["a", "b"], {"z"}, 10), 0.0)
        self.assertAlmostEqual(recall_at_k(["a", "b", "c"], {"a", "c", "z"}, 3), 2 / 3)
        self.assertEqual(recall_at_k([], {"a"}, 5), 0.0)


class RetrievalComparisonTests(TestCase):
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
        self.assertFalse(result["pass"])
        self.assertEqual(result["per_question"], [])
        hs.assert_not_called()
        baseline.assert_not_called()

    def test_empty_dataset_returns_template_status(self):
        result = run_retrieval_comparison(1, dataset=[])
        self.assertEqual(result["dataset_status"], "template")

    def test_mixed_dataset_uses_only_real_annotations(self):
        # 只要有一条真实标注就算正常数据集，正常计算
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
        self.assertNotIn("dataset_status", result)
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

    def test_endpoint_contract(self):
        resp = self.client.post(
            "/api/v1/rag-eval/retrieval",
            data=json.dumps({"dataset": [{"query": "q", "kb_ids": [], "relevant_chunk_ids": ["a"]}]}),
            content_type="application/json", **self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        for key in ("mrr_new", "mrr_baseline", "recall_new", "recall_baseline", "delta_pct", "pass"):
            self.assertIn(key, data)
