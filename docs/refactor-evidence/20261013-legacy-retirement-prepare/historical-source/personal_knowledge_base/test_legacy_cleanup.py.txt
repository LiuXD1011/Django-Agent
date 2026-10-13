import tempfile
from io import StringIO
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from personal_knowledge_base.models import Chunk, Knowledge, KnowledgeBase, TaskRecord, Tenant, WikiFolder, WikiLogEntry, WikiPage, WikiPendingOp


class LegacyKnowledgeCleanupTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media_dir.name, NEO4J_ENABLE=False)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.media_dir.cleanup)
        self.tenant = Tenant.objects.create(name="清理租户", api_key="cleanup-tenant")
        self.kb = KnowledgeBase.objects.create(tenant=self.tenant, name="保留的知识库")
        self.path = default_storage.save("legacy/old.txt", ContentFile(b"legacy"))
        self.knowledge = Knowledge.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            type="file",
            title="旧文档",
            source="old.txt",
            file_name="old.txt",
            file_path=self.path,
        )
        Chunk.objects.create(tenant=self.tenant, knowledge_base=self.kb, knowledge=self.knowledge, content="旧内容", chunk_index=0)
        WikiFolder.objects.create(tenant=self.tenant, knowledge_base=self.kb, name="旧目录")
        WikiPage.objects.create(tenant=self.tenant, knowledge_base=self.kb, slug="old", title="旧页面")
        WikiPendingOp.objects.create(tenant=self.tenant, scope="knowledge_base", scope_id=self.kb.id, op="ingest")
        WikiLogEntry.objects.create(tenant=self.tenant, knowledge_base=self.kb, knowledge_id=self.knowledge.id, action="ingest")
        TaskRecord.objects.create(task_type="process_knowledge", payload={"knowledge_id": self.knowledge.id})

    def test_command_requires_explicit_confirmation(self):
        with self.assertRaises(CommandError):
            call_command("purge_legacy_knowledge")
        self.assertTrue(Knowledge.objects.filter(id=self.knowledge.id).exists())

    def test_command_deletes_legacy_content_but_keeps_knowledge_base(self):
        output = StringIO()

        with patch("personal_knowledge_base.legacy_cleanup.graph_repository.delete_graph") as delete_graph:
            call_command("purge_legacy_knowledge", "--confirm", stdout=output)

        delete_graph.assert_not_called()
        self.assertFalse(default_storage.exists(self.path))
        self.assertEqual(Knowledge.objects.count(), 0)
        self.assertEqual(Chunk.objects.count(), 0)
        self.assertEqual(WikiPage.objects.count(), 0)
        self.assertEqual(WikiFolder.objects.count(), 0)
        self.assertEqual(WikiPendingOp.objects.count(), 0)
        self.assertEqual(WikiLogEntry.objects.count(), 0)
        self.assertEqual(TaskRecord.objects.filter(task_type="process_knowledge").count(), 0)
        self.assertTrue(KnowledgeBase.objects.filter(id=self.kb.id).exists())
        self.assertIn("1", output.getvalue())

    def test_command_can_run_before_knowledge_image_table_exists(self):
        from personal_knowledge_base import legacy_cleanup

        real_table_exists = legacy_cleanup._table_exists
        with (
            patch("personal_knowledge_base.legacy_cleanup._table_exists", side_effect=lambda name: False if name == "knowledge_images" else real_table_exists(name)),
            patch.object(Knowledge.objects, "all", side_effect=AssertionError("ORM collector must not inspect the future image table")),
        ):
            call_command("purge_legacy_knowledge", "--confirm", stdout=StringIO())

        self.assertEqual(Knowledge.objects.count(), 0)
