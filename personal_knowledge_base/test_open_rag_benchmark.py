import hashlib
import json
import sqlite3
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import Client, SimpleTestCase, TestCase, override_settings

from . import open_rag_benchmark as open_rag_module
from .eval_dataset_registry import DatasetNotFoundError, get_dataset_spec, registered_dataset_ids
from .models import AuthToken, GenericResource, Knowledge, KnowledgeBase, TaskRecord, Tenant, User
from .open_rag_benchmark import (
    OpenRagDatasetError,
    _build_index,
    _bounded_contexts,
    _cache_artifacts_verified,
    _embed_batches,
    _git_blob_oid,
    _public_chunks,
    _retrieval_metrics,
    open_dataset_status,
    prepare_open_rag_dataset,
    run_open_rag_chunking,
    run_open_rag_retrieval,
    sample_open_rag_questions,
)


class OpenRagRegistryTests(SimpleTestCase):
    def test_answer_contexts_respect_total_character_budget(self):
        contexts = _bounded_contexts([
            {"content": "a" * 3000},
            {"content": "b" * 3000},
            {"content": "c" * 3000},
            {"content": "d" * 3000},
        ])

        self.assertLessEqual(sum(len(context) for context in contexts), 6000)
        self.assertEqual([len(context) for context in contexts], [2000, 2000, 2000])

    def test_registry_contains_only_open_rag_benchmark(self):
        self.assertEqual(
            registered_dataset_ids(),
            ("open_rag_benchmark_180", "open_rag_benchmark_full"),
        )
        subset = get_dataset_spec("open_rag_benchmark_180", "arxiv-v1")
        legacy_subset = get_dataset_spec("open_rag_benchmark_100", "arxiv-v1")
        full = get_dataset_spec("open_rag_benchmark_full", "arxiv-v1")
        alias = get_dataset_spec("open_rag_benchmark", "arxiv-v1")

        self.assertEqual(subset.version, "arxiv-v1")
        self.assertEqual(subset.license, "CC-BY-NC-4.0")
        self.assertEqual(subset.expected_queries, 180)
        self.assertEqual(legacy_subset, subset)
        self.assertEqual(full.expected_queries, 3045)
        self.assertEqual(alias, full)
        self.assertEqual(subset.cache_path, full.cache_path)
        self.assertEqual(subset.artifact_manifest_sha256, full.artifact_manifest_sha256)
        self.assertEqual(subset.expected_documents, 1000)
        self.assertEqual(len(subset.query_ids), 180)
        self.assertEqual(len(set(subset.query_ids)), 180)
        self.assertEqual(subset.selection_seed, 20260819)

    def test_removed_public_datasets_are_unknown(self):
        for dataset_id in ("ragas", "squad", "hotpotqa"):
            with self.assertRaises(DatasetNotFoundError):
                get_dataset_spec(dataset_id, "v1")

    def test_qrel_metrics_use_exact_document_and_section_identity(self):
        results = [
            {"doc_id": "other", "section_id": "1"},
            {"doc_id": "doc-1", "section_id": "2"},
        ]
        self.assertEqual(_retrieval_metrics(results, {"doc_id": "doc-1", "section_id": 2}), (1.0, 0.5, 1.0))
        self.assertEqual(_retrieval_metrics(results, {"doc_id": "doc-1", "section_id": 1}), (0.0, 0.0, 0.0))

    def test_fixed_and_recursive_chunking_are_distinct_read_only_strategies(self):
        source = ("First sentence. " * 45) + "\n\n" + ("Second sentence. " * 45)
        document = {"source": source, "sections": {"1": (0, len(source))}, "section_blocks": [source], "title": ""}
        fixed = _public_chunks(document, "fixed_window")
        recursive = _public_chunks(document, "recursive")
        self.assertTrue(fixed)
        self.assertTrue(recursive)
        self.assertNotEqual([(item["start"], item["end"]) for item in fixed], [(item["start"], item["end"]) for item in recursive])

    @patch("personal_knowledge_base.open_rag_benchmark._payloads")
    def test_public_question_sampling_is_deterministic_and_capped(self, payloads):
        queries = {str(index): {"query": f"query-{index}"} for index in range(150)}
        qrels = {str(index): {"doc_id": "doc", "section_id": index} for index in range(150)}
        answers = {str(index): f"answer-{index}" for index in range(150)}
        payloads.return_value = queries, qrels, answers
        spec = get_dataset_spec("open_rag_benchmark", "arxiv-v1")

        first = sample_open_rag_questions(spec, 1000, 42)
        second = sample_open_rag_questions(spec, 1000, 42)

        self.assertEqual(len(first), 150)
        self.assertEqual(first, second)

    @patch("personal_knowledge_base.open_rag_benchmark._payloads")
    def test_subset_sampling_never_escapes_immutable_query_ids(self, payloads):
        spec = get_dataset_spec("open_rag_benchmark_180", "arxiv-v1")
        all_ids = [*spec.query_ids, "outside-subset"]
        queries = {query_id: {"query": query_id} for query_id in all_ids}
        qrels = {query_id: {"doc_id": "doc", "section_id": 1} for query_id in all_ids}
        answers = {query_id: query_id for query_id in all_ids}
        payloads.return_value = queries, qrels, answers

        first = sample_open_rag_questions(spec, 180, 1)
        second = sample_open_rag_questions(spec, 180, 999)

        self.assertEqual({item["query_id"] for item in first}, set(spec.query_ids))
        self.assertEqual({item["query_id"] for item in second}, set(spec.query_ids))
        self.assertNotIn("outside-subset", {item["query_id"] for item in first})

    @patch("personal_knowledge_base.open_rag_benchmark._active_task", return_value=None)
    @patch("personal_knowledge_base.open_rag_benchmark.cache.get", return_value=None)
    def test_manifest_drift_marks_prepared_cache_stale(self, _cache_get, _active_task):
        with tempfile.TemporaryDirectory() as directory:
            spec = replace(get_dataset_spec("open_rag_benchmark", "arxiv-v1"), cache_path=Path(directory))
            Path(directory, "index.sqlite3").touch()
            Path(directory, "state.json").write_text(json.dumps({
                "status": "ready",
                "revision": "stale-revision",
                "manifest_sha256": spec.sha256,
            }), encoding="utf-8")

            status = open_dataset_status(spec)

            self.assertEqual(status["status"], "stale")
            self.assertFalse(status["ready"])
            self.assertFalse(status["verified"])

    @patch("personal_knowledge_base.open_rag_benchmark._latest_task")
    @patch(
        "personal_knowledge_base.open_rag_benchmark._active_task",
        return_value=SimpleNamespace(id="stale-prepare", status="pending"),
    )
    @patch("personal_knowledge_base.open_rag_benchmark._cache_artifacts_verified", return_value=True)
    @patch("personal_knowledge_base.open_rag_benchmark.cache.get")
    def test_verified_artifacts_remain_ready_after_later_failed_attempt(
        self, cache_get, _verified, _active_task, latest_task
    ):
        cache_get.return_value = {
            "status": "failed",
            "progress": 0,
            "error": "later embedding attempt failed",
        }
        latest_task.return_value = SimpleNamespace(
            status="failed",
            error_message="later embedding attempt failed",
        )

        status = open_dataset_status(get_dataset_spec("open_rag_benchmark_full", "arxiv-v1"))

        self.assertEqual(status["status"], "ready")
        self.assertTrue(status["ready"])
        self.assertTrue(status["verified"])
        self.assertEqual(status["progress"], 1.0)
        self.assertEqual(status["error"], "")
        self.assertEqual(status["task_id"], "")

    @patch("personal_knowledge_base.open_rag_benchmark._latest_task", return_value=None)
    @patch("personal_knowledge_base.open_rag_benchmark._active_task", side_effect=RuntimeError("task table schema drift"))
    @patch("personal_knowledge_base.open_rag_benchmark._cache_artifacts_verified", return_value=True)
    @patch("personal_knowledge_base.open_rag_benchmark.cache.get", return_value={"status": "failed"})
    def test_verified_status_survives_unavailable_task_table(
        self, _cache_get, _verified, _active_task, _latest_task
    ):
        status = open_dataset_status(get_dataset_spec("open_rag_benchmark_full", "arxiv-v1"))

        self.assertEqual(status["status"], "ready")
        self.assertTrue(status["verified"])

    def test_corpus_file_uses_git_blob_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "document.json")
            path.write_bytes(b'{"id":"doc-1"}')
            self.assertEqual(_git_blob_oid(path), "0142219ac88729541a74d35368fcc4e9ec4e846b")

    @patch("personal_knowledge_base.model_providers.embedding")
    def test_embedding_batches_bound_each_input_and_request_payload(self, embedding):
        calls = []

        def fake_embedding(_tenant, texts):
            calls.append(list(texts))
            return [[float(index), 1.0] for index, _text in enumerate(texts, start=1)]

        embedding.side_effect = fake_embedding
        vectors = _embed_batches(
            None,
            ["a" * 30_000, "short"],
            {"batch_size": 32, "max_input_chars": 8_000, "max_batch_chars": 16_000},
        )

        self.assertEqual(len(vectors), 2)
        self.assertGreater(len(calls), 1)
        self.assertTrue(all(len(text) <= 8_000 for call in calls for text in call))
        self.assertTrue(all(sum(len(text) for text in call) <= 16_000 for call in calls))

    @patch("personal_knowledge_base.model_providers.embedding")
    def test_default_embedding_batch_budget_is_rate_limit_friendly(self, embedding):
        calls = []

        def fake_embedding(_tenant, texts):
            calls.append(list(texts))
            return [[1.0, 0.0] for _text in texts]

        embedding.side_effect = fake_embedding
        _embed_batches(None, ["a" * 8_000] * 32, {"batch_size": 32})

        self.assertGreater(len(calls), 1)
        self.assertTrue(all(sum(len(text) for text in call) <= 32_000 for call in calls))

    @patch("personal_knowledge_base.open_rag_benchmark.time.sleep")
    @patch("personal_knowledge_base.model_providers.embedding")
    def test_embedding_batches_retries_rate_limit_with_backoff(self, embedding, sleep):
        class RateLimited(Exception):
            status_code = 429

        embedding.side_effect = [RateLimited("TPM limit reached"), [[1.0, 0.0]]]

        vectors = _embed_batches(None, ["short"], {"batch_size": 1, "rate_limit_delay_seconds": 0.01})

        self.assertEqual(vectors, [[1.0, 0.0]])
        sleep.assert_called_once_with(0.01)

    @patch("personal_knowledge_base.open_rag_benchmark.time.sleep")
    @patch("personal_knowledge_base.model_providers.embedding")
    def test_embedding_rate_limit_honors_retry_after_header(self, embedding, sleep):
        class RateLimited(Exception):
            status_code = 429
            response = SimpleNamespace(headers={"Retry-After": "7"})

        embedding.side_effect = [RateLimited("TPM limit reached"), [[1.0, 0.0]]]

        vectors = _embed_batches(None, ["short"], {"batch_size": 1, "rate_limit_delay_seconds": 0.01})

        self.assertEqual(vectors, [[1.0, 0.0]])
        sleep.assert_called_once_with(7.0)

    @patch("personal_knowledge_base.open_rag_benchmark._embed_batches")
    def test_embedding_checkpoint_resumes_by_signature_and_content_hash(self, embed):
        self.assertTrue(hasattr(open_rag_module, "_load_or_embed_section_vectors"))
        load_or_embed = open_rag_module._load_or_embed_section_vectors
        embed.side_effect = [
            [[1.0, 0.0]],
            RuntimeError("upstream failed"),
            [[0.0, 1.0]],
        ]
        sections = [(1, "first"), (2, "second")]
        progress = []
        config = {"model": "embedding-model", "dimension": 2, "checkpoint_batch_size": 1}

        with tempfile.TemporaryDirectory() as directory:
            spec = replace(
                get_dataset_spec("open_rag_benchmark_full", "arxiv-v1"),
                cache_path=Path(directory),
            )
            with self.assertRaises(RuntimeError):
                load_or_embed(spec, sections, config, progress.append)

            vectors = load_or_embed(spec, sections, config, progress.append)

            checkpoint = sqlite3.connect(Path(directory, "embedding-checkpoint.sqlite3"))
            rows = checkpoint.execute(
                "SELECT model_signature, content_hash FROM embeddings ORDER BY content_hash"
            ).fetchall()
            checkpoint.close()

        self.assertEqual(vectors, [[1.0, 0.0], [0.0, 1.0]])
        self.assertEqual(embed.call_count, 3)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row[0] for row in rows}, {"embedding-model:2"})
        self.assertEqual(progress[-1], 1.0)

    @patch("personal_knowledge_base.model_providers.active_embedding_config")
    def test_prepared_cache_requires_vector_index_when_embedding_is_configured(self, active_embedding):
        active_embedding.return_value = {"model": "embedding-model", "dimension": 2}
        with tempfile.TemporaryDirectory() as directory:
            content = b"{}"
            digest = hashlib.sha256(content).hexdigest()
            spec = replace(
                get_dataset_spec("open_rag_benchmark", "arxiv-v1"),
                cache_path=Path(directory),
                files={name: digest for name in ("queries.json", "qrels.json", "answers.json", "pdf_urls.json")},
            )
            for name in spec.files:
                Path(directory, name).write_bytes(content)
            connection = sqlite3.connect(Path(directory, "index.sqlite3"))
            connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                [
                    ("revision", spec.revision),
                    ("manifest_sha256", spec.sha256),
                    ("vector_status", "unavailable"),
                    ("vector_reason", "embedding_index_failed:BadRequestError"),
                ],
            )
            connection.commit()
            connection.close()

            self.assertFalse(_cache_artifacts_verified(spec))

    @patch("personal_knowledge_base.model_providers.active_embedding_config", return_value=None)
    def test_unchanged_verified_index_skips_repeated_full_integrity_scan(self, _active_embedding):
        with tempfile.TemporaryDirectory() as directory:
            content = b"{}"
            digest = hashlib.sha256(content).hexdigest()
            spec = replace(
                get_dataset_spec("open_rag_benchmark", "arxiv-v1"),
                cache_path=Path(directory),
                files={name: digest for name in ("queries.json", "qrels.json", "answers.json", "pdf_urls.json")},
            )
            for name in spec.files:
                Path(directory, name).write_bytes(content)
            index_path = Path(directory, "index.sqlite3")
            connection = sqlite3.connect(index_path)
            connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                [("revision", spec.revision), ("manifest_sha256", spec.sha256)],
            )
            connection.commit()
            connection.close()
            stat = index_path.stat()
            Path(directory, "state.json").write_text(json.dumps({
                "status": "ready",
                "revision": spec.revision,
                "manifest_sha256": spec.sha256,
                "index_integrity": "ok",
                "index_size": stat.st_size,
                "index_mtime_ns": stat.st_mtime_ns,
            }), encoding="utf-8")

            with patch("personal_knowledge_base.open_rag_benchmark._full_integrity_check") as full_check:
                self.assertTrue(_cache_artifacts_verified(spec))
                self.assertTrue(_cache_artifacts_verified(spec))

            full_check.assert_not_called()

    @patch("personal_knowledge_base.open_rag_benchmark._embed_batches", side_effect=RuntimeError("upstream failed"))
    @patch("personal_knowledge_base.model_providers.active_embedding_config", return_value={"model": "embedding-model", "dimension": 2})
    @patch("personal_knowledge_base.open_rag_benchmark._load_corpus_documents")
    def test_vector_build_failure_fails_preparation(self, documents, _active_embedding, _embed):
        documents.return_value = [{"id": "doc-1", "title": "Title", "sections": [{"section_id": 1, "text": "content"}]}]
        with tempfile.TemporaryDirectory() as directory:
            spec = replace(get_dataset_spec("open_rag_benchmark", "arxiv-v1"), cache_path=Path(directory))
            existing_index = Path(directory, "index.sqlite3")
            existing_index.write_bytes(b"existing-compatible-index")

            with self.assertRaises(OpenRagDatasetError):
                _build_index(spec)

            self.assertEqual(existing_index.read_bytes(), b"existing-compatible-index")

    @patch("personal_knowledge_base.open_rag_benchmark._query_embeddings", return_value=[None])
    @patch("personal_knowledge_base.open_rag_benchmark.search_open_rag")
    @patch("personal_knowledge_base.open_rag_benchmark.sample_open_rag_questions")
    def test_degraded_rerank_keeps_fallback_metrics_but_is_unverified(self, sample, search, _query_embeddings):
        sample.return_value = [{"query_id": "q1", "query": "query", "qrel": {"doc_id": "doc-1", "section_id": 1}}]
        search.return_value = ([{"doc_id": "doc-1", "section_id": "1"}], {"degradations": ["rerank_unavailable"]})

        result = run_open_rag_retrieval(object(), get_dataset_spec("open_rag_benchmark", "arxiv-v1"), 1, 1)

        self.assertFalse(result["verified"])
        self.assertEqual(result["hit_at_10_new"], 1.0)
        self.assertEqual(result["per_question"][0]["mrr_at_10"], 1.0)
        self.assertEqual(result["valid_coverage"], 1.0)
        self.assertEqual(result["failed_questions"], 0)

    @patch("personal_knowledge_base.model_providers.active_embedding_config", return_value={"model": "embedding", "dimension": 2})
    @patch("personal_knowledge_base.open_rag_benchmark._public_chunks")
    @patch("personal_knowledge_base.open_rag_benchmark._public_document_map")
    @patch("personal_knowledge_base.open_rag_benchmark.sample_open_rag_questions")
    def test_chunking_ranks_nonrelevant_candidates_before_qrel_matching(self, sample, document_map, public_chunks, _embedding):
        sample.return_value = [{"query_id": "q1", "query": "needle", "qrel": {"doc_id": "doc-a", "section_id": 1}}]
        document_map.return_value = {
            "doc-a": {"source": "relevant", "sections": {"1": (0, 8)}, "section_blocks": [], "title": "A"},
            "doc-b": {"source": "distractor", "sections": {"1": (0, 10)}, "section_blocks": [], "title": "B"},
        }
        public_chunks.side_effect = lambda document, *_args: [{
            "start": 0, "end": len(document["source"]), "context_start": 0, "context_end": len(document["source"]),
            "content": "needle" if document["title"] == "B" else "unrelated",
        }]

        result = run_open_rag_chunking(
            object(),
            get_dataset_spec("open_rag_benchmark", "arxiv-v1"),
            1,
            1,
            ["fixed_window", "recursive", "auto_parent_child", "semantic_parent_child"],
        )

        self.assertTrue(result["verified"])
        self.assertEqual(result["strategies"]["fixed_window"]["mrr_at_10"], 0.0)

    @patch("personal_knowledge_base.model_providers.active_embedding_config", return_value={"model": "embedding", "dimension": 2})
    @patch("personal_knowledge_base.open_rag_benchmark._rank_public_chunks", return_value=[])
    @patch("personal_knowledge_base.open_rag_benchmark._public_chunks", return_value=[])
    @patch("personal_knowledge_base.open_rag_benchmark._public_document_map")
    @patch("personal_knowledge_base.open_rag_benchmark.sample_open_rag_questions")
    def test_chunking_loads_only_documents_referenced_by_sampled_qrels(self, sample, document_map, _chunks, _rank, _embedding):
        sample.return_value = [
            {"query_id": "q1", "query": "one", "qrel": {"doc_id": "doc-a", "section_id": 1}},
            {"query_id": "q2", "query": "two", "qrel": {"doc_id": "doc-b", "section_id": 2}},
        ]
        document_map.return_value = {
            "doc-a": {"source": "", "sections": {"1": (0, 0)}, "section_blocks": [], "title": "A"},
            "doc-b": {"source": "", "sections": {"2": (0, 0)}, "section_blocks": [], "title": "B"},
        }
        spec = get_dataset_spec("open_rag_benchmark", "arxiv-v1")

        run_open_rag_chunking(object(), spec, 2, 7)

        document_map.assert_called_once_with(spec, {"doc-a", "doc-b"})

    @patch("personal_knowledge_base.model_providers.active_embedding_config", return_value={"model": "embedding", "dimension": 2})
    @patch("personal_knowledge_base.open_rag_benchmark._rank_public_chunks", side_effect=AssertionError("question loop rescanned every chunk"))
    @patch("personal_knowledge_base.open_rag_benchmark._public_chunks")
    @patch("personal_knowledge_base.open_rag_benchmark._public_document_map")
    @patch("personal_knowledge_base.open_rag_benchmark.sample_open_rag_questions")
    def test_chunking_uses_a_prebuilt_index_instead_of_rescanning_chunks_per_question(self, sample, document_map, public_chunks, _rank, _embedding):
        sample.return_value = [
            {"query_id": "q1", "query": "needle", "qrel": {"doc_id": "doc-a", "section_id": 1}},
            {"query_id": "q2", "query": "needle", "qrel": {"doc_id": "doc-a", "section_id": 1}},
        ]
        document_map.return_value = {
            "doc-a": {"source": "needle", "sections": {"1": (0, 6)}, "section_blocks": ["needle"], "title": "A"},
        }
        public_chunks.return_value = [{"start": 0, "end": 6, "context_start": 0, "context_end": 6, "content": "needle"}]

        result = run_open_rag_chunking(object(), get_dataset_spec("open_rag_benchmark", "arxiv-v1"), 2, 7)

        self.assertTrue(result["verified"])
        self.assertEqual(public_chunks.call_count, 4)

    @patch("personal_knowledge_base.model_providers.active_embedding_config", return_value=None)
    @patch("personal_knowledge_base.open_rag_benchmark._rank_public_chunk_index", side_effect=AssertionError("must reuse production retrieval"))
    @patch("personal_knowledge_base.open_rag_benchmark._public_chunks")
    @patch("personal_knowledge_base.open_rag_benchmark._public_document_map")
    @patch("personal_knowledge_base.open_rag_benchmark.sample_open_rag_questions")
    def test_chunking_reuses_production_top20_without_reembedding_or_reranking(
        self, sample, document_map, public_chunks, _rank, _embedding
    ):
        sample.return_value = [{"query_id": "q1", "query": "needle", "qrel": {"doc_id": "doc-a", "section_id": 1}}]
        document_map.return_value = {
            "doc-a": {"id": "doc-a", "source": "needle", "sections": {"1": (0, 6)}, "section_blocks": ["needle"], "title": "A"},
        }
        public_chunks.return_value = [{"start": 0, "end": 6, "context_start": 0, "context_end": 6, "content": "needle"}]
        retrieved = {"q1": ([{"doc_id": "doc-a", "section_id": "1"}], {"degradations": []})}

        result = run_open_rag_chunking(
            object(), get_dataset_spec("open_rag_benchmark", "arxiv-v1"), 1, 7,
            ["fixed_window"], retrieved_results=retrieved,
        )

        self.assertTrue(result["verified"])
        self.assertEqual(result["strategies"]["fixed_window"]["mrr_at_10"], 1.0)
        self.assertEqual(result["strategies"]["fixed_window"]["retrieval_pipeline"], "shared_production_top20")

    def test_shared_retrieval_chunk_mapping_never_leaks_same_offsets_from_other_documents(self):
        index = {"chunks": [
            {"doc_id": "doc-b", "start": 0, "end": 6, "context_start": 0, "context_end": 6},
            {"doc_id": "doc-a", "start": 0, "end": 6, "context_start": 0, "context_end": 6},
        ]}
        document = {"id": "doc-a", "sections": {"1": (0, 6)}}

        ranked = open_rag_module._rank_public_chunks_from_retrieval(
            index, document, [{"doc_id": "doc-a", "section_id": "1"}]
        )

        self.assertEqual([item["doc_id"] for item in ranked], ["doc-a"])

    def test_public_chunk_index_builds_document_lookup_for_shared_retrieval(self):
        index = open_rag_module._build_public_chunk_index({
            "doc-a": [{"doc_id": "doc-a", "start": 0, "end": 6, "context_start": 0, "context_end": 6, "content": "a"}],
            "doc-b": [{"doc_id": "doc-b", "start": 0, "end": 6, "context_start": 0, "context_end": 6, "content": "b"}],
        })

        self.assertEqual([item["doc_id"] for item in index["chunks_by_doc"]["doc-a"]], ["doc-a"])
        index["connection"].close()

    @patch("personal_knowledge_base.model_providers.active_embedding_config", return_value=None)
    @patch("personal_knowledge_base.open_rag_benchmark._public_chunks")
    @patch("personal_knowledge_base.open_rag_benchmark._public_document_map")
    @patch("personal_knowledge_base.open_rag_benchmark.sample_open_rag_questions")
    def test_chunking_keeps_non_qrel_production_candidates_in_rank_order(
        self, sample, document_map, public_chunks, _embedding
    ):
        sample.return_value = [{
            "query_id": "q1", "query": "needle",
            "qrel": {"doc_id": "doc-a", "section_id": "1"},
        }]
        document_map.return_value = {
            "doc-a": {"id": "doc-a", "source": "needle", "sections": {"1": (0, 6)}, "section_blocks": [], "title": "A"},
            "doc-b": {"id": "doc-b", "source": "needle", "sections": {"1": (0, 6)}, "section_blocks": [], "title": "B"},
        }
        public_chunks.side_effect = lambda document, *_args: [{
            "start": 0, "end": 6, "context_start": 0, "context_end": 6,
            "content": "needle", "doc_id": document["id"],
        }]
        result = run_open_rag_chunking(
            object(), get_dataset_spec("open_rag_benchmark", "arxiv-v1"), 1, 7,
            ["fixed_window"],
            retrieved_results={"q1": ([{"doc_id": "doc-b", "section_id": "1"}, {"doc_id": "doc-a", "section_id": "1"}], {})},
        )

        self.assertEqual(result["strategies"]["fixed_window"]["mrr_at_10"], 0.5)
        document_map.assert_called_once_with(get_dataset_spec("open_rag_benchmark", "arxiv-v1"), {"doc-a", "doc-b"})

    @patch("personal_knowledge_base.model_providers.chat_completion")
    @patch("personal_knowledge_base.open_rag_benchmark._hydrate_open_rag_retrieved")
    @patch("personal_knowledge_base.open_rag_benchmark.sample_open_rag_questions")
    def test_answer_resume_rehydrates_context_from_reference_only_checkpoint(self, sample, hydrate, chat):
        sample.return_value = [{"query_id": "q1", "query": "question", "answer": "reference"}]
        hydrate.return_value = {"q1": ([{"id": 1, "content": "rehydrated context"}], {"degradations": []})}

        result = open_rag_module.generate_open_rag_answers(
            object(),
            get_dataset_spec("open_rag_benchmark", "arxiv-v1"),
            sample_size=1,
            retrieved_results={"q1": ([{"id": 1}], {"degradations": []})},
            existing_details=[{"query_id": "q1", "answer": "saved answer", "valid": True}],
        )

        chat.assert_not_called()
        self.assertEqual(result["details"][0]["contexts"], ["rehydrated context"])
        self.assertEqual(result["details"][0]["question"], "question")
        self.assertEqual(result["details"][0]["ground_truth"], "reference")

    @patch("personal_knowledge_base.model_providers.chat_completion", return_value="retried answer")
    @patch("personal_knowledge_base.open_rag_benchmark._hydrate_open_rag_retrieved")
    @patch("personal_knowledge_base.open_rag_benchmark.sample_open_rag_questions")
    def test_answer_resume_retries_invalid_checkpoint_entries(self, sample, hydrate, chat):
        sample.return_value = [{"query_id": "q1", "query": "question", "answer": "reference"}]
        hydrate.return_value = {"q1": ([{"id": 1, "content": "context"}], {"degradations": []})}

        result = open_rag_module.generate_open_rag_answers(
            object(), get_dataset_spec("open_rag_benchmark", "arxiv-v1"), sample_size=1,
            retrieved_results={"q1": ([{"id": 1}], {})},
            existing_details=[{"query_id": "q1", "valid": False, "error": "temporary"}],
        )

        chat.assert_called_once()
        self.assertEqual(chat.call_args.kwargs, {
            "max_tokens": 1024,
            "enable_thinking": False,
        })
        self.assertTrue(result["details"][0]["valid"])

    @patch("personal_knowledge_base.model_providers.chat_completion", return_value="   ")
    @patch("personal_knowledge_base.open_rag_benchmark._hydrate_open_rag_retrieved")
    @patch("personal_knowledge_base.open_rag_benchmark.sample_open_rag_questions")
    def test_answer_generation_rejects_empty_model_output(self, sample, hydrate, _chat):
        sample.return_value = [{"query_id": "q1", "query": "question", "answer": "reference"}]
        hydrate.return_value = {"q1": ([{"id": 1, "content": "context"}], {"degradations": []})}

        result = open_rag_module.generate_open_rag_answers(
            object(), get_dataset_spec("open_rag_benchmark", "arxiv-v1"), sample_size=1,
            retrieved_results={"q1": ([{"id": 1}], {})},
        )

        self.assertFalse(result["details"][0]["valid"])
        self.assertEqual(result["failed_questions"], 1)

    @patch("personal_knowledge_base.ragas_adapter.evaluate_dataset", return_value=[{
        "faithfulness": 0.8,
        "answer_relevancy": 0.7,
        "context_precision": 0.6,
    }])
    @patch("personal_knowledge_base.open_rag_benchmark.generate_open_rag_answers")
    def test_ragas_resume_rehydrates_sanitized_checkpoint_answers(self, generate, evaluate):
        sanitized = {
            "details": [{"query_id": "q1", "answer": "saved", "valid": True}],
            "total_questions": 1,
            "failed_questions": 0,
            "degradations": [],
        }
        hydrated = {
            **sanitized,
            "details": [{
                "query_id": "q1",
                "question": "question",
                "answer": "saved",
                "contexts": ["context"],
                "ground_truth": "reference",
                "valid": True,
            }],
        }
        generate.return_value = hydrated

        result = open_rag_module.run_open_rag_evaluation(
            tenant=object(),
            spec=get_dataset_spec("open_rag_benchmark", "arxiv-v1"),
            sample_size=1,
            seed=7,
            retrieved_results={"q1": ([{"id": 1}], {})},
            answer_result=sanitized,
        )

        self.assertEqual(result["faithfulness"], 0.8)
        self.assertEqual(generate.call_args.kwargs["existing_details"], sanitized["details"])
        evaluate.assert_called_once()
        self.assertEqual(evaluate.call_args.args[0][0]["question"], "question")

    @patch("personal_knowledge_base.ragas_adapter.evaluate_dataset", return_value=[
        {"faithfulness": 0.8, "answer_relevancy": 0.7, "context_precision": 0.6},
        {"valid": False, "error": "ragas_score_invalid"},
    ])
    def test_ragas_metrics_keep_valid_questions_when_one_judge_score_fails(self, _evaluate):
        details = [
            {"query_id": "q1", "question": "q1", "answer": "a1", "contexts": ["c1"], "ground_truth": "r1", "valid": True},
            {"query_id": "q2", "question": "q2", "answer": "a2", "contexts": ["c2"], "ground_truth": "r2", "valid": True},
        ]

        result = open_rag_module.run_open_rag_evaluation(
            tenant=object(),
            spec=get_dataset_spec("open_rag_benchmark", "arxiv-v1"),
            sample_size=2,
            answer_result={
                "details": details,
                "total_questions": 2,
                "failed_questions": 0,
                "degradations": [],
            },
        )

        self.assertEqual(result["faithfulness"], 0.8)
        self.assertEqual(result["total_questions"], 2)
        self.assertEqual(result["failed_questions"], 1)
        self.assertEqual(result["valid_coverage"], 0.5)
        self.assertFalse(result["verified"])

    @patch("personal_knowledge_base.open_rag_benchmark._public_chunks", return_value=[])
    @patch("personal_knowledge_base.open_rag_benchmark._public_document_map", return_value={})
    @patch("personal_knowledge_base.open_rag_benchmark.sample_open_rag_questions")
    def test_chunking_cancel_callback_runs_before_each_strategy(self, sample, document_map, chunks):
        sample.return_value = [{"query_id": "q1", "query": "q", "qrel": {"doc_id": "doc-a", "section_id": "1"}}]
        document_map.return_value = {"doc-a": {"id": "doc-a", "source": "", "sections": {}, "section_blocks": [], "title": "A"}}
        cancelled = Mock()

        run_open_rag_chunking(
            object(), get_dataset_spec("open_rag_benchmark", "arxiv-v1"), 1, 7,
            ["fixed_window", "recursive"], cancel_callback=cancelled,
        )

        self.assertGreaterEqual(cancelled.call_count, 2)

    @patch("personal_knowledge_base.model_providers.active_embedding_config", return_value={"model": "embedding", "dimension": 2})
    @patch("personal_knowledge_base.open_rag_benchmark._rank_public_chunks", side_effect=lambda chunks, _query: chunks)
    @patch("personal_knowledge_base.open_rag_benchmark._public_chunks")
    @patch("personal_knowledge_base.open_rag_benchmark._public_document_map")
    @patch("personal_knowledge_base.open_rag_benchmark.sample_open_rag_questions")
    def test_chunking_failure_is_isolated_to_its_own_strategy(self, sample, document_map, public_chunks, _rank, _embedding):
        sample.return_value = [{"query_id": "q1", "query": "needle", "qrel": {"doc_id": "doc-a", "section_id": 1}}]
        document_map.return_value = {
            "doc-a": {"source": "needle", "sections": {"1": (0, 6)}, "section_blocks": ["needle"], "title": "A"},
        }

        def chunks_for_strategy(_document, strategy, _tenant):
            if strategy == "semantic_parent_child":
                raise RuntimeError("semantic provider failed")
            return [{"start": 0, "end": 6, "context_start": 0, "context_end": 6, "content": "needle"}]

        public_chunks.side_effect = chunks_for_strategy
        result = run_open_rag_chunking(object(), get_dataset_spec("open_rag_benchmark", "arxiv-v1"), 1, 7)

        self.assertEqual(result["strategies"]["fixed_window"]["mrr_at_10"], 1.0)
        self.assertIsNone(result["strategies"]["semantic_parent_child"]["mrr_at_10"])

    @patch("personal_knowledge_base.open_rag_benchmark.RETRIEVAL_WORKERS", 2)
    @patch("personal_knowledge_base.open_rag_benchmark.search_open_rag")
    @patch("personal_knowledge_base.open_rag_benchmark._query_embeddings", create=True)
    @patch("personal_knowledge_base.open_rag_benchmark.sample_open_rag_questions")
    def test_retrieval_batches_query_embeddings_and_honors_selected_strategy(self, sample, query_embeddings, search):
        sample.return_value = [
            {"query_id": "q1", "query": "first question", "qrel": {"doc_id": "doc-a", "section_id": 1}},
            {"query_id": "q2", "query": "second question", "qrel": {"doc_id": "doc-b", "section_id": 2}},
        ]
        query_embeddings.return_value = [[1.0, 0.0], [0.0, 1.0]]
        search.return_value = ([], {"degradations": []})
        tenant = object()
        spec = get_dataset_spec("open_rag_benchmark", "arxiv-v1")

        run_open_rag_retrieval(tenant, spec, 2, 7, retrieval_strategy="vector")

        query_embeddings.assert_called_once_with(tenant, spec, ["first question", "second question"], "vector")
        self.assertEqual(search.call_args_list[0].kwargs["retrieval_strategy"], "vector")
        self.assertEqual(search.call_args_list[0].kwargs["query_vector"], [1.0, 0.0])

    @patch("personal_knowledge_base.open_rag_benchmark.RETRIEVAL_WORKERS", 2)
    @patch("personal_knowledge_base.open_rag_benchmark.search_open_rag")
    @patch("personal_knowledge_base.open_rag_benchmark._query_embeddings", return_value=[None, None, None, None])
    @patch("personal_knowledge_base.open_rag_benchmark.sample_open_rag_questions")
    def test_retrieval_searches_queries_with_bounded_parallelism(self, sample, _query_embeddings, search):
        sample.return_value = [
            {"query_id": f"q{index}", "query": f"question {index}", "qrel": {"doc_id": "doc", "section_id": index}}
            for index in range(4)
        ]
        lock = threading.Lock()
        active = 0
        peak = 0

        def search_one(*_args, **_kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return ([], {"degradations": []})

        search.side_effect = search_one
        result = open_rag_module.retrieve_open_rag_questions(
            object(), get_dataset_spec("open_rag_benchmark", "arxiv-v1"), sample.return_value,
            retrieval_strategy="keyword",
        )

        self.assertEqual(len(result), 4)
        self.assertGreaterEqual(peak, 2)


@override_settings(ALLOW_AUTO_SETUP=True)
class OpenRagApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.tenant = Tenant.objects.create(name="open-rag-tenant", api_key="open-rag-key")
        user = User.objects.create(
            username="open-rag-user",
            email="open-rag@example.test",
            password_hash="unused",
            tenant=self.tenant,
        )
        token = AuthToken.objects.create(
            user=user,
            token="open-rag-token",
            token_type="access",
            expires_at="2099-01-01T00:00:00Z",
        )
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {token.token}"}

    def _post(self, path, payload=None):
        return self.client.post(
            path,
            data=json.dumps(payload or {}),
            content_type="application/json",
            **self.headers,
        )

    @patch("personal_knowledge_base.open_rag_benchmark._cache_artifacts_verified", return_value=True)
    @patch("personal_knowledge_base.open_rag_benchmark._build_index")
    def test_preparation_short_circuits_verified_cache_and_reconciles_pending_tasks(self, build_index, _verified):
        with tempfile.TemporaryDirectory() as directory:
            spec = replace(
                get_dataset_spec("open_rag_benchmark_180", "arxiv-v1"),
                cache_path=Path(directory),
            )
            stale = TaskRecord.objects.create(
                task_type="prepare_open_rag_dataset",
                status="pending",
                payload={"dataset_id": "open_rag_benchmark", "dataset_version": "arxiv-v1"},
            )

            result = prepare_open_rag_dataset(spec)

            stale.refresh_from_db()

        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["ready"])
        self.assertEqual(result["queries"], 180)
        self.assertEqual(stale.status, "completed")
        self.assertEqual(stale.progress, 1)
        build_index.assert_not_called()

    @patch("personal_knowledge_base.open_rag_benchmark.open_dataset_status")
    def test_list_returns_metadata_without_full_records(self, status):
        status.return_value = {"status": "not_ready", "ready": False, "progress": 0, "verified": False}
        response = self.client.get("/api/v1/rag-eval/open-datasets", **self.headers)

        self.assertEqual(response.status_code, 200)
        datasets = response.json()["data"]["datasets"]
        self.assertEqual(
            [dataset["id"] for dataset in datasets],
            ["open_rag_benchmark_180", "open_rag_benchmark_full"],
        )
        self.assertTrue(all(dataset["version"] == "arxiv-v1" for dataset in datasets))
        self.assertTrue(all("records" not in dataset for dataset in datasets))
        self.assertTrue(all(not dataset["ready"] for dataset in datasets))

    def test_unknown_dataset_status_returns_404(self):
        response = self.client.get("/api/v1/rag-eval/open-datasets/missing/status", **self.headers)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "open_dataset_not_found")

    @patch("personal_knowledge_base.eval_views.enqueue")
    def test_prepare_is_idempotent_and_writes_no_tenant_resources(self, enqueue):
        existing = TaskRecord.objects.create(
            task_type="prepare_open_rag_dataset",
            status="running",
            payload={"dataset_id": "open_rag_benchmark_full", "dataset_version": "arxiv-v1", "tenant_id": self.tenant.id},
        )
        before = (GenericResource.objects.count(), KnowledgeBase.objects.count(), Knowledge.objects.count())

        first = self._post("/api/v1/rag-eval/open-datasets/open_rag_benchmark/prepare")
        second = self._post("/api/v1/rag-eval/open-datasets/open_rag_benchmark/prepare")

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(first.json()["data"]["task_id"], existing.id)
        self.assertEqual(second.json()["data"]["task_id"], existing.id)
        enqueue.assert_not_called()
        self.assertEqual(before, (GenericResource.objects.count(), KnowledgeBase.objects.count(), Knowledge.objects.count()))

    @patch("personal_knowledge_base.eval_views.enqueue")
    @patch("personal_knowledge_base.eval_views.open_dataset_status")
    def test_prepare_task_payload_is_global_not_tenant_bound(self, status, enqueue):
        status.return_value = {"status": "not_ready", "ready": False, "progress": 0, "verified": False}
        enqueue.return_value = SimpleNamespace(id="task-1", status="pending")

        response = self._post("/api/v1/rag-eval/open-datasets/open_rag_benchmark/prepare")

        self.assertEqual(response.status_code, 202)
        payload = enqueue.call_args.args[2]
        self.assertEqual(payload, {"dataset_id": "open_rag_benchmark_full", "dataset_version": "arxiv-v1"})

    @patch("personal_knowledge_base.open_rag_benchmark._cache_artifacts_verified", return_value=False)
    @patch("personal_knowledge_base.open_rag_benchmark.cache.get")
    def test_status_does_not_hide_failed_task_behind_queued_cache(self, cache_get, _verified):
        cache_get.return_value = {
            "status": "queued",
            "progress": 0,
            "revision": "63f6b052ff83508b08e242db42263ee708815c26",
            "manifest_sha256": "a656020a107d66c9d6bdb025e9b6761d6f7bd9e9cd13d045b212b338ca9b2ab5",
        }
        TaskRecord.objects.create(
            task_type="prepare_open_rag_dataset",
            status="failed",
            error_message="Open RAG embedding rate limit reached",
            payload={"dataset_id": "open_rag_benchmark", "dataset_version": "arxiv-v1"},
        )

        status = open_dataset_status(get_dataset_spec("open_rag_benchmark", "arxiv-v1"))

        self.assertEqual(status["status"], "failed")
        self.assertIn("rate limit", status["error"])

    @patch("personal_knowledge_base.eval_views.enqueue")
    @patch("personal_knowledge_base.eval_views.open_dataset_status")
    def test_public_run_uses_isolated_open_dataset_pipeline(self, status, enqueue):
        status.return_value = {"status": "ready", "ready": True, "progress": 1}
        enqueue.return_value = SimpleNamespace(id="open-run", status="pending", payload={}, result={}, progress=0, error_message="", created_at=None, updated_at=None)
        before_resources = GenericResource.objects.count()
        response = self._post("/api/v1/rag-eval/run", {
            "open_dataset_id": "open_rag_benchmark",
            "dataset_version": "arxiv-v1",
            "sample_size": 2,
            "seed": 20260819,
        })

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["data"]["run_id"], "open-run")
        self.assertEqual(enqueue.call_args.args[0], "open_rag_evaluation")
        self.assertEqual(enqueue.call_args.args[2]["sample_size"], 2)
        self.assertEqual(enqueue.call_args.args[2]["seed"], 20260819)
        self.assertEqual(GenericResource.objects.count(), before_resources)

    @patch("personal_knowledge_base.eval_views.enqueue")
    @patch("personal_knowledge_base.eval_views.open_dataset_status")
    def test_public_run_defaults_to_the_180_question_subset(self, status, enqueue):
        status.return_value = {"status": "ready", "ready": True, "progress": 1}
        enqueue.return_value = SimpleNamespace(id="open-run", status="pending", payload={}, result={}, progress=0, error_message="", created_at=None, updated_at=None)

        response = self._post("/api/v1/rag-eval/run", {
            "open_dataset_id": "open_rag_benchmark",
            "dataset_version": "arxiv-v1",
        })

        self.assertEqual(response.status_code, 202)
        self.assertEqual(enqueue.call_args.args[2]["sample_size"], 180)

    @patch("personal_knowledge_base.eval_views.enqueue")
    @patch("personal_knowledge_base.eval_views.open_dataset_status")
    def test_public_run_accepts_the_full_dataset_size(self, status, enqueue):
        status.return_value = {"status": "ready", "ready": True, "progress": 1}
        enqueue.return_value = SimpleNamespace(id="open-run", status="pending", payload={}, result={}, progress=0, error_message="", created_at=None, updated_at=None)

        response = self._post("/api/v1/rag-eval/run", {
            "open_dataset_id": "open_rag_benchmark",
            "dataset_version": "arxiv-v1",
            "sample_size": 3045,
        })

        self.assertEqual(response.status_code, 202)
        self.assertEqual(enqueue.call_args.args[2]["sample_size"], 3045)

    @patch("personal_knowledge_base.eval_views.open_dataset_status")
    def test_public_run_rejects_unprepared_dataset(self, status):
        status.return_value = {"status": "downloading", "ready": False, "progress": 0.4}
        response = self._post("/api/v1/rag-eval/run", {
            "open_dataset_id": "open_rag_benchmark",
            "dataset_version": "arxiv-v1",
        })
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "open_dataset_not_ready")

    @patch("personal_knowledge_base.eval_views.enqueue")
    @patch("personal_knowledge_base.eval_views.open_dataset_status")
    def test_public_retrieval_uses_open_dataset_pipeline(self, status, enqueue):
        status.return_value = {"status": "ready", "ready": True, "progress": 1}
        enqueue.return_value = SimpleNamespace(id="open-run", status="pending", payload={}, result={}, progress=0, error_message="", created_at=None, updated_at=None)

        response = self._post("/api/v1/rag-eval/retrieval", {
            "open_dataset_id": "open_rag_benchmark",
            "dataset_version": "arxiv-v1",
            "sample_size": 2,
            "seed": 7,
        })

        self.assertEqual(response.status_code, 202)
        self.assertEqual(enqueue.call_args.args[2]["sample_size"], 2)
        self.assertEqual(enqueue.call_args.args[2]["seed"], 7)

    @patch("personal_knowledge_base.eval_views.enqueue")
    @patch("personal_knowledge_base.eval_views.open_dataset_status")
    def test_public_chunking_uses_open_dataset_pipeline(self, status, enqueue):
        status.return_value = {"status": "ready", "ready": True, "progress": 1}
        enqueue.return_value = SimpleNamespace(id="open-run", status="pending", payload={}, result={}, progress=0, error_message="", created_at=None, updated_at=None)

        response = self._post("/api/v1/rag-eval/chunking", {
            "open_dataset_id": "open_rag_benchmark",
            "dataset_version": "arxiv-v1",
            "sample_size": 2,
            "seed": 8,
            "strategies": ["fixed_window", "recursive", "auto_parent_child", "semantic_parent_child"],
        })

        self.assertEqual(response.status_code, 202)
        self.assertEqual(enqueue.call_args.args[2]["sample_size"], 2)
        self.assertEqual(enqueue.call_args.args[2]["seed"], 8)
        self.assertEqual(enqueue.call_args.args[2]["chunking_strategies"], ["fixed_window", "recursive", "auto_parent_child", "semantic_parent_child"])

    @patch("personal_knowledge_base.eval_views.open_dataset_status")
    def test_public_retrieval_and_chunking_reject_unprepared_dataset(self, status):
        status.return_value = {"status": "queued", "ready": False, "progress": 0.1}
        for path in ("/api/v1/rag-eval/retrieval", "/api/v1/rag-eval/chunking"):
            response = self._post(path, {"open_dataset_id": "open_rag_benchmark", "dataset_version": "arxiv-v1"})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["error"]["code"], "open_dataset_not_ready")

    def test_open_report_cannot_be_downloaded_by_another_tenant(self):
        from .eval_reports import save_open_evaluation_report

        report = save_open_evaluation_report(
            tenant=self.tenant,
            evaluation_type="retrieval",
            evaluator="open_rag",
            verified=False,
            dataset={"id": "open_rag_benchmark"},
            result={"api_key": "secret", "mrr_new": None},
        )
        other = Tenant.objects.create(name="other-open-rag-tenant", api_key="other-open-rag-key")
        other_user = User.objects.create(username="other-open-rag-user", email="other-open-rag@example.test", password_hash="unused", tenant=other)
        other_token = AuthToken.objects.create(user=other_user, token="other-open-rag-token", token_type="access", expires_at="2099-01-01T00:00:00Z")

        response = self.client.get(f"/api/v1/rag-eval/reports/{report['run_id']}", HTTP_AUTHORIZATION=f"Bearer {other_token.token}")

        self.assertEqual(response.status_code, 404)
