from django.test import TestCase

from personal_knowledge_base.authentication import issue_tokens
from personal_knowledge_base.models import Knowledge, KnowledgeBase, KnowledgeTag, Tenant, User


class KnowledgeCollectionPerformanceTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="collection-tenant", api_key="collection-key")
        self.user = User.objects.create(
            username="collection-user",
            email="collection@example.com",
            password_hash="unused",
            tenant=self.tenant,
        )
        token, _ = issue_tokens(self.user)
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        self.kb = KnowledgeBase.objects.create(tenant=self.tenant, name="collection-kb")
        self.tag = KnowledgeTag.objects.create(tenant=self.tenant, knowledge_base=self.kb, name="collection-tag")
        self.doc = Knowledge.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            type="file",
            title="large metadata document",
            source="large.txt",
            parse_status="completed",
            tag_id=self.tag.id,
        )
        self.pending_doc = Knowledge.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            type="file",
            title="pending document",
            source="pending.txt",
            parse_status="pending",
        )

    def test_collection_uses_one_lightweight_array_and_unfiltered_aggregates(self):
        self.doc.metadata = {"content": "x" * 100_000}
        self.doc.file_path = "/private/large.txt"
        self.doc.file_hash = "f" * 64
        self.doc.save(update_fields=["metadata", "file_path", "file_hash"])

        response = self.client.get(
            f"/api/v1/knowledge-bases/{self.kb.id}/knowledge?parse_status=completed&page=1&page_size=100",
            **self.headers,
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual([item["id"] for item in data["items"]], [self.doc.id])
        self.assertNotIn("metadata", data["items"][0])
        self.assertNotIn("file_path", data["items"][0])
        self.assertNotIn("file_hash", data["items"][0])
        self.assertNotIn("knowledge", data)
        self.assertNotIn("data", data)
        self.assertEqual(data["status_counts"][self.doc.parse_status], 1)
        self.assertEqual(data["status_counts"][self.pending_doc.parse_status], 1)
        self.assertEqual(data["tag_counts"][self.doc.tag_id], 1)
        self.assertEqual(data["tag_counts"][""], 1)
        self.assertEqual({item["id"] for item in data["processing_records"]}, {self.doc.id, self.pending_doc.id})
        self.assertLess(len(response.content), 20_000)

    def test_collection_limits_processing_records_to_200(self):
        Knowledge.objects.bulk_create([
            Knowledge(
                tenant=self.tenant,
                knowledge_base=self.kb,
                type="file",
                title=f"record-{index}",
                source=f"record-{index}.txt",
            )
            for index in range(201)
        ])

        response = self.client.get(
            f"/api/v1/knowledge-bases/{self.kb.id}/knowledge?page=1&page_size=100",
            **self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]["processing_records"]), 200)
