import json

from django.test import TestCase
from django.utils import timezone

from personal_knowledge_base.authentication import issue_tokens
from personal_knowledge_base.models import Knowledge, KnowledgeBase, Tenant, User, WikiFolder, WikiPage
from personal_knowledge_base.wiki_ingest import (
    SlugUpdate,
    clean_dead_links,
    inject_cross_links,
    rebuild_index_page,
    reduce_page,
)


class WikiTenantSecurityTests(TestCase):
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

        self.kb = KnowledgeBase.objects.create(tenant=self.tenant_a, name="tenant-a-kb")
        self.page = WikiPage.objects.create(
            tenant=self.tenant_a,
            knowledge_base=self.kb,
            slug="tenant-a-page",
            title="tenant-a page",
        )
        self.folder = WikiFolder.objects.create(
            tenant=self.tenant_a,
            knowledge_base=self.kb,
            name="tenant-a folder",
        )

    def test_wiki_resources_are_tenant_scoped(self):
        collection_url = f"/api/v1/knowledge-bases/{self.kb.id}/wiki/pages"
        page_url = f"{collection_url}/{self.page.slug}"
        folder_url = f"/api/v1/knowledge-bases/{self.kb.id}/wiki/folders/{self.folder.id}"

        for url in [collection_url, page_url, folder_url]:
            with self.subTest(unauthenticated_url=url):
                self.assertEqual(self.client.get(url).status_code, 401)

        for url in [collection_url, page_url, folder_url]:
            with self.subTest(cross_tenant_get_url=url):
                self.assertEqual(self.client.get(url, **self.tenant_b_headers).status_code, 404)

        writes = [
            ("page put", "put", page_url, {"title": "cross tenant page"}),
            ("folder put", "put", folder_url, {"name": "cross tenant folder"}),
        ]
        for label, method, url, payload in writes:
            with self.subTest(cross_tenant_write=label):
                kwargs = {"content_type": "application/json", **self.tenant_b_headers}
                if payload is not None:
                    kwargs["data"] = json.dumps(payload)
                response = getattr(self.client, method)(url, **kwargs)
                self.assertEqual(response.status_code, 404)
                page = WikiPage.objects.filter(id=self.page.id).first()
                folder = WikiFolder.objects.filter(id=self.folder.id).first()
                self.assertIsNotNone(page)
                self.assertIsNotNone(folder)
                if page and folder:
                    self.assertEqual(page.title, "tenant-a page")
                    self.assertEqual(folder.name, "tenant-a folder")

        for label, url in [("page delete", page_url), ("folder delete", folder_url)]:
            with self.subTest(cross_tenant_write=label):
                response = self.client.delete(url, **self.tenant_b_headers)
                self.assertEqual(response.status_code, 404)
                page = WikiPage.objects.filter(id=self.page.id).first()
                folder = WikiFolder.objects.filter(id=self.folder.id).first()
                self.assertIsNotNone(page)
                self.assertIsNotNone(folder)
                if page and folder:
                    self.assertEqual(page.title, "tenant-a page")
                    self.assertEqual(folder.name, "tenant-a folder")

    def test_wiki_folder_references_must_belong_to_the_current_tenant_and_kb(self):
        foreign_kb = KnowledgeBase.objects.create(tenant=self.tenant_b, name="tenant-b-kb")
        foreign_folder = WikiFolder.objects.create(tenant=self.tenant_b, knowledge_base=foreign_kb, name="tenant-b-folder")
        other_kb = KnowledgeBase.objects.create(tenant=self.tenant_a, name="tenant-a-other-kb")
        other_kb_folder = WikiFolder.objects.create(tenant=self.tenant_a, knowledge_base=other_kb, name="other-kb-folder")

        for folder_ref in [foreign_folder.id, other_kb_folder.id]:
            with self.subTest(operation="page create", folder_ref=folder_ref):
                count_before = WikiPage.objects.filter(knowledge_base=self.kb).count()
                response = self.client.post(
                    f"/api/v1/knowledge-bases/{self.kb.id}/wiki/pages",
                    data=json.dumps({"title": f"bad-page-{folder_ref}", "folder_id": folder_ref}),
                    content_type="application/json",
                    **self.tenant_a_headers,
                )
                self.assertEqual(WikiPage.objects.filter(knowledge_base=self.kb).count(), count_before)
                self.assertEqual(response.status_code, 404)

            page = WikiPage.objects.create(
                tenant=self.tenant_a,
                knowledge_base=self.kb,
                slug=f"page-update-{folder_ref}",
                title="page update",
            )
            with self.subTest(operation="page update", folder_ref=folder_ref):
                response = self.client.put(
                    f"/api/v1/knowledge-bases/{self.kb.id}/wiki/pages/{page.slug}",
                    data=json.dumps({"folder_id": folder_ref}),
                    content_type="application/json",
                    **self.tenant_a_headers,
                )
                page.refresh_from_db()
                self.assertEqual(page.folder_id, "")
                self.assertEqual(response.status_code, 404)

            with self.subTest(operation="folder create", folder_ref=folder_ref):
                count_before = WikiFolder.objects.filter(knowledge_base=self.kb).count()
                response = self.client.post(
                    f"/api/v1/knowledge-bases/{self.kb.id}/wiki/folders",
                    data=json.dumps({"name": f"bad-folder-{folder_ref}", "parent_id": folder_ref}),
                    content_type="application/json",
                    **self.tenant_a_headers,
                )
                self.assertEqual(WikiFolder.objects.filter(knowledge_base=self.kb).count(), count_before)
                self.assertEqual(response.status_code, 404)

            folder = WikiFolder.objects.create(tenant=self.tenant_a, knowledge_base=self.kb, name="folder update")
            with self.subTest(operation="folder update", folder_ref=folder_ref):
                response = self.client.put(
                    f"/api/v1/knowledge-bases/{self.kb.id}/wiki/folders/{folder.id}",
                    data=json.dumps({"parent_id": folder_ref}),
                    content_type="application/json",
                    **self.tenant_a_headers,
                )
                folder.refresh_from_db()
                self.assertEqual(folder.parent_id, "")
                self.assertEqual(response.status_code, 404)

    def test_soft_deleted_pages_and_folders_are_hidden_and_unusable(self):
        deleted_page = WikiPage.objects.create(
            tenant=self.tenant_a,
            knowledge_base=self.kb,
            slug="deleted-page",
            title="deleted page",
            deleted_at=timezone.now(),
        )
        deleted_folder = WikiFolder.objects.create(
            tenant=self.tenant_a,
            knowledge_base=self.kb,
            name="deleted folder",
            deleted_at=timezone.now(),
        )

        pages_url = f"/api/v1/knowledge-bases/{self.kb.id}/wiki/pages"
        folders_url = f"/api/v1/knowledge-bases/{self.kb.id}/wiki/folders"
        pages = self.client.get(pages_url, **self.tenant_a_headers)
        folders = self.client.get(folders_url, **self.tenant_a_headers)
        self.assertNotIn(deleted_page.slug, [item["slug"] for item in pages.json()["data"]["items"]])
        self.assertNotIn(deleted_folder.id, [item["id"] for item in folders.json()["data"]["items"]])
        self.assertEqual(self.client.get(f"{pages_url}/{deleted_page.slug}", **self.tenant_a_headers).status_code, 404)
        self.assertEqual(self.client.get(f"{folders_url}/{deleted_folder.id}", **self.tenant_a_headers).status_code, 404)

        page_create = self.client.post(
            pages_url,
            data=json.dumps({"title": "bad deleted folder", "folder_id": deleted_folder.id}),
            content_type="application/json",
            **self.tenant_a_headers,
        )
        folder_create = self.client.post(
            folders_url,
            data=json.dumps({"name": "bad deleted parent", "parent_id": deleted_folder.id}),
            content_type="application/json",
            **self.tenant_a_headers,
        )
        self.assertEqual(page_create.status_code, 404)
        self.assertEqual(folder_create.status_code, 404)

    def test_manual_page_sync_ignores_soft_deleted_folders_and_pages(self):
        deleted_default_folder = WikiFolder.objects.create(
            tenant=self.tenant_a,
            knowledge_base=self.kb,
            name="页面",
            deleted_at=timezone.now(),
        )
        deleted_target = WikiPage.objects.create(
            tenant=self.tenant_a,
            knowledge_base=self.kb,
            slug="deleted-link-target",
            title="deleted link target",
            in_links=[],
            deleted_at=timezone.now(),
        )

        response = self.client.post(
            f"/api/v1/knowledge-bases/{self.kb.id}/wiki/pages",
            data=json.dumps({
                "slug": "active-source",
                "title": "active source",
                "content": "Do not revive [[deleted-link-target]]",
            }),
            content_type="application/json",
            **self.tenant_a_headers,
        )

        self.assertEqual(response.status_code, 201)
        source = WikiPage.objects.get(knowledge_base=self.kb, slug="active-source")
        active_folder = WikiFolder.objects.get(id=source.folder_id)
        deleted_target.refresh_from_db()
        self.assertNotEqual(active_folder.id, deleted_default_folder.id)
        self.assertIsNone(active_folder.deleted_at)
        self.assertNotIn(deleted_target.slug, source.out_links)
        self.assertNotIn(source.slug, deleted_target.in_links)

    def test_wiki_background_helpers_ignore_soft_deleted_pages(self):
        deleted_page = WikiPage.objects.create(
            tenant=self.tenant_a,
            knowledge_base=self.kb,
            slug="deleted-helper-target",
            title="Deleted Helper Target",
            content="tenant-a page must stay unchanged",
            deleted_at=timezone.now(),
        )
        active_page = WikiPage.objects.create(
            tenant=self.tenant_a,
            knowledge_base=self.kb,
            slug="active-helper-source",
            title="Active Helper Source",
            content="[[deleted-helper-target|Deleted Helper Target]]",
        )

        clean_dead_links(self.kb, [active_page])
        active_page.refresh_from_db()
        self.assertEqual(active_page.content, "Deleted Helper Target")

        active_page.content = "Deleted Helper Target appears here."
        active_page.save(update_fields=["content", "updated_at"])
        inject_cross_links(self.kb, [active_page, deleted_page])
        active_page.refresh_from_db()
        deleted_page.refresh_from_db()
        self.assertNotIn("[[deleted-helper-target", active_page.content)
        self.assertEqual(deleted_page.content, "tenant-a page must stay unchanged")

        index_page = rebuild_index_page(self.kb)
        self.assertNotIn(deleted_page.slug, index_page.content)
        self.assertNotIn(deleted_page.title, index_page.content)

        knowledge = Knowledge.objects.create(
            tenant=self.tenant_a,
            knowledge_base=self.kb,
            type="file",
            title="helper source document",
            source="helper-source.txt",
        )
        result = reduce_page(
            self.kb,
            deleted_page.slug,
            [
                SlugUpdate(
                    slug=deleted_page.slug,
                    page_type="page",
                    title="must not revive",
                    action="upsert",
                    knowledge=knowledge,
                    generated_content="must not overwrite",
                )
            ],
        )
        deleted_page.refresh_from_db()
        self.assertIsNone(result)
        self.assertEqual(deleted_page.title, "Deleted Helper Target")
        self.assertEqual(deleted_page.content, "tenant-a page must stay unchanged")
