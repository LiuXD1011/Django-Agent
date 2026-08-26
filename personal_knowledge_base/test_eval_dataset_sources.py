from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from .eval_dataset_registry import DatasetNotFoundError, get_dataset_spec, registered_dataset_ids
from .eval_dataset_sources import normalize_dataset_records


class EvaluationDatasetSourceTests(TestCase):
    def test_registry_exposes_only_open_rag_metadata(self):
        self.assertEqual(
            registered_dataset_ids(),
            ("open_rag_benchmark_180", "open_rag_benchmark_full"),
        )
        subset = get_dataset_spec("open_rag_benchmark_180", "arxiv-v1")
        legacy_subset = get_dataset_spec("open_rag_benchmark_100", "arxiv-v1")
        full = get_dataset_spec("open_rag_benchmark_full", "arxiv-v1")
        alias = get_dataset_spec("open_rag_benchmark", "arxiv-v1")

        self.assertEqual(subset.expected_queries, 180)
        self.assertEqual(legacy_subset, subset)
        self.assertEqual(full.expected_queries, 3045)
        self.assertEqual(alias, full)
        self.assertEqual(subset.cache_path, full.cache_path)
        self.assertEqual(subset.artifact_manifest_sha256, full.artifact_manifest_sha256)
        self.assertEqual(subset.expected_documents, 1000)
        self.assertEqual(subset.license, "CC-BY-NC-4.0")
        self.assertEqual(len(subset.sha256), 64)

    def test_removed_dataset_and_fixture_normalizers_are_rejected(self):
        for dataset_id in ("ragas", "squad", "hotpotqa"):
            with self.assertRaises(DatasetNotFoundError):
                get_dataset_spec(dataset_id, "v1")
            with self.assertRaises(DatasetNotFoundError):
                normalize_dataset_records(dataset_id, "v1", {})

    @patch("personal_knowledge_base.management.commands.import_eval_dataset.prepare_open_rag_dataset")
    def test_import_command_prepares_cache_without_tenant_import(self, prepare):
        prepare.return_value = {"status": "ready", "ready": True}
        call_command("import_eval_dataset", dataset="open_rag_benchmark_full", download=True)
        prepare.assert_called_once()

    def test_import_command_rejects_knowledge_base_mode(self):
        with self.assertRaises(CommandError):
            call_command("import_eval_dataset", dataset="open_rag_benchmark_full", mode="knowledge-base", tenant=1)
