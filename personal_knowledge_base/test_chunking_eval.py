"""Contract coverage for deterministic adaptive-chunking evaluation."""

import json

from django.test import Client, TestCase, override_settings

from .chunking_eval import (
    SourceEvidence,
    evaluate_release_gates,
    overlaps_evidence,
    run_chunking_comparison,
)
from .models import Knowledge, KnowledgeBase, Tenant


class ChunkingEvaluationContractTests(TestCase):
    def test_source_span_relevance_and_evaluation_contract(self):
        def metrics(mrr, recall=0.5, precision=0.4, duration=100.0, index_bytes=100):
            return {
                "mrr_at_10": mrr,
                "recall_at_20": recall,
                "context_precision": precision,
                "processing_duration_ms": duration,
                "index_bytes": index_bytes,
            }

        with self.subTest(case="source spans remain relevant after rechunking"):
            relevant = SourceEvidence("knowledge-1", 100, 180, "optional answer evidence")
            self.assertTrue(
                overlaps_evidence(
                    {"knowledge_id": "knowledge-1", "start_at": 80, "end_at": 140},
                    relevant,
                )
            )
            self.assertFalse(
                overlaps_evidence(
                    {"knowledge_id": "knowledge-2", "start_at": 100, "end_at": 180},
                    relevant,
                )
            )

        with self.subTest(case="empty and template datasets cannot pass"):
            for dataset in (
                [],
                [{"query": "q", "documents": [], "evidence": []}],
            ):
                result = run_chunking_comparison(1, dataset=dataset)
                self.assertEqual(result["dataset_status"], "unverified")
                self.assertFalse(result["pass"])
            no_strategies = run_chunking_comparison(1, dataset=[], strategies=[])
            self.assertIn("insufficient_strategies", {reason["code"] for reason in no_strategies["reasons"]})

        with self.subTest(case="comparison gates use finite ratios and exact thresholds"):
            gates = evaluate_release_gates(
                {
                    "fixed_window": metrics(0.10),
                    "recursive": metrics(0.10),
                    "auto_parent_child": metrics(0.105),
                    "semantic_parent_child": metrics(0.10815, duration=200.0, index_bytes=200),
                }
            )
            self.assertTrue(gates["auto_parent_child"]["pass"])
            self.assertTrue(gates["semantic_parent_child"]["promotion_eligible"])
            zero_baseline = evaluate_release_gates(
                {
                    "fixed_window": metrics(0.0),
                    "recursive": metrics(0.0),
                    "auto_parent_child": metrics(1.0),
                    "semantic_parent_child": metrics(1.0),
                }
            )
            self.assertFalse(zero_baseline["auto_parent_child"]["pass"])

        with self.subTest(case="endpoint requires post auth and tenant-scoped documents"):
            client = Client()
            with override_settings(ALLOW_AUTO_SETUP=True):
                setup = client.post("/api/v1/auth/auto-setup", content_type="application/json")
            self.assertEqual(setup.status_code, 201)
            headers = {"HTTP_AUTHORIZATION": f"Bearer {setup.json()['data']['token']}"}
            self.assertEqual(
                client.post("/api/v1/rag-eval/chunking", data=json.dumps({}), content_type="application/json").status_code,
                401,
            )
            self.assertEqual(client.get("/api/v1/rag-eval/chunking", **headers).status_code, 405)

            other_tenant = Tenant.objects.create(name="other evaluation tenant", api_key="other-evaluation-key")
            other_base = KnowledgeBase.objects.create(tenant=other_tenant, name="other evaluation base")
            foreign_document = Knowledge.objects.create(
                tenant=other_tenant,
                knowledge_base=other_base,
                type="file",
                title="private",
                source="private.md",
                file_name="private.md",
                file_hash="foreign-version",
            )
            response = client.post(
                "/api/v1/rag-eval/chunking",
                data=json.dumps(
                    {
                        "dataset": [
                            {
                                "query": "private",
                                "documents": [{"knowledge_id": foreign_document.id, "version": "foreign-version"}],
                                "evidence": [
                                    {"knowledge_id": foreign_document.id, "source_start": 0, "source_end": 7}
                                ],
                            }
                        ]
                    }
                ),
                content_type="application/json",
                **headers,
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()["data"]
            self.assertEqual(payload["dataset_status"], "unverified")
            self.assertFalse(payload["pass"])
            self.assertIn("unavailable_document", {reason["code"] for reason in payload["reasons"]})
