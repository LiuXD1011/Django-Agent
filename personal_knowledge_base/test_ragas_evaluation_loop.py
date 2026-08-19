import json
from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from . import rag_eval
from .models import AuthToken, Tenant, User


class RagasAdapterTests(TestCase):
    def test_ragas_scores_are_preserved_per_question(self):
        details = [
            rag_eval.EvalDetail(question="first", answer="a1", contexts=["c1"], ground_truth=""),
            rag_eval.EvalDetail(question="second", answer="a2", contexts=["c2"], ground_truth=""),
        ]
        scores = [
            {"faithfulness": 0.2, "answer_relevancy": 0.4, "context_precision": 0.6},
            {"faithfulness": 0.8, "answer_relevancy": 1.0, "context_precision": 0.5},
        ]

        with patch("personal_knowledge_base.ragas_adapter.evaluate_dataset", return_value=scores):
            result = rag_eval._ragas_evaluation(details, tenant=object())

        self.assertEqual(result.faithfulness, 0.5)
        self.assertEqual(result.answer_relevancy, 0.7)
        self.assertEqual(result.context_precision, 0.55)
        self.assertEqual(result.details[0].faithfulness, 0.2)
        self.assertEqual(result.details[1].faithfulness, 0.8)
        self.assertEqual(result.details[0].context_precision, 0.6)
        self.assertEqual(result.details[1].context_precision, 0.5)

    def test_ragas_failure_is_exposed_without_scores(self):
        details = [rag_eval.EvalDetail(question="q", answer="a", contexts=["c"], ground_truth="")]
        with patch(
            "personal_knowledge_base.ragas_adapter.evaluate_dataset",
            side_effect=RuntimeError("judge unavailable"),
        ):
            with self.assertRaises(rag_eval.RagasEvaluationError):
                rag_eval._ragas_evaluation(details, tenant=object())


@override_settings(ALLOW_AUTO_SETUP=True)
class RagasEvaluationLoopApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.tenant_a, self.headers_a = self._tenant("a")
        self.tenant_b, self.headers_b = self._tenant("b")

    def _tenant(self, suffix):
        tenant = Tenant.objects.create(name=f"tenant-{suffix}", api_key=f"key-{suffix}")
        user = User.objects.create(
            username=f"user-{suffix}",
            email=f"user-{suffix}@example.test",
            password_hash="unused",
            tenant=tenant,
        )
        token = AuthToken.objects.create(user=user, token=f"token-{suffix}", token_type="access", expires_at="2099-01-01T00:00:00Z")
        return tenant, {"HTTP_AUTHORIZATION": f"Bearer {token.token}"}

    def _post(self, path, payload, headers):
        return self.client.post(path, data=json.dumps(payload), content_type="application/json", **headers)

    def test_manual_review_changes_only_candidate_status(self):
        created = self._post(
            "/api/v1/rag-eval/datasets",
            {
                "name": "manual dataset",
                "review_mode": "manual",
                "entries": [{"question": "What is it?", "answer": "An answer", "evidence": []}],
            },
            self.headers_a,
        )
        self.assertEqual(created.status_code, 201)
        dataset = created.json()["data"]
        entry = dataset["entries"][0]
        self.assertEqual(entry["status"], "pending_review")

        reviewed = self._post(
            f"/api/v1/rag-eval/datasets/{dataset['id']}/review",
            {"entry_ids": [entry["id"]], "status": "approved", "answer": "mutated"},
            self.headers_a,
        )
        self.assertEqual(reviewed.status_code, 200)
        self.assertEqual(reviewed.json()["data"]["entries"][0]["status"], "approved")
        self.assertEqual(reviewed.json()["data"]["entries"][0]["answer"], "An answer")

    def test_auto_review_rejects_missing_evidence_without_a_score(self):
        created = self._post(
            "/api/v1/rag-eval/datasets",
            {
                "name": "unverified dataset",
                "entries": [{"question": "What is it?", "answer": "An answer", "evidence": []}],
            },
            self.headers_a,
        )
        self.assertEqual(created.status_code, 201)
        data = created.json()["data"]
        self.assertEqual(data["entries"][0]["status"], "rejected")
        self.assertIn("evidence", data["entries"][0]["validation_errors"])
        self.assertEqual(data["entries"][0]["ground_truth"], "")

        run = self._post("/api/v1/rag-eval/run", {"dataset_id": data["id"]}, self.headers_a)
        self.assertEqual(run.status_code, 422)
        self.assertEqual(run.json()["error"]["code"], "unverified_eval_dataset")

    def test_dataset_is_tenant_scoped(self):
        created = self._post(
            "/api/v1/rag-eval/datasets",
            {"name": "private", "entries": []},
            self.headers_a,
        )
        dataset_id = created.json()["data"]["id"]

        listing = self.client.get("/api/v1/rag-eval/datasets", **self.headers_b)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["data"]["datasets"], [])

        foreign = self.client.get(f"/api/v1/rag-eval/datasets/{dataset_id}", **self.headers_b)
        self.assertEqual(foreign.status_code, 404)

    def test_sample_review_validates_sample_and_leaves_remaining_candidates_pending(self):
        created = self._post(
            "/api/v1/rag-eval/datasets",
            {
                "name": "sample dataset",
                "review_mode": "sample",
                "entries": [
                    {"question": "first", "answer": "answer", "evidence": []},
                    {"question": "second", "answer": "answer", "evidence": []},
                ],
            },
            self.headers_a,
        )
        self.assertEqual(created.status_code, 201)
        entries = created.json()["data"]["entries"]
        self.assertEqual(entries[0]["status"], "rejected")
        self.assertEqual(entries[1]["status"], "pending_review")

    def test_run_uses_saved_questions_before_defaults(self):
        self._post(
            "/api/v1/rag-eval/questions",
            {"question": "saved question", "ground_truth": "saved reference"},
            self.headers_a,
        )
        result = rag_eval.EvalResult(total_questions=1)
        with patch("personal_knowledge_base.eval_views.run_rag_evaluation", return_value=result) as run:
            response = self._post("/api/v1/rag-eval/run", {}, self.headers_a)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(run.call_args.kwargs["questions"][0]["question"], "saved question")
