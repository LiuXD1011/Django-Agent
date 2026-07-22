from django.test import TestCase

from personal_knowledge_base.authentication import issue_tokens
from personal_knowledge_base.models import KnowledgeBase, Tenant, User, WikiFolder, WikiLogEntry, WikiPage, WikiPendingOp


class WikiTenantChildRowTests(TestCase):
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
        self.local_page = WikiPage.objects.create(
            tenant=self.tenant_a,
            knowledge_base=self.kb,
            slug="tenant-a-page",
            title="tenant-a page",
        )
        self.foreign_page = WikiPage.objects.create(
            tenant=self.tenant_b,
            knowledge_base=self.kb,
            slug="tenant-b-page",
            title="tenant-b secret page",
        )
        WikiFolder.objects.create(tenant=self.tenant_b, knowledge_base=self.kb, name="tenant-b folder")
        WikiPendingOp.objects.create(tenant=self.tenant_b, scope_id=self.kb.id, op="ingest")
        WikiLogEntry.objects.create(
            tenant=self.tenant_b,
            knowledge_base=self.kb,
            action="ingest",
            doc_title="tenant-b secret log",
        )

    def test_wiki_read_models_ignore_inconsistent_tenant_b_children(self):
        pages = self.client.get(f"/api/v1/knowledge-bases/{self.kb.id}/wiki/pages", **self.headers)
        self.assertEqual(pages.status_code, 200)
        self.assertEqual([item["slug"] for item in pages.json()["data"]["items"]], [self.local_page.slug])

        index = self.client.get(f"/api/v1/knowledge-bases/{self.kb.id}/wiki/index", **self.headers)
        self.assertEqual(index.status_code, 200)
        self.assertEqual([item["slug"] for item in index.json()["data"]["items"]], [self.local_page.slug])

        search = self.client.get(f"/api/v1/knowledge-bases/{self.kb.id}/wiki/search?q=secret", **self.headers)
        self.assertEqual(search.status_code, 200)
        self.assertEqual(search.json()["data"]["items"], [])

        graph = self.client.get(f"/api/v1/knowledge-bases/{self.kb.id}/wiki/graph", **self.headers)
        self.assertEqual(graph.status_code, 200)
        self.assertEqual([item["slug"] for item in graph.json()["data"]["nodes"]], [self.local_page.slug])

        stats = self.client.get(f"/api/v1/knowledge-bases/{self.kb.id}/wiki/stats", **self.headers)
        self.assertEqual(stats.status_code, 200)
        self.assertEqual(stats.json()["data"]["pages"], 1)
        self.assertEqual(stats.json()["data"]["folders"], 0)
        self.assertEqual(stats.json()["data"]["pending_tasks"], 0)

        log = self.client.get(f"/api/v1/knowledge-bases/{self.kb.id}/wiki/log", **self.headers)
        self.assertEqual(log.status_code, 200)
        self.assertEqual(log.json()["data"]["items"], [])
