import json
from unittest.mock import patch

from django.test import TestCase

from .authentication import issue_tokens
from .eval_reports import save_evaluation_report
from .models import GenericResource, Tenant, User


class EvaluationReportTests(TestCase):
    def setUp(self):
        self.tenant_a = Tenant.objects.create(name="tenant-a", api_key="report-a")
        self.tenant_b = Tenant.objects.create(name="tenant-b", api_key="report-b")
        user_a = User.objects.create(
            username="report-a",
            email="report-a@example.com",
            password_hash="unused",
            tenant=self.tenant_a,
        )
        user_b = User.objects.create(
            username="report-b",
            email="report-b@example.com",
            password_hash="unused",
            tenant=self.tenant_b,
        )
        token_a, _ = issue_tokens(user_a)
        token_b, _ = issue_tokens(user_b)
        self.headers_a = {"HTTP_AUTHORIZATION": f"Bearer {token_a}"}
        self.headers_b = {"HTTP_AUTHORIZATION": f"Bearer {token_b}"}

    @patch("personal_knowledge_base.eval_reports._git_commit", return_value="abc123")
    def test_report_download_is_tenant_scoped(self, _commit):
        metadata = save_evaluation_report(
            tenant=self.tenant_a,
            evaluation_type="retrieval",
            evaluator="deterministic",
            verified=True,
            dataset=[{"query": "q", "evidence": [{"source_start": 0, "source_end": 1}]}],
            result={"hit_at_10_new": 1.0, "content": "private source document", "api_key": "secret"},
            configuration={"rerank_model": "bge-reranker"},
        )

        own = self.client.get(metadata["report_url"], **self.headers_a)
        self.assertEqual(own.status_code, 200)
        self.assertIn("attachment", own.headers["Content-Disposition"])
        report = json.loads(own.content)
        self.assertEqual(report["run_id"], metadata["run_id"])
        self.assertEqual(report["provenance"]["git_commit"], "abc123")
        self.assertEqual(report["dataset"]["entries"], 1)
        self.assertNotIn("query", json.dumps(report))
        self.assertNotIn("private source document", json.dumps(report))
        self.assertNotIn("secret", json.dumps(report))

        foreign = self.client.get(metadata["report_url"], **self.headers_b)
        self.assertEqual(foreign.status_code, 404)

    @patch("personal_knowledge_base.eval_reports._git_commit", return_value="abc123")
    def test_only_latest_fifty_reports_are_retained_per_tenant(self, _commit):
        run_ids = []
        for index in range(51):
            metadata = save_evaluation_report(
                tenant=self.tenant_a,
                evaluation_type="retrieval",
                evaluator="deterministic",
                verified=False,
                dataset=[{"query": str(index)}],
                result={"verified": False},
            )
            run_ids.append(metadata["run_id"])

        reports = GenericResource.objects.filter(
            tenant=self.tenant_a,
            resource_type="rag_eval_runs",
            deleted_at__isnull=True,
        )
        self.assertEqual(reports.count(), 50)
        self.assertFalse(reports.filter(id=run_ids[0]).exists())
        self.assertTrue(reports.filter(id=run_ids[-1]).exists())
