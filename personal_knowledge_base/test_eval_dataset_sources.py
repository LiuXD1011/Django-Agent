from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from .eval_dataset_registry import DatasetNotFoundError, get_dataset_spec
from .eval_dataset_sources import normalize_dataset_records
from .models import KnowledgeBase, Tenant


class EvaluationDatasetSourceTests(SimpleTestCase):
    def test_registry_exposes_versioned_license_and_cache_metadata(self):
        spec = get_dataset_spec("squad", "v1")

        self.assertEqual(spec.dataset_id, "squad")
        self.assertEqual(spec.version, "v1")
        self.assertTrue(spec.source_url.startswith("https://"))
        self.assertTrue(spec.license)
        self.assertEqual(len(spec.sha256), 64)
        self.assertIn("eval-datasets", str(spec.cache_path))

    def test_unknown_dataset_is_rejected(self):
        with self.assertRaises(DatasetNotFoundError):
            get_dataset_spec("missing", "v1")

    def test_ragas_records_map_contexts_to_full_document_evidence(self):
        records = normalize_dataset_records(
            "ragas",
            "v1",
            [{
                "question": "Who wrote the guide?",
                "ground_truth": "Ada",
                "contexts": ["Ada wrote the guide.", "The guide was published in 2024."],
            }],
        )

        record = records[0]
        self.assertEqual(record["reference_answer"], "Ada")
        self.assertEqual(record["question_type"], "generative")
        self.assertEqual(record["status"], "ready")
        self.assertEqual(len(record["documents"]), 2)
        self.assertEqual(
            [(item["source_start"], item["source_end"]) for item in record["evidence"]],
            [(0, 20), (0, 32)],
        )

    def test_squad_answer_offsets_become_source_spans(self):
        records = normalize_dataset_records(
            "squad",
            "v1",
            {"data": [{"title": "Ada", "paragraphs": [{
                "context": "Ada wrote the guide in London.",
                "qas": [{
                    "id": "ada-1",
                    "question": "Who wrote the guide?",
                    "answers": [{"text": "Ada", "answer_start": 0, "answer_end": 3}],
                }],
            }]}]},
        )

        record = records[0]
        self.assertEqual(record["reference_answer"], "Ada")
        self.assertEqual(record["question_type"], "extractive")
        self.assertEqual(record["evidence"][0]["source_start"], 0)
        self.assertEqual(record["evidence"][0]["source_end"], 3)
        self.assertEqual(record["documents"][0]["text"][0:3], "Ada")

    def test_hotpot_supporting_facts_retain_multiple_document_spans(self):
        records = normalize_dataset_records(
            "hotpotqa",
            "v1",
            [{
                "_id": "hp-1",
                "question": "Which city connects Ada and the guide?",
                "answer": "London",
                "context": [
                    ["Ada", ["Ada wrote the guide.", "Ada lived in London."]],
                    ["Guide", ["The guide was published in London."]],
                ],
                "supporting_facts": [["Ada", 1], ["Guide", 0]],
            }],
        )

        record = records[0]
        self.assertEqual(record["question_type"], "multi_hop")
        self.assertEqual(len(record["documents"]), 2)
        self.assertEqual(len(record["evidence"]), 2)
        self.assertEqual(record["evidence"][0]["source_start"], 21)
        self.assertEqual(record["evidence"][0]["source_end"], 41)
        self.assertEqual(record["evidence"][1]["source_start"], 0)
        self.assertEqual(record["evidence"][1]["source_end"], 34)
        self.assertNotEqual(record["evidence"][0]["document_id"], record["evidence"][1]["document_id"])

    def test_empty_and_duplicate_records_are_retained_as_skipped_statuses(self):
        records = normalize_dataset_records(
            "ragas",
            "v1",
            [
                {"id": "same", "question": "", "ground_truth": "answer", "contexts": ["context"]},
                {"id": "same", "question": "Question?", "ground_truth": "answer", "contexts": ["context"]},
                {"id": "same", "question": "Question?", "ground_truth": "answer", "contexts": ["context"]},
            ],
        )

        self.assertEqual([item["status"] for item in records], ["skipped_empty_question", "ready", "skipped_duplicate"])
        self.assertTrue(all({"dataset_id", "dataset_version", "question", "reference_answer", "documents", "evidence", "question_type", "status"} <= item.keys() for item in records))


class ImportEvaluationDatasetCommandTests(TestCase):
    def test_knowledge_base_dry_run_is_tenant_scoped_and_writes_nothing(self):
        tenant = Tenant.objects.create(name="eval tenant", api_key="eval-command-key")

        call_command(
            "import_eval_dataset",
            dataset="squad",
            dataset_version="v1",
            mode="knowledge-base",
            tenant=tenant.pk,
            dry_run=True,
        )

        self.assertEqual(KnowledgeBase.objects.filter(tenant=tenant).count(), 0)
