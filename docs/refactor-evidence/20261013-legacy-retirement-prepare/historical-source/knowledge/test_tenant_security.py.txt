import io
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from personal_knowledge_base.authentication import issue_tokens
from personal_knowledge_base.models import Chunk, Knowledge, KnowledgeBase, KnowledgeImage, KnowledgeTag, Tenant, User


class KnowledgeTenantSecurityTests(TestCase):
    def setUp(self):
        self.tenant_a = Tenant.objects.create(name="tenant-a", api_key="tenant-a-key")
        self.tenant_b = Tenant.objects.create(name="tenant-b", api_key="tenant-b-key")
        self.user_b = User.objects.create(
            username="tenant-b-user",
            email="tenant-b@example.com",
            password_hash="unused",
            tenant=self.tenant_b,
        )
        token_b, _ = issue_tokens(self.user_b)
        self.tenant_b_headers = {"HTTP_AUTHORIZATION": f"Bearer {token_b}"}
        self.user_a = User.objects.create(
            username="tenant-a-user",
            email="tenant-a@example.com",
            password_hash="unused",
            tenant=self.tenant_a,
        )
        token_a, _ = issue_tokens(self.user_a)
        self.tenant_a_headers = {"HTTP_AUTHORIZATION": f"Bearer {token_a}"}

        self.kb, self.doc, self.chunk, self.tag = self.create_resources()

    def create_resources(self):
        kb = KnowledgeBase.objects.create(tenant=self.tenant_a, name="tenant-a-kb")
        doc = Knowledge.objects.create(
            tenant=self.tenant_a,
            knowledge_base=kb,
            type="file",
            title="tenant-a-document",
            source="tenant-a.txt",
        )
        chunk = Chunk.objects.create(
            tenant=self.tenant_a,
            knowledge_base=kb,
            knowledge=doc,
            content="tenant-a chunk",
            chunk_index=0,
        )
        tag = KnowledgeTag.objects.create(
            tenant=self.tenant_a,
            knowledge_base=kb,
            name="tenant-a-tag",
        )
        return kb, doc, chunk, tag

    def create_document(self, knowledge_base=None, title="tenant-a-document"):
        return Knowledge.objects.create(
            tenant=self.tenant_a,
            knowledge_base=knowledge_base or self.kb,
            type="file",
            title=title,
            source=f"{title}.txt",
        )

    def test_knowledge_resources_reject_unauthenticated_and_cross_tenant_access(self):
        unauthenticated_urls = [
            f"/api/v1/knowledge-bases/{self.kb.id}",
            f"/api/v1/knowledge/{self.doc.id}",
            f"/api/v1/chunks/by-id/{self.chunk.id}",
            f"/api/v1/knowledge-bases/{self.kb.id}/tags/{self.tag.id}",
        ]
        for url in unauthenticated_urls:
            with self.subTest(unauthenticated_url=url):
                self.assertEqual(self.client.get(url).status_code, 401)

        cross_tenant_get_urls = [
            f"/api/v1/knowledge-bases/{self.kb.id}",
            f"/api/v1/knowledge/{self.doc.id}",
            f"/api/v1/chunks/by-id/{self.chunk.id}",
            f"/api/v1/knowledge-bases/{self.kb.id}/tags/{self.tag.id}",
        ]
        for url in cross_tenant_get_urls:
            with self.subTest(cross_tenant_get_url=url):
                self.assertEqual(self.client.get(url, **self.tenant_b_headers).status_code, 404)

        response = self.client.post(
            "/api/v1/knowledge-search",
            data=json.dumps({"knowledge_base_ids": [self.kb.id], "query": "tenant-a"}),
            content_type="application/json",
            **self.tenant_b_headers,
        )
        self.assertEqual(response.status_code, 404)

        writes = [
            ("knowledge base put", "put", lambda kb, doc, chunk, tag: f"/api/v1/knowledge-bases/{kb.id}", {"name": "cross tenant kb"}),
            ("knowledge base delete", "delete", lambda kb, doc, chunk, tag: f"/api/v1/knowledge-bases/{kb.id}", None),
            ("knowledge put", "put", lambda kb, doc, chunk, tag: f"/api/v1/knowledge/{doc.id}", {"title": "cross tenant doc"}),
            ("knowledge delete", "delete", lambda kb, doc, chunk, tag: f"/api/v1/knowledge/{doc.id}", None),
            ("chunk put", "put", lambda kb, doc, chunk, tag: f"/api/v1/chunks/by-id/{chunk.id}", {"content": "cross tenant chunk"}),
            ("chunk delete", "delete", lambda kb, doc, chunk, tag: f"/api/v1/chunks/by-id/{chunk.id}", None),
            ("tag put", "put", lambda kb, doc, chunk, tag: f"/api/v1/knowledge-bases/{kb.id}/tags/{tag.id}", {"name": "cross tenant tag"}),
            ("tag delete", "delete", lambda kb, doc, chunk, tag: f"/api/v1/knowledge-bases/{kb.id}/tags/{tag.id}", None),
        ]
        for label, method, url_for, payload in writes:
            with self.subTest(cross_tenant_write=label):
                kb, doc, chunk, tag = self.create_resources()
                kwargs = {"content_type": "application/json", **self.tenant_b_headers}
                if payload is not None:
                    kwargs["data"] = json.dumps(payload)
                response = getattr(self.client, method)(url_for(kb, doc, chunk, tag), **kwargs)
                self.assertEqual(response.status_code, 404)
                kb = KnowledgeBase.objects.filter(id=kb.id).first()
                doc = Knowledge.objects.filter(id=doc.id).first()
                chunk = Chunk.objects.filter(id=chunk.id).first()
                tag = KnowledgeTag.objects.filter(id=tag.id).first()
                self.assertIsNotNone(kb)
                self.assertIsNotNone(doc)
                self.assertIsNotNone(chunk)
                self.assertIsNotNone(tag)
                if kb and doc and chunk and tag:
                    self.assertEqual(kb.name, "tenant-a-kb")
                    self.assertIsNone(kb.deleted_at)
                    self.assertEqual(doc.title, "tenant-a-document")
                    self.assertIsNone(doc.deleted_at)
                    self.assertEqual(chunk.content, "tenant-a chunk")
                    self.assertEqual(tag.name, "tenant-a-tag")

    def test_batch_routes_reject_every_foreign_or_missing_id_before_mutation(self):
        foreign_kb = KnowledgeBase.objects.create(tenant=self.tenant_b, name="tenant-b-kb")
        foreign_doc = Knowledge.objects.create(
            tenant=self.tenant_b,
            knowledge_base=foreign_kb,
            type="file",
            title="tenant-b-document",
            source="tenant-b.txt",
        )
        target = KnowledgeBase.objects.create(tenant=self.tenant_a, name="tenant-a-target")
        bad_ids = [foreign_doc.id, "missing-knowledge-id"]

        for bad_id in bad_ids:
            local_doc = self.create_document(title=f"batch-read-{bad_id}")
            with self.subTest(route="knowledge batch read", bad_id=bad_id):
                response = self.client.get(
                    f"/api/v1/knowledge/batch?ids={local_doc.id},{bad_id}",
                    **self.tenant_a_headers,
                )
                self.assertEqual(response.status_code, 404)
                local_doc.refresh_from_db()
                self.assertIsNone(local_doc.deleted_at)

        batch_delete_routes = [
            ("/api/v1/knowledge/batch-delete", lambda local_id, bad_id: {"ids": [local_id, bad_id], "source_kb_id": self.kb.id}),
            (f"/api/v1/knowledge-bases/{self.kb.id}/knowledge/batch-delete", lambda local_id, bad_id: {"ids": [local_id, bad_id]}),
        ]
        for url, payload_for in batch_delete_routes:
            for bad_id in bad_ids:
                local_doc = self.create_document(title=f"batch-delete-{bad_id}")
                with self.subTest(route=url, bad_id=bad_id):
                    response = self.client.post(
                        url,
                        data=json.dumps(payload_for(local_doc.id, bad_id)),
                        content_type="application/json",
                        **self.tenant_a_headers,
                    )
                    local_doc.refresh_from_db()
                    self.assertIsNone(local_doc.deleted_at)
                    self.assertEqual(response.status_code, 404)

        move_routes = [
            ("/api/v1/knowledge/move", lambda local_id, bad_id: {"ids": [local_id, bad_id], "source_kb_id": self.kb.id, "target_kb_id": target.id}),
            (f"/api/v1/knowledge-bases/{self.kb.id}/knowledge/move", lambda local_id, bad_id: {"ids": [local_id, bad_id], "target_kb_id": target.id}),
        ]
        for url, payload_for in move_routes:
            for bad_id in bad_ids:
                local_doc = self.create_document(title=f"move-{bad_id}")
                with self.subTest(route=url, bad_id=bad_id):
                    response = self.client.post(
                        url,
                        data=json.dumps(payload_for(local_doc.id, bad_id)),
                        content_type="application/json",
                        **self.tenant_a_headers,
                    )
                    local_doc.refresh_from_db()
                    self.assertEqual(local_doc.knowledge_base_id, self.kb.id)
                    self.assertEqual(response.status_code, 404)

    def test_knowledge_tag_references_must_belong_to_the_current_tenant_and_kb(self):
        foreign_kb = KnowledgeBase.objects.create(tenant=self.tenant_b, name="tenant-b-kb")
        foreign_tag = KnowledgeTag.objects.create(tenant=self.tenant_b, knowledge_base=foreign_kb, name="tenant-b-tag")
        other_kb = KnowledgeBase.objects.create(tenant=self.tenant_a, name="tenant-a-other-kb")
        other_kb_tag = KnowledgeTag.objects.create(tenant=self.tenant_a, knowledge_base=other_kb, name="other-kb-tag")

        for tag_id in [foreign_tag.id, other_kb_tag.id]:
            with self.subTest(operation="update", tag_id=tag_id):
                response = self.client.put(
                    f"/api/v1/knowledge/{self.doc.id}",
                    data=json.dumps({"tag_id": tag_id}),
                    content_type="application/json",
                    **self.tenant_a_headers,
                )
                self.doc.refresh_from_db()
                self.assertEqual(self.doc.tag_id, "")
                self.assertEqual(response.status_code, 404)

            with self.subTest(operation="upload", tag_id=tag_id):
                count_before = Knowledge.objects.filter(tenant=self.tenant_a).count()
                with patch("knowledge.views.enqueue", return_value=SimpleNamespace(id="test-task")):
                    response = self.client.post(
                        f"/api/v1/knowledge-bases/{self.kb.id}/knowledge/file",
                        data={
                            "file": SimpleUploadedFile(f"foreign-tag-{tag_id}.txt", b"content", content_type="text/plain"),
                            "tag_id": tag_id,
                        },
                        **self.tenant_a_headers,
                    )
                self.assertEqual(Knowledge.objects.filter(tenant=self.tenant_a).count(), count_before)
                self.assertEqual(response.status_code, 404)

    def test_direct_knowledge_routes_reject_mismatched_parent_tenant(self):
        foreign_kb = KnowledgeBase.objects.create(tenant=self.tenant_b, name="tenant-b-parent")
        inconsistent_doc = Knowledge.objects.create(
            tenant=self.tenant_a,
            knowledge_base=foreign_kb,
            type="file",
            title="inconsistent-parent-document",
            source="inconsistent.txt",
            metadata={"content": "must not be disclosed"},
        )
        inconsistent_image = KnowledgeImage.objects.create(
            tenant=self.tenant_a,
            knowledge_base=foreign_kb,
            knowledge=inconsistent_doc,
            content_hash="inconsistent-parent-image",
            storage_path="inconsistent-parent/image.png",
            source_type="test",
        )

        requests = [
            ("get", f"/api/v1/knowledge/{inconsistent_doc.id}"),
            ("post", f"/api/v1/knowledge/{inconsistent_doc.id}/reparse"),
            ("post", f"/api/v1/knowledge/{inconsistent_doc.id}/cancel-parse"),
            ("get", f"/api/v1/knowledge/{inconsistent_doc.id}/spans"),
            ("get", f"/api/v1/knowledge/{inconsistent_doc.id}/download"),
            ("get", f"/api/v1/knowledge/{inconsistent_doc.id}/preview"),
            ("get", f"/api/v1/knowledge/{inconsistent_doc.id}/images/{inconsistent_image.id}"),
        ]
        with patch("knowledge.views.prepare_wiki_for_reparse"), patch(
            "knowledge.views.delete_knowledge_content"
        ), patch("knowledge.views.enqueue", return_value=SimpleNamespace(id="test-task")), patch(
            "knowledge.views.default_storage.exists", return_value=True
        ), patch("knowledge.views.default_storage.open", return_value=io.BytesIO(b"secret")):
            for method, url in requests:
                with self.subTest(method=method, url=url):
                    response = getattr(self.client, method)(url, **self.tenant_a_headers)
                    self.assertEqual(response.status_code, 404)

    def test_soft_deleted_tags_are_hidden_and_cannot_be_referenced(self):
        deleted_tag = KnowledgeTag.objects.create(
            tenant=self.tenant_a,
            knowledge_base=self.kb,
            name="deleted-tag",
            deleted_at=timezone.now(),
        )

        listing = self.client.get(f"/api/v1/knowledge-bases/{self.kb.id}/tags", **self.tenant_a_headers)
        self.assertEqual(listing.status_code, 200)
        self.assertNotIn(deleted_tag.id, [item["id"] for item in listing.json()["data"]["items"]])
        detail = self.client.get(
            f"/api/v1/knowledge-bases/{self.kb.id}/tags/{deleted_tag.id}",
            **self.tenant_a_headers,
        )
        self.assertEqual(detail.status_code, 404)

        update = self.client.put(
            f"/api/v1/knowledge-bases/{self.kb.id}/tags/{deleted_tag.id}",
            data=json.dumps({"name": "revived"}),
            content_type="application/json",
            **self.tenant_a_headers,
        )
        self.assertEqual(update.status_code, 404)

        reference = self.client.put(
            f"/api/v1/knowledge/{self.doc.id}",
            data=json.dumps({"tag_id": deleted_tag.id}),
            content_type="application/json",
            **self.tenant_a_headers,
        )
        self.assertEqual(reference.status_code, 404)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.tag_id, "")

    def test_direct_knowledge_routes_reject_soft_deleted_parent(self):
        deleted_parent = KnowledgeBase.objects.create(
            tenant=self.tenant_a,
            name="deleted-parent",
            deleted_at=timezone.now(),
        )
        child = Knowledge.objects.create(
            tenant=self.tenant_a,
            knowledge_base=deleted_parent,
            type="file",
            title="child-of-deleted-parent",
            source="deleted-parent.txt",
        )

        response = self.client.get(f"/api/v1/knowledge/{child.id}", **self.tenant_a_headers)

        self.assertEqual(response.status_code, 404)

    def test_batch_mutations_roll_back_database_state_on_mid_loop_exception(self):
        delete_docs = [self.create_document(title="atomic-delete-one"), self.create_document(title="atomic-delete-two")]
        delete_calls = 0

        def fail_on_second_delete(item):
            nonlocal delete_calls
            delete_calls += 1
            if delete_calls == 2:
                raise RuntimeError("delete failed mid-loop")

        with patch("knowledge.views.delete_knowledge_content", side_effect=fail_on_second_delete):
            with self.assertRaisesRegex(RuntimeError, "delete failed mid-loop"):
                self.client.post(
                    "/api/v1/knowledge/batch-delete",
                    data=json.dumps({"ids": [item.id for item in delete_docs], "source_kb_id": self.kb.id}),
                    content_type="application/json",
                    **self.tenant_a_headers,
                )
        for document in delete_docs:
            document.refresh_from_db()
            self.assertIsNone(document.deleted_at)
            self.assertNotEqual(document.parse_status, "cancelled")

        target = KnowledgeBase.objects.create(tenant=self.tenant_a, name="atomic-move-target")
        move_docs = [self.create_document(title="atomic-move-one"), self.create_document(title="atomic-move-two")]
        for index, document in enumerate(move_docs):
            Chunk.objects.create(
                tenant=self.tenant_a,
                knowledge_base=self.kb,
                knowledge=document,
                content=f"atomic move chunk {index}",
                chunk_index=0,
            )
        index_calls = 0

        def fail_on_second_index(chunk):
            nonlocal index_calls
            index_calls += 1
            if index_calls == 2:
                raise RuntimeError("move failed mid-loop")

        with patch("knowledge.views.cleanup_wiki_for_knowledge"), patch("knowledge.views.delete_knowledge_graph"), patch(
            "knowledge.views.delete_chunk_index"
        ), patch("knowledge.views.rebuild_knowledge_graph"), patch("knowledge.views.enqueue_wiki_ingest"), patch(
            "knowledge.views.index_chunk", side_effect=fail_on_second_index
        ):
            with self.assertRaisesRegex(RuntimeError, "move failed mid-loop"):
                self.client.post(
                    "/api/v1/knowledge/move",
                    data=json.dumps({"ids": [item.id for item in move_docs], "source_kb_id": self.kb.id, "target_kb_id": target.id}),
                    content_type="application/json",
                    **self.tenant_a_headers,
                )
        for document in move_docs:
            document.refresh_from_db()
            self.assertEqual(document.knowledge_base_id, self.kb.id)
            self.assertEqual(document.tenant_id, self.tenant_a.id)
            chunk = Chunk.objects.get(knowledge=document)
            self.assertEqual(chunk.knowledge_base_id, self.kb.id)
            self.assertEqual(chunk.tenant_id, self.tenant_a.id)
