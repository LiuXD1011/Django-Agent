import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from personal_knowledge_base.authentication import issue_tokens
from personal_knowledge_base.graph_rag import delete_kb_graph
from personal_knowledge_base.models import (
    Chunk,
    Knowledge,
    KnowledgeBase,
    KnowledgeImage,
    KnowledgeTag,
    Tenant,
    User,
    WikiFolder,
    WikiLogEntry,
    WikiPage,
    WikiPendingOp,
)


class KnowledgeTenantChildRowTests(TestCase):
    def setUp(self):
        self.tenant_a = Tenant.objects.create(name="tenant-a", api_key="tenant-a-key")
        self.tenant_b = Tenant.objects.create(name="tenant-b", api_key="tenant-b-key")
        user_a = User.objects.create(
            username="tenant-a-user",
            email="tenant-a@example.com",
            password_hash="unused",
            tenant=self.tenant_a,
        )
        token_a, _ = issue_tokens(user_a)
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {token_a}"}
        self.kb = KnowledgeBase.objects.create(tenant=self.tenant_a, name="tenant-a-kb")
        self.target_kb = KnowledgeBase.objects.create(tenant=self.tenant_a, name="tenant-a-target")
        self.local_tag = KnowledgeTag.objects.create(tenant=self.tenant_a, knowledge_base=self.kb, name="tenant-a-tag")
        self.local_doc = Knowledge.objects.create(
            tenant=self.tenant_a,
            knowledge_base=self.kb,
            type="file",
            title="tenant-a-document",
            source="tenant-a.txt",
            parse_status="completed",
            tag_id=self.local_tag.id,
        )
        self.local_chunk = Chunk.objects.create(
            tenant=self.tenant_a,
            knowledge_base=self.kb,
            knowledge=self.local_doc,
            content="tenant-a chunk",
            chunk_index=0,
        )
        self.foreign_doc = Knowledge.objects.create(
            tenant=self.tenant_b,
            knowledge_base=self.kb,
            type="file",
            title="tenant-b document on tenant-a kb",
            source="tenant-b.txt",
            parse_status="pending",
            tag_id="tenant-b-tag",
        )
        self.foreign_chunk = Chunk.objects.create(
            tenant=self.tenant_b,
            knowledge_base=self.kb,
            knowledge=self.local_doc,
            content="tenant-b child chunk",
            chunk_index=1,
        )
        self.foreign_image = KnowledgeImage.objects.create(
            tenant=self.tenant_b,
            knowledge_base=self.kb,
            knowledge=self.local_doc,
            content_hash="foreign-image-hash",
            storage_path="tenant-b/foreign-image.png",
            source_type="test",
        )
        self.foreign_page = WikiPage.objects.create(
            tenant=self.tenant_b,
            knowledge_base=self.kb,
            slug="tenant-b-legacy-page",
            title="tenant-b legacy page",
        )
        self.foreign_folder = WikiFolder.objects.create(
            tenant=self.tenant_b,
            knowledge_base=self.kb,
            name="tenant-b legacy folder",
        )
        self.foreign_pending_op = WikiPendingOp.objects.create(
            tenant=self.tenant_b,
            scope_id=self.kb.id,
            op="ingest",
        )
        self.foreign_log = WikiLogEntry.objects.create(
            tenant=self.tenant_b,
            knowledge_base=self.kb,
            action="ingest",
            doc_title="tenant-b legacy log",
        )

    def assert_foreign_children_unchanged(self):
        foreign_doc = Knowledge.objects.filter(id=self.foreign_doc.id).first()
        foreign_chunk = Chunk.objects.filter(id=self.foreign_chunk.id).first()
        foreign_image = KnowledgeImage.objects.filter(id=self.foreign_image.id).first()
        foreign_page = WikiPage.objects.filter(id=self.foreign_page.id).first()
        foreign_folder = WikiFolder.objects.filter(id=self.foreign_folder.id).first()
        foreign_pending_op = WikiPendingOp.objects.filter(id=self.foreign_pending_op.id).first()
        foreign_log = WikiLogEntry.objects.filter(id=self.foreign_log.id).first()
        with self.subTest(child="knowledge"):
            self.assertIsNotNone(foreign_doc)
        with self.subTest(child="chunk"):
            self.assertIsNotNone(foreign_chunk)
        with self.subTest(child="image"):
            self.assertIsNotNone(foreign_image)
        with self.subTest(child="wiki page"):
            self.assertIsNotNone(foreign_page)
        with self.subTest(child="wiki folder"):
            self.assertIsNotNone(foreign_folder)
        with self.subTest(child="wiki pending op"):
            self.assertIsNotNone(foreign_pending_op)
        with self.subTest(child="wiki log"):
            self.assertIsNotNone(foreign_log)
        if foreign_doc:
            self.assertIsNone(foreign_doc.deleted_at)
            self.assertEqual(foreign_doc.tenant_id, self.tenant_b.id)
        if foreign_chunk:
            self.assertEqual(foreign_chunk.tenant_id, self.tenant_b.id)
            self.assertEqual(foreign_chunk.knowledge_base_id, self.kb.id)
        if foreign_image:
            self.assertEqual(foreign_image.tenant_id, self.tenant_b.id)
            self.assertEqual(foreign_image.knowledge_base_id, self.kb.id)
        if foreign_page:
            self.assertEqual(foreign_page.tenant_id, self.tenant_b.id)
            self.assertEqual(foreign_page.knowledge_base_id, self.kb.id)
        if foreign_folder:
            self.assertEqual(foreign_folder.tenant_id, self.tenant_b.id)
            self.assertEqual(foreign_folder.knowledge_base_id, self.kb.id)
        if foreign_pending_op:
            self.assertEqual(foreign_pending_op.tenant_id, self.tenant_b.id)
            self.assertEqual(foreign_pending_op.scope_id, self.kb.id)
        if foreign_log:
            self.assertEqual(foreign_log.tenant_id, self.tenant_b.id)
            self.assertEqual(foreign_log.knowledge_base_id, self.kb.id)

    def test_collection_aggregates_stats_and_dedupe_ignore_inconsistent_child_rows(self):
        response = self.client.get(f"/api/v1/knowledge-bases/{self.kb.id}/knowledge", **self.headers)

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual([item["id"] for item in data["items"]], [self.local_doc.id])
        self.assertEqual({item["id"] for item in data["processing_records"]}, {self.local_doc.id})
        self.assertEqual(data["status_counts"], {"completed": 1})
        self.assertEqual(data["tag_counts"], {self.local_tag.id: 1})

        knowledge_base = self.client.get(f"/api/v1/knowledge-bases/{self.kb.id}", **self.headers)
        self.assertEqual(knowledge_base.status_code, 200)
        summary = knowledge_base.json()["data"]
        self.assertEqual(summary["knowledge_count"], 1)
        self.assertEqual(summary["document_count"], 1)
        self.assertEqual(summary["chunk_count"], 1)
        self.assertEqual(summary["processing_count"], 0)
        self.assertFalse(summary["is_processing"])

        stats = self.client.get(f"/api/v1/knowledge-bases/{self.kb.id}/knowledge/stats", **self.headers)
        self.assertEqual(stats.status_code, 200)
        self.assertEqual(stats.json()["data"]["knowledge_count"], 1)
        self.assertEqual(stats.json()["data"]["chunk_count"], 1)

        content = b"duplicate content"
        Knowledge.objects.create(
            tenant=self.tenant_b,
            knowledge_base=self.kb,
            type="file",
            title="tenant-b duplicate",
            source="duplicate.txt",
            file_name="duplicate.txt",
            file_hash=hashlib.sha256(content).hexdigest(),
        )
        with patch("knowledge.views.default_storage.save", return_value="tenant-a/duplicate.txt"), patch(
            "knowledge.views.enqueue", return_value=SimpleNamespace(id="test-task")
        ):
            upload = self.client.post(
                f"/api/v1/knowledge-bases/{self.kb.id}/knowledge/file",
                data={"file": SimpleUploadedFile("duplicate.txt", content, content_type="text/plain")},
                **self.headers,
            )
        self.assertEqual(upload.status_code, 409)
        self.assertFalse(Knowledge.objects.filter(tenant=self.tenant_a, knowledge_base=self.kb, file_name="duplicate.txt").exists())

    def test_collection_and_batch_delete_leave_inconsistent_tenant_b_children_untouched(self):
        response = self.client.delete(f"/api/v1/knowledge-bases/{self.kb.id}/knowledge", **self.headers)
        self.assert_foreign_children_unchanged()
        self.assertEqual(response.status_code, 200)

    def test_batch_delete_and_move_leave_inconsistent_tenant_b_children_untouched(self):
        delete = self.client.post(
            "/api/v1/knowledge/batch-delete",
            data=json.dumps({"ids": [self.local_doc.id], "source_kb_id": self.kb.id}),
            content_type="application/json",
            **self.headers,
        )
        self.assert_foreign_children_unchanged()
        self.assertEqual(delete.status_code, 200)

        local_doc = Knowledge.objects.create(
            tenant=self.tenant_a,
            knowledge_base=self.kb,
            type="file",
            title="tenant-a move document",
            source="move.txt",
        )
        foreign_chunk = Chunk.objects.create(
            tenant=self.tenant_b,
            knowledge_base=self.kb,
            knowledge=local_doc,
            content="tenant-b move chunk",
            chunk_index=0,
        )
        foreign_image = KnowledgeImage.objects.create(
            tenant=self.tenant_b,
            knowledge_base=self.kb,
            knowledge=local_doc,
            content_hash="foreign-move-image-hash",
            storage_path="tenant-b/foreign-move-image.png",
            source_type="test",
        )
        move = self.client.post(
            "/api/v1/knowledge/move",
            data=json.dumps({"ids": [local_doc.id], "source_kb_id": self.kb.id, "target_kb_id": self.target_kb.id}),
            content_type="application/json",
            **self.headers,
        )
        foreign_chunk.refresh_from_db()
        foreign_image.refresh_from_db()
        self.assertEqual(foreign_chunk.tenant_id, self.tenant_b.id)
        self.assertEqual(foreign_chunk.knowledge_base_id, self.kb.id)
        self.assertEqual(foreign_image.tenant_id, self.tenant_b.id)
        self.assertEqual(foreign_image.knowledge_base_id, self.kb.id)
        self.assertEqual(move.status_code, 200)

    def test_preview_chunk_and_image_helpers_exclude_inconsistent_tenant_b_children(self):
        chunks = self.client.get(f"/api/v1/chunks/{self.local_doc.id}", **self.headers)
        self.assertEqual(chunks.status_code, 200)
        self.assertEqual([item["id"] for item in chunks.json()["data"]["items"]], [self.local_chunk.id])

        preview = self.client.get(f"/api/v1/knowledge/{self.local_doc.id}/preview", **self.headers)
        self.assertEqual(preview.status_code, 200)
        self.assertIn(b"tenant-a chunk", preview.content)
        self.assertNotIn(b"tenant-b child chunk", preview.content)

        image = self.client.get(
            f"/api/v1/knowledge/{self.local_doc.id}/images/{self.foreign_image.id}",
            **self.headers,
        )
        self.assertEqual(image.status_code, 404)

    def test_delete_kb_graph_excludes_inconsistent_tenant_b_documents(self):
        with patch("personal_knowledge_base.graph_rag.graph_repository.delete_graph") as delete_graph:
            delete_kb_graph(self.kb)

        namespaces = delete_graph.call_args.args[0]
        self.assertEqual(
            [(namespace.knowledge_base_id, namespace.knowledge_id) for namespace in namespaces],
            [(self.kb.id, self.local_doc.id)],
        )

    def test_direct_chunk_routes_reject_inconsistent_or_deleted_parents_before_graph_cleanup(self):
        foreign_kb = KnowledgeBase.objects.create(tenant=self.tenant_b, name="tenant-b-kb")
        foreign_kb_doc = Knowledge.objects.create(
            tenant=self.tenant_a,
            knowledge_base=foreign_kb,
            type="file",
            title="tenant-a document on tenant-b kb",
            source="foreign-kb.txt",
        )
        deleted_doc = Knowledge.objects.create(
            tenant=self.tenant_a,
            knowledge_base=self.kb,
            type="file",
            title="deleted document",
            source="deleted.txt",
            deleted_at=timezone.now(),
        )
        scenarios = [
            (self.foreign_doc, self.kb, "tenant-b document"),
            (foreign_kb_doc, foreign_kb, "tenant-b kb"),
            (deleted_doc, self.kb, "deleted document"),
        ]
        for knowledge, knowledge_base, label in scenarios:
            for route_kind in ["by-id", "knowledge-id"]:
                for method in ["get", "put", "delete"]:
                    chunk = Chunk.objects.create(
                        tenant=self.tenant_a,
                        knowledge_base=knowledge_base,
                        knowledge=knowledge,
                        content=f"tenant-a chunk on {label}",
                        chunk_index=0,
                    )
                    url = (
                        f"/api/v1/chunks/by-id/{chunk.id}"
                        if route_kind == "by-id"
                        else f"/api/v1/chunks/{chunk.knowledge_id}/{chunk.id}"
                    )
                    with self.subTest(chunk=chunk.id, method=method, url=url):
                        kwargs = {**self.headers}
                        if method == "put":
                            kwargs.update(data=json.dumps({"content": "should not update"}), content_type="application/json")
                        with patch("knowledge.views.delete_knowledge_graph") as delete_graph:
                            response = getattr(self.client, method)(url, **kwargs)
                        self.assertEqual(response.status_code, 404)
                        delete_graph.assert_not_called()
                        chunk.refresh_from_db()
                        self.assertNotEqual(chunk.content, "should not update")
