import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import Client, TestCase

from .models import AuthToken, GenericResource, KnowledgeBase, ModelConfig, TaskRecord, Tenant, User


class OpenRagRunApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.tenant = self._tenant("owner")
        self.headers = self._headers(self.tenant, "owner")
        self.other_tenant = self._tenant("other")
        self.other_headers = self._headers(self.other_tenant, "other")

    def _tenant(self, name):
        return Tenant.objects.create(name=f"open-rag-run-{name}", api_key=f"key-{name}")

    def _headers(self, tenant, name):
        user = User.objects.create(
            username=f"open-rag-run-{name}",
            email=f"open-rag-run-{name}@example.test",
            password_hash="unused",
            tenant=tenant,
        )
        token = AuthToken.objects.create(
            user=user,
            token=f"open-rag-run-token-{name}",
            token_type="access",
            expires_at="2099-01-01T00:00:00Z",
        )
        return {"HTTP_AUTHORIZATION": f"Bearer {token.token}"}

    def _post(self, path, payload, headers=None):
        return self.client.post(
            path,
            data=json.dumps(payload),
            content_type="application/json",
            **(headers or self.headers),
        )

    def _payload(self, **overrides):
        payload = {
            "open_dataset_id": "open_rag_benchmark",
            "dataset_version": "arxiv-v1",
            "sample_size": 180,
            "seed": 20260819,
            "retrieval_strategy": "hybrid",
            "chunking_strategies": [
                "fixed_window",
                "recursive",
                "auto_parent_child",
                "semantic_parent_child",
            ],
            "eval_llm_model": "",
        }
        payload.update(overrides)
        return payload

    def _v2_payload(self, **overrides):
        payload = {
            "source": {
                "type": "open_dataset",
                "dataset_id": "open_rag_benchmark_100",
                "dataset_version": "arxiv-v1",
            },
            "retrieval_strategy": "hybrid",
            "rerank_enabled": True,
            "chunking_strategies": ["auto_parent_child"],
            "answer_model_id": "answer-model",
            "judge_model_id": "judge-model",
        }
        payload.update(overrides)
        return payload

    @patch("personal_knowledge_base.eval_views.enqueue")
    @patch("personal_knowledge_base.eval_views.open_dataset_status")
    def test_unified_run_accepts_v2_contract_and_separates_models(self, status, enqueue):
        status.return_value = {"ready": True, "status": "ready"}
        for model_id in ("answer-model", "judge-model"):
            ModelConfig.objects.create(
                id=model_id,
                tenant=self.tenant,
                name=model_id,
                type="KnowledgeQA",
                source="openai",
                parameters={},
            )
        enqueue.return_value = SimpleNamespace(
            id="unified-run", status="pending", progress=0, payload={}, result={}
        )

        response = self._post("/api/v1/rag-eval/runs", self._v2_payload())

        self.assertEqual(response.status_code, 202)
        task_payload = enqueue.call_args.args[2]
        self.assertEqual(task_payload["source"]["type"], "open_dataset")
        self.assertEqual(task_payload["sample_size"], 180)
        self.assertEqual(task_payload["chunking_strategies"], ["auto_parent_child"])
        self.assertEqual(task_payload["answer_model_id"], "answer-model")
        self.assertEqual(task_payload["judge_model_id"], "judge-model")
        self.assertTrue(task_payload["rerank_enabled"])

    def test_unified_status_uses_metrics_rag_contract(self):
        record = TaskRecord.objects.create(
            task_type="open_rag_evaluation",
            status="completed",
            progress=1,
            payload={"tenant_id": self.tenant.id, "sample_size": 100},
            result={
                "partial_metrics": {
                    "retrieval": {"hit_at_10": 0.8},
                    "chunking": {"verified": True},
                    "ragas": {"faithfulness": 0.7},
                },
                "verified": True,
            },
        )

        response = self.client.get(f"/api/v1/rag-eval/runs/{record.id}", **self.headers)

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["metrics"]["rag"]["faithfulness"], 0.7)
        self.assertNotIn("ragas", data["metrics"])

    def test_unified_status_exposes_real_question_progress_and_eta(self):
        record = TaskRecord.objects.create(
            task_type="open_rag_evaluation",
            status="running",
            progress=0.25,
            payload={"tenant_id": self.tenant.id, "sample_size": 100},
            result={
                "stage": "retrieval",
                "progress": 0.25,
                "stage_progress": 0.4,
                "completed_questions": 40,
                "total_questions": 100,
                "failed_questions": 3,
                "valid_coverage": 0.925,
                "partial_metrics": {},
            },
        )

        response = self.client.get(f"/api/v1/rag-eval/runs/{record.id}", **self.headers)

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["completed_questions"], 40)
        self.assertEqual(data["total_questions"], 100)
        self.assertEqual(data["failed_questions"], 3)
        self.assertEqual(data["valid_coverage"], 0.925)
        self.assertGreaterEqual(data["elapsed_seconds"], 0)
        self.assertIsNotNone(data["eta_seconds"])

    def test_cancel_immediately_publishes_stop_and_resume_reuses_run_id(self):
        record = TaskRecord.objects.create(
            task_type="open_rag_evaluation",
            status="running",
            progress=0.4,
            queue_name="evaluation",
            payload={"tenant_id": self.tenant.id, "sample_size": 100},
        )

        cancelled = self._post(f"/api/v1/rag-eval/runs/{record.id}/cancel", {})
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["data"]["status"], "cancelled")
        record.refresh_from_db()
        self.assertEqual(record.status, "cancelled")
        self.assertIsNotNone(record.cancel_requested_at)
        self.assertEqual(record.claimed_by, "")
        self.assertIsNone(record.lease_expires_at)

        resumed = self._post(f"/api/v1/rag-eval/runs/{record.id}/resume", {})
        self.assertEqual(resumed.status_code, 202)
        self.assertEqual(resumed.json()["data"]["run_id"], record.id)
        record.refresh_from_db()
        self.assertEqual(record.status, "pending")
        self.assertIsNone(record.cancel_requested_at)

    def test_cancel_stops_pending_run_before_worker_claims_it(self):
        record = TaskRecord.objects.create(
            task_type="open_rag_evaluation",
            status="pending",
            queue_name="evaluation",
            payload={"tenant_id": self.tenant.id, "sample_size": 100},
        )

        response = self._post(f"/api/v1/rag-eval/runs/{record.id}/cancel", {})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], "cancelled")
        record.refresh_from_db()
        self.assertEqual(record.status, "cancelled")
        self.assertIsNotNone(record.cancel_requested_at)

    def test_cancelled_worker_token_stays_cancelled_after_immediate_resume(self):
        from .tasks import _open_rag_cancelled

        record = TaskRecord.objects.create(
            task_type="open_rag_evaluation",
            status="running",
            queue_name="evaluation",
            claimed_by="new-worker",
            payload={"tenant_id": self.tenant.id, "_worker_token": "new-worker"},
        )

        self.assertTrue(_open_rag_cancelled(record.id, "old-worker"))
        self.assertFalse(_open_rag_cancelled(record.id, "new-worker"))

    def test_active_lookup_restores_latest_resumable_run(self):
        record = TaskRecord.objects.create(
            task_type="open_rag_evaluation",
            status="partial",
            progress=0.8,
            payload={"tenant_id": self.tenant.id, "sample_size": 100},
            result={"stage": "ragas", "partial_metrics": {"retrieval": {"verified": True}}},
        )

        response = self.client.get("/api/v1/rag-eval/runs?active=true", **self.headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["active_run"]["run_id"], record.id)
        self.assertEqual(response.json()["data"]["active_run"]["status"], "partial")

    def test_unified_tenant_source_requires_published_evaluation_v2(self):
        kb = KnowledgeBase.objects.create(name="kb", tenant=self.tenant)
        dataset = GenericResource.objects.create(
            tenant=self.tenant,
            resource_type="rag_eval_datasets",
            name="draft",
            status="draft",
            data={"schema_version": "evaluation_v2", "entries": []},
        )
        response = self._post(
            "/api/v1/rag-eval/runs",
            self._v2_payload(source={
                "type": "tenant_dataset",
                "dataset_id": dataset.id,
                "knowledge_base_id": kb.id,
            }, answer_model_id="", judge_model_id=""),
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "dataset_not_published")

    def test_soft_deleted_or_inactive_models_are_rejected(self):
        from django.utils import timezone

        inactive = ModelConfig.objects.create(
            id="inactive-chat", tenant=self.tenant, name="inactive", type="KnowledgeQA",
            source="openai", status="inactive",
        )
        deleted = ModelConfig.objects.create(
            id="deleted-chat", tenant=self.tenant, name="deleted", type="KnowledgeQA",
            source="openai", status="active", deleted_at=timezone.now(),
        )
        for model in (inactive, deleted):
            response = self._post(
                "/api/v1/rag-eval/runs",
                self._v2_payload(answer_model_id=model.id, judge_model_id=""),
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["error"]["code"], "invalid_configuration")

    def test_unified_tenant_source_must_match_dataset_knowledge_base(self):
        dataset_kb = KnowledgeBase.objects.create(name="dataset-kb", tenant=self.tenant)
        requested_kb = KnowledgeBase.objects.create(name="requested-kb", tenant=self.tenant)
        dataset = GenericResource.objects.create(
            tenant=self.tenant,
            resource_type="rag_eval_datasets",
            name="published",
            status="published",
            data={
                "schema_version": "evaluation_v2",
                "knowledge_base_id": dataset_kb.id,
                "dataset_hash": "hash",
                "entries": [{"id": "q1"}],
            },
        )

        response = self._post(
            "/api/v1/rag-eval/runs",
            self._v2_payload(source={
                "type": "tenant_dataset",
                "dataset_id": dataset.id,
                "knowledge_base_id": requested_kb.id,
            }, answer_model_id="", judge_model_id=""),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_configuration")

    @patch("personal_knowledge_base.eval_views.enqueue")
    @patch("personal_knowledge_base.eval_views.open_dataset_status")
    def test_create_open_run_returns_background_task_with_default_subset(self, status, enqueue):
        status.return_value = {"ready": True, "status": "ready"}
        enqueue.return_value = SimpleNamespace(id="run-100", status="pending")

        response = self._post("/api/v1/rag-eval/open-runs", self._payload())

        self.assertEqual(response.status_code, 202)
        data = response.json()["data"]
        self.assertEqual(data["run_id"], "run-100")
        self.assertEqual(data["status"], "queued")
        self.assertEqual(data["sample_size"], 180)
        self.assertEqual(enqueue.call_args.args[0], "open_rag_evaluation")
        payload = enqueue.call_args.args[2]
        self.assertEqual(payload["tenant_id"], self.tenant.id)
        self.assertEqual(payload["sample_size"], 180)
        self.assertTrue(payload["configuration_fingerprint"])

    @patch("personal_knowledge_base.eval_views.enqueue")
    @patch("personal_knowledge_base.eval_views.open_dataset_status")
    def test_same_tenant_and_configuration_reuses_active_run(self, status, enqueue):
        status.return_value = {"ready": True, "status": "ready"}
        existing = TaskRecord.objects.create(
            task_type="open_rag_evaluation",
            status="running",
            payload={
                "tenant_id": self.tenant.id,
                "configuration_fingerprint": "will-be-replaced-by-request",
            },
        )
        # The API must compute the fingerprint from the complete configuration,
        # not merely trust a caller-provided value.
        first = self._post("/api/v1/rag-eval/open-runs", self._payload())
        self.assertEqual(first.status_code, 202)
        fingerprint = enqueue.call_args.args[2]["configuration_fingerprint"]
        TaskRecord.objects.filter(id=existing.id).update(payload={
            "tenant_id": self.tenant.id,
            "configuration_fingerprint": fingerprint,
            "sample_size": 100,
        })
        enqueue.reset_mock()

        second = self._post("/api/v1/rag-eval/open-runs", self._payload())

        self.assertEqual(second.status_code, 202)
        self.assertEqual(second.json()["data"]["run_id"], existing.id)
        enqueue.assert_not_called()

    def test_status_and_cancel_are_tenant_scoped(self):
        record = TaskRecord.objects.create(
            task_type="open_rag_evaluation",
            status="running",
            progress=0.42,
            payload={
                "tenant_id": self.tenant.id,
                "sample_size": 100,
                "stage": "chunking",
                "stage_progress": 0.5,
                "completed_stages": ["retrieval"],
            },
            result={"partial_metrics": {"retrieval": {"hit_at_10_new": 0.5}}},
        )

        foreign_status = self.client.get(f"/api/v1/rag-eval/open-runs/{record.id}", **self.other_headers)
        foreign_cancel = self._post(f"/api/v1/rag-eval/open-runs/{record.id}/cancel", {}, self.other_headers)
        own_status = self.client.get(f"/api/v1/rag-eval/open-runs/{record.id}", **self.headers)
        own_cancel = self._post(f"/api/v1/rag-eval/open-runs/{record.id}/cancel", {})

        self.assertEqual(foreign_status.status_code, 404)
        self.assertEqual(foreign_cancel.status_code, 404)
        self.assertEqual(own_status.status_code, 200)
        data = own_status.json()["data"]
        self.assertEqual(data["stage"], "chunking")
        self.assertEqual(data["completed_stages"], ["retrieval"])
        self.assertEqual(data["partial_metrics"]["retrieval"]["hit_at_10_new"], 0.5)
        self.assertEqual(own_cancel.status_code, 200)
        record.refresh_from_db()
        self.assertEqual(record.status, "cancelled")
