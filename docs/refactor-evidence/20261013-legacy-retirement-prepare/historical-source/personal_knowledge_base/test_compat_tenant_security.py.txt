import json
from unittest.mock import patch

from django.test import TestCase

from personal_knowledge_base.authentication import issue_tokens
from personal_knowledge_base.models import Chunk, Knowledge, KnowledgeBase, TaskRecord, Tenant, User


class MountedCompatibilityTenantSecurityTests(TestCase):
    def setUp(self):
        self.tenant_a = Tenant.objects.create(name="tenant-a", api_key="tenant-a-key")
        self.tenant_b = Tenant.objects.create(name="tenant-b", api_key="tenant-b-key")
        self.headers_a = self.headers_for(self.tenant_a, "tenant-a-user", "tenant-a@example.com")
        self.headers_b = self.headers_for(self.tenant_b, "tenant-b-user", "tenant-b@example.com")
        self.kb_a, self.doc_a, self.chunk_a = self.create_resources(self.tenant_a, "tenant-a")

    def headers_for(self, tenant, username, email):
        user = User.objects.create(username=username, email=email, password_hash="unused", tenant=tenant)
        token, _ = issue_tokens(user)
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def create_resources(self, tenant, prefix):
        kb = KnowledgeBase.objects.create(tenant=tenant, name=f"{prefix}-kb")
        document = Knowledge.objects.create(
            tenant=tenant,
            knowledge_base=kb,
            type="file",
            title=f"{prefix}-document",
            source=f"{prefix}.txt",
        )
        chunk = Chunk.objects.create(
            tenant=tenant,
            knowledge_base=kb,
            knowledge=document,
            content=f"{prefix} chunk",
            chunk_index=0,
        )
        return kb, document, chunk

    def test_mounted_compatibility_routes_require_tenant_access(self):
        unauthenticated_urls = [
            f"/api/v1/chunks/by-id/{self.chunk_a.id}/questions",
            f"/api/v1/initialization/config/{self.kb_a.id}",
            f"/api/v1/initialization/initialize/{self.kb_a.id}",
        ]
        for url in unauthenticated_urls:
            with self.subTest(unauthenticated=url):
                self.assertEqual(self.client.get(url).status_code, 401)

        foreign_kb, foreign_doc, foreign_chunk = self.create_resources(self.tenant_b, "foreign-question")
        question_url = f"/api/v1/chunks/by-id/{foreign_chunk.id}/questions"
        for method, payload in [("get", None), ("put", {"content": "foreign write"}), ("delete", None)]:
            with self.subTest(route="questions", method=method):
                kwargs = {**self.headers_a}
                if payload is not None:
                    kwargs.update(data=json.dumps(payload), content_type="application/json")
                self.assertEqual(getattr(self.client, method)(question_url, **kwargs).status_code, 404)
                foreign_chunk.refresh_from_db()
                self.assertEqual(foreign_chunk.content, "foreign-question chunk")

        for route in ["config", "initialize"]:
            for method, payload in [("get", None), ("put", {"name": "foreign rename"}), ("delete", None)]:
                foreign_kb, _, _ = self.create_resources(self.tenant_b, f"foreign-{route}-{method}")
                url = f"/api/v1/initialization/{route}/{foreign_kb.id}"
                with self.subTest(route=route, method=method):
                    kwargs = {**self.headers_a}
                    if payload is not None:
                        kwargs.update(data=json.dumps(payload), content_type="application/json")
                    self.assertEqual(getattr(self.client, method)(url, **kwargs).status_code, 404)
                    foreign_kb.refresh_from_db()
                    self.assertEqual(foreign_kb.name, f"foreign-{route}-{method}-kb")
                    self.assertIsNone(foreign_kb.deleted_at)

    def test_mounted_compatibility_routes_preserve_owner_behavior(self):
        question_url = f"/api/v1/chunks/by-id/{self.chunk_a.id}/questions"
        response = self.client.get(question_url, **self.headers_a)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["id"], self.chunk_a.id)

        with patch("knowledge.views.index_chunk"):
            update = self.client.put(
                question_url,
                data=json.dumps({"content": "owner updated chunk"}),
                content_type="application/json",
                **self.headers_a,
            )
        self.assertEqual(update.status_code, 200)
        self.chunk_a.refresh_from_db()
        self.assertEqual(self.chunk_a.content, "owner updated chunk")

        delete = self.client.delete(question_url, **self.headers_a)
        self.assertEqual(delete.status_code, 200)
        self.assertFalse(Chunk.objects.filter(id=self.chunk_a.id).exists())

        config = self.client.get(f"/api/v1/initialization/config/{self.kb_a.id}", **self.headers_a)
        self.assertEqual(config.status_code, 200)
        self.assertEqual(config.json()["data"]["knowledge_base"]["id"], self.kb_a.id)

        update = self.client.put(
            f"/api/v1/initialization/initialize/{self.kb_a.id}",
            data=json.dumps({"name": "owner initialized kb"}),
            content_type="application/json",
            **self.headers_a,
        )
        self.assertEqual(update.status_code, 200)
        self.kb_a.refresh_from_db()
        self.assertEqual(self.kb_a.name, "owner initialized kb")

    def test_task_progress_routes_require_the_payload_document_tenant(self):
        owner_task = TaskRecord.objects.create(
            task_type="process_knowledge",
            payload={"knowledge_id": self.doc_a.id},
            status="running",
            progress=42,
        )
        routes = [
            f"/api/v1/knowledge-bases/copy/progress/{owner_task.id}",
            f"/api/v1/knowledge/move/progress/{owner_task.id}",
        ]
        for route in routes:
            with self.subTest(owner=route):
                response = self.client.get(route, **self.headers_a)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["data"]["status"], "running")
            with self.subTest(unauthenticated=route):
                self.assertEqual(self.client.get(route).status_code, 401)

        foreign_kb, foreign_doc, _ = self.create_resources(self.tenant_b, "foreign-task")
        foreign_task = TaskRecord.objects.create(
            task_type="process_knowledge",
            payload={"knowledge_id": foreign_doc.id},
            status="completed",
        )
        unresolved_task = TaskRecord.objects.create(task_type="process_knowledge", payload={})
        for task_id in [foreign_task.id, unresolved_task.id, "missing-task"]:
            for prefix in ["knowledge-bases/copy/progress", "knowledge/move/progress"]:
                with self.subTest(task_id=task_id, route=prefix):
                    response = self.client.get(f"/api/v1/{prefix}/{task_id}", **self.headers_a)
                    self.assertEqual(response.status_code, 404)

    def test_question_compatibility_rejects_chunk_with_foreign_knowledge_base(self):
        foreign_kb = KnowledgeBase.objects.create(tenant=self.tenant_b, name="foreign-kb")
        inconsistent_doc = Knowledge.objects.create(
            tenant=self.tenant_a,
            knowledge_base=foreign_kb,
            type="file",
            title="tenant-a document on tenant-b kb",
            source="inconsistent.txt",
        )
        inconsistent_chunk = Chunk.objects.create(
            tenant=self.tenant_a,
            knowledge_base=foreign_kb,
            knowledge=inconsistent_doc,
            content="inconsistent chunk",
            chunk_index=0,
        )
        url = f"/api/v1/chunks/by-id/{inconsistent_chunk.id}/questions"
        for method, payload in [("get", None), ("put", {"content": "should not update"})]:
            with self.subTest(method=method):
                kwargs = {**self.headers_a}
                if payload is not None:
                    kwargs.update(data=json.dumps(payload), content_type="application/json")
                self.assertEqual(getattr(self.client, method)(url, **kwargs).status_code, 404)
                inconsistent_chunk.refresh_from_db()
                self.assertEqual(inconsistent_chunk.content, "inconsistent chunk")
        with patch("knowledge.views.delete_knowledge_graph") as delete_graph:
            self.assertEqual(self.client.delete(url, **self.headers_a).status_code, 404)
        delete_graph.assert_not_called()
        self.assertTrue(Chunk.objects.filter(id=inconsistent_chunk.id).exists())
