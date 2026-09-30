"""Evaluation task bridges exercised without database or model requests."""
from contextlib import ExitStack
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from . import tasks


def score(value):
    return {"faithfulness": value, "answer_relevancy": value, "context_precision": value}


class EvaluationExampleTaskTests(SimpleTestCase):
    def setUp(self):
        self.entries = [{"id": f"entry-{i}", "question": f"question-{i}"} for i in range(3)]
        self.payload = {
            "tenant_id": "tenant", "dataset_hash": "hash", "configuration_fingerprint": "config",
            "source": {"dataset_id": "dataset", "knowledge_base_id": "kb"},
            "dataset_id": "open", "dataset_version": "v1", "sample_size": 3,
        }
        self.tenant = SimpleNamespace(id="tenant")
        self.dataset = SimpleNamespace(id="dataset", data={
            "schema_version": "evaluation_v2", "dataset_hash": "hash", "knowledge_base_id": "kb",
            "entries": self.entries,
        })
        self.spec = SimpleNamespace(dataset_id="open", version="v1", sha256="hash", expected_documents=1)
        self.base_checkpoint = {
            "configuration_fingerprint": "config", "completed_stages": ["retrieval", "chunking"],
            "metrics": {"retrieval": {"verified": True}, "chunking": {"verified": True}},
            "partial_metrics": {"retrieval": {"verified": True}, "chunking": {"verified": True}},
            "retrieved_results": {entry["id"]: {"results": [{"content": "context"}], "valid": True} for entry in self.entries},
        }

    def run_task(self, kind="tenant", *, failed_answers=(), scores=None, checkpoint=None, judge_callback=True, real_judge=False):
        checkpoint = deepcopy(checkpoint if checkpoint is not None else self.base_checkpoint)
        report = Mock()
        writes = []
        judge_inputs = []
        self.api_calls = []
        from .ragas_adapter import evaluate_dataset as real_evaluate_dataset
        def synthetic_api_evaluate(*, dataset, **_kwargs):
            self.api_calls.append(dataset)
            return SimpleNamespace(scores=[score((int(row["user_input"].rsplit("-", 1)[-1]) + 1) / 10) for row in dataset])
        api = {
            "evaluate": synthetic_api_evaluate, "EvaluationDataset": lambda samples: samples,
            "SingleTurnSample": lambda **kwargs: kwargs,
            **{name: object for name in ("Faithfulness", "AnswerRelevancy", "ContextPrecision", "ContextPrecisionWithoutReference")},
        }
        def evaluate(rows, *_args, **kwargs):
            judge_inputs.extend(deepcopy(rows))
            if real_judge:
                return real_evaluate_dataset(rows, *_args, **kwargs)
            result = deepcopy(scores if scores is not None else [score((i + 1) / 10) for i in range(len(rows))])
            callback = kwargs.get("progress_callback")
            if callback and judge_callback:
                callback(len(result), len(rows), result)
            return result
        def generate_open(**_kwargs):
            details = [{
                "query_id": f"query-{i}", "question": f"question-{i}", "answer": "answer" if i not in failed_answers else "",
                "contexts": ["context"], "ground_truth": "reference", "valid": i not in failed_answers,
                **({"error": "answer_generation_failed:ValueError"} if i in failed_answers else {}),
            } for i in range(3)]
            return {"details": details, "total_questions": 3, "failed_questions": len(failed_answers), "verified": not failed_answers}
        def chat(_tenant, messages, *_args, **_kwargs):
            question = messages[-1]["content"].rsplit("问题：", 1)[-1]
            if int(question.rsplit("-", 1)[-1]) in failed_answers:
                raise ValueError("synthetic answer failure")
            return "answer"
        record = SimpleNamespace(payload=self.payload, claimed_by="worker")
        with ExitStack() as stack:
            patches = {
                "personal_knowledge_base.tasks.TaskRecord.objects.get": Mock(return_value=record),
                "personal_knowledge_base.models.Tenant.objects.filter": Mock(return_value=SimpleNamespace(first=lambda: self.tenant)),
                "personal_knowledge_base.models.GenericResource.objects.filter": Mock(return_value=SimpleNamespace(first=lambda: self.dataset)),
                "personal_knowledge_base.tasks._read_open_rag_checkpoint": Mock(return_value=checkpoint),
                "personal_knowledge_base.tasks._write_open_rag_checkpoint": lambda _tenant, _task, value: writes.append(deepcopy(value)),
                "personal_knowledge_base.tasks._update_open_rag_runtime": Mock(return_value=True),
                "personal_knowledge_base.tasks._open_rag_cancelled": Mock(return_value=False),
                "personal_knowledge_base.tasks._runtime_configuration_degradations": Mock(return_value=[]),
                "personal_knowledge_base.tasks._validate_tenant_evaluation_documents": Mock(),
                "personal_knowledge_base.tasks._cleanup_open_rag_checkpoints": Mock(),
                "personal_knowledge_base.tasks._open_rag_checkpoint_path": Mock(return_value=Mock()),
                "personal_knowledge_base.eval_reports.save_evaluation_report": Mock(return_value={"report_id": "report"}),
                "personal_knowledge_base.eval_reports.save_open_evaluation_report": Mock(return_value={"report_id": "report"}),
                "personal_knowledge_base.observability.report_evaluation_run": report,
                "personal_knowledge_base.ragas_adapter.evaluate_dataset": evaluate,
                "personal_knowledge_base.ragas_adapter._ragas_api": Mock(return_value=api),
                "personal_knowledge_base.ragas_adapter._clients": Mock(return_value=(object(), object())),
                "personal_knowledge_base.model_providers.chat_completion": chat,
                "personal_knowledge_base.open_rag_benchmark.generate_open_rag_answers": generate_open,
                "personal_knowledge_base.open_rag_benchmark.open_dataset_status": Mock(return_value={"ready": True}),
                "personal_knowledge_base.open_rag_benchmark.sample_open_rag_questions": Mock(return_value=[{"query_id": f"query-{i}"} for i in range(3)]),
                "personal_knowledge_base.eval_dataset_registry.get_dataset_spec": Mock(return_value=self.spec),
            }
            for name, replacement in patches.items():
                stack.enter_context(patch(name, new=replacement))
            result = (tasks.run_tenant_evaluation_task if kind == "tenant" else tasks.run_open_rag_evaluation_task)("task")
        return report.call_args.kwargs["examples"], writes, judge_inputs, result

    def resume_checkpoint(self, kind, saved_scores, saved_ids=None, missing_answer=False):
        checkpoint = deepcopy(self.base_checkpoint)
        checkpoint["completed_stages"] += ["answer_generation"]
        if kind == "tenant":
            checkpoint["answers"] = {f"entry-{i}": {"answer": "saved", "valid": True} for i in range(3) if not missing_answer or i != 0}
            checkpoint["judge_scores"] = saved_scores
            if saved_ids is not None:
                checkpoint["judge_example_ids"] = saved_ids
        else:
            checkpoint["answer_result"] = {"total_questions": 3, "details": [
                {"query_id": f"query-{i}", "question": f"question-{i}", "answer": "saved", "valid": True,
                 "contexts": ["context"], "ground_truth": "reference"}
                for i in range(3) if not missing_answer or i != 0
            ]}
            checkpoint["ragas_scores"] = saved_scores
            if saved_ids is not None:
                checkpoint["ragas_example_ids"] = saved_ids
        return checkpoint

    def test_real_judge_resume_reorders_saved_scores_by_identity_without_calls(self):
        for kind, prefix in (("tenant", "entry"), ("open", "query")):
            with self.subTest(kind=kind):
                checkpoint = self.resume_checkpoint(kind, [score(0.8), score(0.1), score(0.2)],
                                                    [f"{prefix}-{i}" for i in (2, 0, 1)])
                examples, writes, _, _ = self.run_task(kind, checkpoint=checkpoint, real_judge=True)
                self.assertEqual([row.get("faithfulness") for row in examples], [0.1, 0.2, 0.8])
                self.assertEqual(self.api_calls, [])
                key = "judge_example_ids" if kind == "tenant" else "ragas_example_ids"
                self.assertEqual(writes[-1][key], [f"{prefix}-{i}" for i in range(3)])

    def test_real_judge_resume_partial_identity_only_judges_truly_missing_rows(self):
        for kind, prefix in (("tenant", "entry"), ("open", "query")):
            with self.subTest(kind=kind):
                checkpoint = self.resume_checkpoint(kind, [score(0.8), {}, score(0.2)],
                                                    [f"{prefix}-{i}" for i in (2, 0, 1)])
                examples, _, _, _ = self.run_task(kind, checkpoint=checkpoint, real_judge=True)
                self.assertEqual([row.get("faithfulness") for row in examples], [0.1, 0.2, 0.8])
                self.assertEqual([[row["user_input"] for row in batch] for batch in self.api_calls], [["question-0"]])

    def test_real_judge_resume_truncated_partial_preserves_the_known_saved_row(self):
        for kind, prefix in (("tenant", "entry"), ("open", "query")):
            with self.subTest(kind=kind):
                checkpoint = self.resume_checkpoint(kind, [score(0.8)], [f"{prefix}-{i}" for i in (2, 0, 1)])
                examples, _, _, _ = self.run_task(kind, checkpoint=checkpoint, real_judge=True)
                self.assertEqual([row.get("faithfulness") for row in examples], [0.1, 0.2, 0.8])
                self.assertEqual([[row["user_input"] for row in batch] for batch in self.api_calls], [["question-0", "question-1"]])

    def test_real_judge_resume_complete_legacy_inputs_reconstruct_order(self):
        for kind in ("tenant", "open"):
            with self.subTest(kind=kind):
                checkpoint = self.resume_checkpoint(kind, [score(0.1), score(0.2), score(0.8)])
                examples, _, _, _ = self.run_task(kind, checkpoint=checkpoint, real_judge=True)
                self.assertEqual([row.get("faithfulness") for row in examples], [0.1, 0.2, 0.8])
                self.assertEqual(self.api_calls, [])

    def test_real_judge_resume_unknown_or_duplicate_identity_does_not_rejudge(self):
        for kind, prefix in (("tenant", "entry"), ("open", "query")):
            for ids in ([f"{prefix}-2", "unknown", f"{prefix}-1"], [f"{prefix}-2", f"{prefix}-2", f"{prefix}-1"]):
                with self.subTest(kind=kind, ids=ids):
                    checkpoint = self.resume_checkpoint(kind, [score(0.8), score(0.1), score(0.2)], ids)
                    examples, writes, _, result = self.run_task(kind, checkpoint=checkpoint, real_judge=True)
                    self.assertEqual(self.api_calls, [])
                    self.assertNotIn("faithfulness", examples[0])
                    self.assertEqual(examples[1].get("faithfulness"), 0.2)
                    if ids.count(f"{prefix}-2") > 1:
                        self.assertNotIn("faithfulness", examples[2])
                    else:
                        self.assertEqual(examples[2].get("faithfulness"), 0.8)
                    key = "judge_example_ids" if kind == "tenant" else "ragas_example_ids"
                    self.assertEqual(writes[-1][key], ids)
                    aggregate = writes[-1]["metrics" if kind == "tenant" else "partial_metrics"]["rag"]
                    self.assertFalse(aggregate["verified"])
                    self.assertEqual(aggregate["verification_status"], "degraded")
                    self.assertAlmostEqual(aggregate["faithfulness"], (0.8 + 0.1 + 0.2) / 3)
                    self.assertGreater(aggregate["failed_questions"], 0)
                    self.assertIn("checkpoint_score_identity_unmatched", str(aggregate["reasons"]))

    def test_real_judge_resume_incomplete_legacy_identity_does_not_guess_or_call(self):
        for kind in ("tenant", "open"):
            with self.subTest(kind=kind):
                checkpoint = self.resume_checkpoint(kind, [score(0.8), score(0.2)], missing_answer=True)
                examples, _, _, _ = self.run_task(kind, checkpoint=checkpoint, real_judge=True)
                self.assertEqual(self.api_calls, [])
                self.assertEqual([row["row_index"] for row in examples], [0, 1, 2])
                self.assertTrue(all(not row["valid"] and "faithfulness" not in row for row in examples))

    def test_tenant_first_and_middle_answer_failures_keep_original_rows(self):
        for failed in (0, 1):
            with self.subTest(failed=failed):
                examples, writes, inputs, _ = self.run_task(failed_answers=(failed,))
                self.assertEqual([row["example_id"] for row in examples], ["entry-0", "entry-1", "entry-2"])
                self.assertEqual([row["row_index"] for row in examples], [0, 1, 2])
                self.assertFalse(examples[failed]["valid"])
                self.assertIn("answer_generation_failed", examples[failed]["error"])
                self.assertNotIn("faithfulness", examples[failed])
                successful = [row for i, row in enumerate(examples) if i != failed]
                self.assertEqual([row["faithfulness"] for row in successful], [0.1, 0.2])
                self.assertEqual(len(inputs), 2)
                self.assertEqual(writes[-1]["judge_example_ids"], [row["example_id"] for row in successful])

    def test_open_first_and_middle_answer_failures_keep_original_rows(self):
        for failed in (0, 1):
            with self.subTest(failed=failed):
                examples, writes, inputs, _ = self.run_task("open", failed_answers=(failed,))
                self.assertEqual([row["example_id"] for row in examples], ["query-0", "query-1", "query-2"])
                self.assertEqual([row["row_index"] for row in examples], [0, 1, 2])
                self.assertFalse(examples[failed]["valid"])
                self.assertNotIn("faithfulness", examples[failed])
                self.assertEqual([row["faithfulness"] for i, row in enumerate(examples) if i != failed], [0.1, 0.2])
                self.assertEqual(len(inputs), 2)
                self.assertEqual(writes[-1]["ragas_example_ids"], [f"query-{i}" for i in range(3) if i != failed])

    def test_failed_judge_score_drops_partial_numeric_metrics(self):
        bad = {"valid": False, "error": "ragas_score_invalid", "faithfulness": 0.9}
        for kind in ("tenant", "open"):
            with self.subTest(kind=kind):
                examples, _, _, _ = self.run_task(kind, scores=[score(0.1), bad, score(0.3)])
                self.assertFalse(examples[1]["valid"])
                self.assertEqual(examples[1]["error"], "ragas_score_invalid")
                self.assertNotIn("faithfulness", examples[1])

    def test_explicitly_invalid_judge_score_drops_even_complete_metrics(self):
        bad = {**score(0.9), "valid": False, "error": "judge_failed"}
        for kind in ("tenant", "open"):
            with self.subTest(kind=kind):
                examples, _, _, _ = self.run_task(kind, scores=[score(0.1), bad, score(0.3)])
                self.assertFalse(examples[1]["valid"])
                self.assertEqual(examples[1]["error"], "judge_failed")
                self.assertNotIn("faithfulness", examples[1])

    def test_completed_legacy_checkpoint_maps_scores_without_judge_call(self):
        checkpoint = deepcopy(self.base_checkpoint)
        checkpoint["completed_stages"] += ["answer_generation", "ragas"]
        checkpoint["answers"] = {entry["id"]: {"answer": "answer", "valid": True} for entry in self.entries}
        checkpoint["judge_scores"] = [score(0.1), score(0.2), score(0.3)]
        checkpoint["metrics"]["rag"] = {"verified": True}
        first, _, inputs, _ = self.run_task(checkpoint=checkpoint)
        second, _, second_inputs, _ = self.run_task(checkpoint=checkpoint)
        self.assertEqual(inputs + second_inputs, [])
        self.assertEqual([row["example_id"] for row in first], ["entry-0", "entry-1", "entry-2"])
        self.assertEqual(first, second)
        self.assertEqual([row["faithfulness"] for row in first], [0.1, 0.2, 0.3])

    def test_completed_checkpoint_with_unknown_mapping_never_attaches_scores(self):
        checkpoint = deepcopy(self.base_checkpoint)
        checkpoint["completed_stages"] += ["answer_generation", "ragas"]
        checkpoint["answers"] = {entry["id"]: {"answer": "answer", "valid": True} for entry in self.entries}
        checkpoint["judge_scores"] = [score(0.1), score(0.2), score(0.3)]
        checkpoint["judge_example_ids"] = ["unknown-0", "unknown-1", "unknown-2"]
        examples, _, inputs, _ = self.run_task(checkpoint=checkpoint)
        self.assertEqual(inputs, [])
        self.assertTrue(all(not row["valid"] and "faithfulness" not in row for row in examples))
        self.assertTrue(all(row["error"] == "ragas_score_unmatched" for row in examples))

    def test_open_completed_legacy_checkpoint_keeps_query_ids_without_calls(self):
        checkpoint = deepcopy(self.base_checkpoint)
        checkpoint["completed_stages"] += ["answer_generation", "ragas"]
        checkpoint["answer_result"] = {"details": [
            {"query_id": f"query-{i}", "answer": "saved answer", "valid": True} for i in range(3)
        ], "total_questions": 3}
        checkpoint["ragas_scores"] = [score(0.1), score(0.2), score(0.3)]
        checkpoint["partial_metrics"]["rag"] = {"verified": True}
        examples, _, inputs, _ = self.run_task("open", checkpoint=checkpoint)
        self.assertEqual(inputs, [])
        self.assertEqual([row["example_id"] for row in examples], ["query-0", "query-1", "query-2"])
        self.assertEqual([row["faithfulness"] for row in examples], [0.1, 0.2, 0.3])

    def test_open_incomplete_legacy_checkpoint_does_not_guess_filtered_positions(self):
        checkpoint = deepcopy(self.base_checkpoint)
        checkpoint["completed_stages"] += ["answer_generation", "ragas"]
        checkpoint["answer_result"] = {"details": [
            {"query_id": "query-1", "answer": "saved", "valid": True},
            {"query_id": "query-2", "answer": "saved", "valid": True},
        ], "total_questions": 3}
        checkpoint["ragas_scores"] = [score(0.1), score(0.2)]
        checkpoint["partial_metrics"]["rag"] = {"verified": True}
        examples, _, inputs, _ = self.run_task("open", checkpoint=checkpoint)
        self.assertEqual(inputs, [])
        self.assertEqual([row["example_id"] for row in examples], ["query-0", "query-1", "query-2"])
        self.assertEqual([row["row_index"] for row in examples], [0, 1, 2])
        self.assertEqual([row.get("error") for row in examples], ["answer_missing", "ragas_score_unmatched", "ragas_score_unmatched"])
        self.assertTrue(all("faithfulness" not in row for row in examples))

    def test_open_evaluator_result_is_used_when_progress_callback_does_not_run(self):
        examples, writes, _, _ = self.run_task("open", judge_callback=False)
        self.assertEqual([row.get("faithfulness") for row in examples], [0.1, 0.2, 0.3])
        self.assertEqual(writes[-1]["ragas_scores"], [score(0.1), score(0.2), score(0.3)])

    def test_all_failed_answers_still_emit_all_rows_without_scores(self):
        for kind in ("tenant", "open"):
            with self.subTest(kind=kind):
                examples, _, inputs, _ = self.run_task(kind, failed_answers=(0, 1, 2))
                self.assertEqual(inputs, [])
                self.assertEqual(len(examples), 3)
                self.assertTrue(all(not row["valid"] and "faithfulness" not in row for row in examples))

    def test_incomplete_historical_answers_do_not_guess_positional_scores(self):
        checkpoint = deepcopy(self.base_checkpoint)
        checkpoint["completed_stages"] += ["answer_generation", "ragas"]
        checkpoint["answers"] = {"entry-0": {"answer": "saved", "valid": True}}
        checkpoint["judge_scores"] = [score(0.1), score(0.2)]
        examples, _, inputs, _ = self.run_task(checkpoint=checkpoint)
        self.assertEqual(inputs, [])
        self.assertEqual([row["error"] for row in examples], ["ragas_score_unmatched", "answer_missing", "answer_missing"])
        self.assertTrue(all("faithfulness" not in row for row in examples))

    def test_partial_checkpoint_scores_are_attached_only_to_the_recorded_rows(self):
        checkpoint = deepcopy(self.base_checkpoint)
        checkpoint["completed_stages"] += ["answer_generation", "ragas"]
        checkpoint["answers"] = {entry["id"]: {"answer": "saved", "valid": True} for entry in self.entries}
        checkpoint["judge_scores"] = [score(0.8)]
        checkpoint["judge_example_ids"] = ["entry-2", "entry-0", "entry-1"]
        examples, _, inputs, _ = self.run_task(checkpoint=checkpoint)
        self.assertEqual(inputs, [])
        self.assertEqual([row.get("faithfulness") for row in examples], [None, None, 0.8])


class EvaluationExampleProjectionTests(SimpleTestCase):
    def test_malformed_score_is_invalid_instead_of_crashing(self):
        from .evaluation_examples import build_evaluation_examples
        rows = [{"example_id": "query", "row_index": 7, "valid": True}]
        self.assertEqual(build_evaluation_examples(rows, [42], ["query"]), [
            {"example_id": "query", "row_index": 7, "valid": False, "error": "ragas_score_invalid"}
        ])

    def test_numeric_ids_are_preserved_and_missing_ids_use_original_row(self):
        from .evaluation_examples import open_example_rows, tenant_example_rows
        self.assertEqual([row["example_id"] for row in open_example_rows([
            {"query_id": 0, "valid": False}, {"valid": False}
        ])], ["0", "row-1"])
        self.assertEqual([row["example_id"] for row in tenant_example_rows([
            {"id": 0}, {}
        ], {})], ["0", "row-1"])

    def test_duplicate_judge_mapping_is_unmatched(self):
        from .evaluation_examples import build_evaluation_examples
        examples = build_evaluation_examples(
            [{"example_id": "query", "row_index": 2, "valid": True}],
            [score(0.1), score(0.9)], ["query", "query"],
        )
        self.assertEqual(examples, [{"example_id": "query", "row_index": 2, "valid": False, "error": "ragas_score_unmatched"}])
