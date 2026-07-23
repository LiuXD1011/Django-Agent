"""Contract coverage for deterministic adaptive-chunking evaluation."""

import hashlib
import json
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import Client, TestCase, override_settings

from .chunking_eval import (
    SourceEvidence,
    _EvaluationChunk,
    _metrics_for_query,
    evaluate_release_gates,
    overlaps_evidence,
    run_chunking_comparison,
)
from .chunking import ChunkingConfig
from .document_processing import semantic_chunking_inputs
from .models import Knowledge, KnowledgeBase, SemanticChunkCache, Tenant


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

        with self.subTest(case="deduplicated parent contexts define all relevance metrics"):
            evidence = [SourceEvidence("knowledge-1", 60, 70)]
            parent_context = {
                "knowledge_id": "knowledge-1",
                "context_content": "returned parent context",
                "context_start_at": 0,
                "context_end_at": 100,
                "context_header": "Parent",
            }
            metrics_for_parent = _metrics_for_query(
                [
                    _EvaluationChunk(
                        start_at=0,
                        end_at=10,
                        search_content="winning child",
                        **parent_context,
                    ),
                    _EvaluationChunk(
                        start_at=60,
                        end_at=70,
                        search_content="lower-ranked evidence child",
                        **parent_context,
                    ),
                ],
                evidence,
            )
            self.assertEqual(metrics_for_parent["returned"], 1)
            self.assertEqual(metrics_for_parent["mrr_at_10"], 1.0)
            self.assertEqual(metrics_for_parent["recall_at_20"], 1.0)
            self.assertEqual(metrics_for_parent["context_precision"], 1.0)

        with self.subTest(case="semantic setup failures are logged without leaking to callers"):
            knowledge = SimpleNamespace(tenant=SimpleNamespace(pk="tenant-setup"), embedding_model_id="embedding-42")
            with patch(
                "personal_knowledge_base.document_processing.embedding_signature",
                side_effect=RuntimeError("configuration backend secret detail"),
            ), self.assertLogs("personal_knowledge_base.document_processing", level="ERROR") as setup_logs:
                setup_options = semantic_chunking_inputs(knowledge, ChunkingConfig(strategy="semantic"))
            self.assertEqual(setup_options, {"semantic_setup_error": "semantic_setup_error:RuntimeError"})
            self.assertIn("configuration backend secret detail", "\n".join(setup_logs.output))
            self.assertNotIn("configuration backend secret detail", json.dumps(setup_options))

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

            for duration, index_bytes in ((0.0, 100), (-1.0, 100), (100.0, 0), (100.0, -1)):
                invalid_resources = evaluate_release_gates(
                    {
                        "fixed_window": metrics(0.10),
                        "recursive": metrics(0.10),
                        "auto_parent_child": metrics(0.105, duration=duration, index_bytes=index_bytes),
                        "semantic_parent_child": metrics(0.10815, duration=0.0, index_bytes=0),
                    }
                )
                self.assertFalse(invalid_resources["semantic_parent_child"]["promotion_eligible"])
            invalid_relevance = evaluate_release_gates(
                {
                    "fixed_window": metrics(0.10, recall=-0.1),
                    "recursive": metrics(0.10),
                    "auto_parent_child": metrics(0.105),
                    "semantic_parent_child": metrics(0.10815),
                }
            )
            self.assertFalse(invalid_relevance["auto_parent_child"]["pass"])

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

            malformed = client.post(
                "/api/v1/rag-eval/chunking",
                data=b'{"dataset": [',
                content_type="application/json",
                **headers,
            )
            self.assertEqual(malformed.status_code, 400)
            self.assertEqual(malformed.json()["error"]["code"], "invalid_json")

            with patch(
                "personal_knowledge_base.chunking_eval.run_chunking_comparison",
                side_effect=RuntimeError("provider-secret-detail"),
            ):
                unexpected = client.post(
                    "/api/v1/rag-eval/chunking",
                    data=json.dumps({}),
                    content_type="application/json",
                    **headers,
                )
            self.assertEqual(unexpected.status_code, 500)
            self.assertNotIn("provider-secret-detail", unexpected.content.decode())

        with self.subTest(case="all strategies use an isolated deterministic index and cache"):
            source = "\n\n".join(
                [
                    "# Retrieval\noriginneedle alpha configuration detail. "
                    + (("needle alpha configuration detail. " * 30) + "stable evidence marker."),
                    "# Operations\n" + ("deployment health rollback procedure. " * 28),
                    "# Security\n" + ("credential rotation audit policy. " * 28),
                    "# Appendix\n" + ("reference glossary ownership schedule. " * 28),
                ]
            )
            source_bytes = source.encode("utf-8")
            version = hashlib.sha256(source_bytes).hexdigest()
            evidence_text = "originneedle alpha configuration detail"
            evidence_start = source.index(evidence_text)
            tenant = Tenant.objects.create(name="evaluation tenant", api_key="evaluation-key")
            knowledge_base = KnowledgeBase.objects.create(tenant=tenant, name="evaluation base")
            model_config = {
                "model_id": "embedding-2d",
                "provider": "test-provider",
                "base_url": "https://embedding.invalid/v1",
                "api_key": "not-used",
                "model": "controlled",
                "dimension": 2,
            }

            def controlled_embedding(_tenant, texts, *, model_id):
                self.assertEqual(_tenant, tenant)
                self.assertEqual(model_id, "embedding-2d")
                return [
                    [0.0, 1.0] if "Security" in text or "credential" in text else [1.0, 0.01]
                    for text in texts
                ]

            with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
                file_path = default_storage.save("eval/versioned-source.md", ContentFile(source_bytes))
                knowledge = Knowledge.objects.create(
                    tenant=tenant,
                    knowledge_base=knowledge_base,
                    type="file",
                    title="Versioned source",
                    source="versioned-source.md",
                    file_name="versioned-source.md",
                    file_path=file_path,
                    file_hash=version,
                    embedding_model_id="embedding-2d",
                )
                dataset = [
                    {
                        "query": "originneedle",
                        "documents": [{"knowledge_id": knowledge.id, "version": version}],
                        "evidence": [
                            {
                                "knowledge_id": knowledge.id,
                                "source_start": evidence_start,
                                "source_end": evidence_start + len(evidence_text),
                                "answer_evidence": evidence_text,
                            }
                        ],
                    },
                    {
                        "query": "term-that-does-not-exist",
                        "documents": [{"knowledge_id": knowledge.id, "version": version}],
                        "evidence": [
                            {
                                "knowledge_id": knowledge.id,
                                "source_start": evidence_start,
                                "source_end": evidence_start + len(evidence_text),
                            }
                        ],
                    },
                ]

                with patch(
                    "personal_knowledge_base.chunking_eval.active_embedding_config",
                    return_value=model_config,
                ), patch(
                    "personal_knowledge_base.document_processing.active_embedding_config",
                    return_value=model_config,
                ), patch(
                    "personal_knowledge_base.document_processing.embedding",
                    side_effect=controlled_embedding,
                ) as embedding_call, patch.object(
                    SemanticChunkCache.objects,
                    "filter",
                    side_effect=AssertionError("evaluation read the persistent semantic cache"),
                ), patch.object(
                    SemanticChunkCache.objects,
                    "get_or_create",
                    side_effect=AssertionError("evaluation wrote the persistent semantic cache"),
                ):
                    result = run_chunking_comparison(tenant.id, dataset=dataset)

                self.assertEqual(result["dataset_status"], "verified")
                self.assertEqual(set(result["strategies"]), {
                    "fixed_window",
                    "recursive",
                    "auto_parent_child",
                    "semantic_parent_child",
                })
                self.assertGreater(embedding_call.call_count, 0)
                self.assertEqual(SemanticChunkCache.objects.count(), 0)
                json.dumps(result, allow_nan=False)

                metric_shapes = set()
                for strategy, strategy_metrics in result["strategies"].items():
                    self.assertGreater(strategy_metrics["index_bytes"], 0, strategy)
                    self.assertGreater(strategy_metrics["searchable_chunk_count"], 0, strategy)
                    self.assertEqual(strategy_metrics["questions"], 2, strategy)
                    self.assertGreater(strategy_metrics["per_question"][0]["mrr_at_10"], 0.0, strategy)
                    self.assertGreater(strategy_metrics["per_question"][0]["recall_at_20"], 0.0, strategy)
                    self.assertEqual(strategy_metrics["per_question"][1]["returned"], 0, strategy)
                    self.assertEqual(strategy_metrics["per_question"][1]["returned_context_characters"], 0, strategy)
                    metric_shapes.add(
                        (
                            strategy_metrics["chunk_count"],
                            strategy_metrics["searchable_chunk_count"],
                            strategy_metrics["index_bytes"],
                        )
                    )
                self.assertGreaterEqual(len(metric_shapes), 3)
                self.assertEqual(
                    result["strategies"]["auto_parent_child"]["per_question"][0]["returned"],
                    1,
                )
                self.assertGreater(
                    result["strategies"]["auto_parent_child"]["per_question"][0]["returned_context_characters"],
                    len(evidence_text),
                )

                with default_storage.open(file_path, "wb") as stored_source:
                    stored_source.write(b"tampered evaluation bytes")
                byte_mismatch = run_chunking_comparison(tenant.id, dataset=dataset)
                self.assertEqual(byte_mismatch["dataset_status"], "unverified")
                self.assertFalse(byte_mismatch["pass"])
                self.assertEqual(
                    {reason["code"] for reason in byte_mismatch["reasons"]},
                    {"version_mismatch"},
                )
                self.assertNotIn(file_path, json.dumps(byte_mismatch))

                with default_storage.open(file_path, "wb") as stored_source:
                    stored_source.write(source_bytes)
                knowledge.file_hash = "f" * 64
                knowledge.save(update_fields=["file_hash", "updated_at"])
                stored_hash_mismatch = run_chunking_comparison(tenant.id, dataset=dataset)
                self.assertEqual(stored_hash_mismatch["dataset_status"], "unverified")
                self.assertEqual(
                    {reason["code"] for reason in stored_hash_mismatch["reasons"]},
                    {"version_mismatch"},
                )
                self.assertNotIn(file_path, json.dumps(stored_hash_mismatch))
                knowledge.file_hash = version
                knowledge.save(update_fields=["file_hash", "updated_at"])

                with patch(
                    "personal_knowledge_base.chunking_eval.active_embedding_config",
                    return_value=None,
                ):
                    unavailable = run_chunking_comparison(tenant.id, dataset=dataset)
                self.assertEqual(unavailable["dataset_status"], "unverified")
                self.assertIn("model_unavailable", {reason["code"] for reason in unavailable["reasons"]})

                with patch(
                    "personal_knowledge_base.chunking_eval.active_embedding_config",
                    return_value=model_config,
                ), patch(
                    "personal_knowledge_base.document_processing.active_embedding_config",
                    return_value=model_config,
                ), patch(
                    "personal_knowledge_base.document_processing.embedding",
                    side_effect=RuntimeError("embedding-provider-secret"),
                ), self.assertLogs("personal_knowledge_base.chunking_eval", level="ERROR") as provider_logs:
                    provider_failure = run_chunking_comparison(tenant.id, dataset=dataset)
                self.assertEqual(provider_failure["dataset_status"], "unverified")
                self.assertNotIn("embedding-provider-secret", json.dumps(provider_failure))
                self.assertIn("embedding-provider-secret", "\n".join(provider_logs.output))

                with patch(
                    "personal_knowledge_base.chunking_eval.parse_document",
                    side_effect=RuntimeError("parser-secret-detail"),
                ):
                    parser_failure = run_chunking_comparison(tenant.id, dataset=dataset)
                self.assertEqual(parser_failure["dataset_status"], "unverified")
                self.assertNotIn("parser-secret-detail", json.dumps(parser_failure))
