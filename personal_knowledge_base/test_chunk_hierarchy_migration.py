import unittest
from unittest.mock import patch

from django.core.exceptions import FieldDoesNotExist
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from personal_knowledge_base.models import Chunk, Knowledge, KnowledgeBase, Tenant


class ChunkHierarchyModelTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(name="hierarchy-tenant", api_key="hierarchy-tenant")
        knowledge_base = KnowledgeBase.objects.create(tenant=tenant, name="hierarchy-kb")
        knowledge = Knowledge.objects.create(
            tenant=tenant,
            knowledge_base=knowledge_base,
            type="file",
            title="hierarchy.txt",
            source="hierarchy.txt",
        )
        self.base = {
            "tenant": tenant,
            "knowledge_base": knowledge_base,
            "knowledge": knowledge,
            "content": "chunk content",
            "chunk_index": 0,
        }

    def test_chunk_relationships_have_distinct_meanings(self):
        parent = Chunk.objects.create(chunk_type="parent_text", **self.base)
        child = Chunk.objects.create(chunk_type="text", context_parent_id=parent.id, **self.base)
        image = Chunk.objects.create(chunk_type="image_container", anchor_chunk_id=child.id, **self.base)
        ocr = Chunk.objects.create(
            chunk_type="image_ocr",
            media_parent_id=image.id,
            anchor_chunk_id=child.id,
            **self.base,
        )

        self.assertEqual(ocr.media_parent_id, image.id)
        self.assertEqual(ocr.anchor_chunk_id, child.id)
        self.assertEqual(child.context_parent_id, parent.id)

    def test_chunk_relationship_ids_are_nullable_indexed_uuid_fields(self):
        for field_name in ["context_parent_id", "media_parent_id", "anchor_chunk_id"]:
            field = Chunk._meta.get_field(field_name)
            self.assertEqual(field.max_length, 36)
            self.assertTrue(field.blank)
            self.assertTrue(field.null)
            self.assertTrue(field.db_index)

        index_fields = [tuple(index.fields) for index in Chunk._meta.indexes]
        self.assertIn(("knowledge", "chunk_type"), index_fields)
        self.assertNotIn(("context_parent_id",), index_fields)
        self.assertNotIn(("media_parent_id",), index_fields)
        self.assertNotIn(("anchor_chunk_id",), index_fields)

    def test_legacy_parent_chunk_id_read_maps_to_media_parent_id(self):
        chunk = Chunk.objects.create(chunk_type="image_ocr", media_parent_id="image-container-id", **self.base)

        self.assertEqual(chunk.parent_chunk_id, "image-container-id")


class ChunkHierarchyMigrationTests(TransactionTestCase):
    migrate_from = ("personal_knowledge_base", "0014_modelconfig_fallback_priority")
    migrate_to = ("personal_knowledge_base", "0015_chunk_hierarchy")

    def setUp(self):
        super().setUp()
        self.addCleanup(self._restore_database)
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        old_apps = self.executor.loader.project_state([self.migrate_from]).apps
        Tenant = old_apps.get_model("personal_knowledge_base", "Tenant")
        KnowledgeBase = old_apps.get_model("personal_knowledge_base", "KnowledgeBase")
        Knowledge = old_apps.get_model("personal_knowledge_base", "Knowledge")
        LegacyChunk = old_apps.get_model("personal_knowledge_base", "Chunk")

        tenant = Tenant.objects.create(name="legacy-tenant", api_key="legacy-tenant")
        knowledge_base = KnowledgeBase.objects.create(tenant=tenant, name="legacy-kb")
        knowledge = Knowledge.objects.create(
            tenant=tenant,
            knowledge_base=knowledge_base,
            type="file",
            title="legacy.txt",
            source="legacy.txt",
        )
        self.chunk_id = "legacy-media-child-chunk-id-000001"
        self.media_parent_id = "legacy-media-parent-chunk-id-00001"
        LegacyChunk.objects.create(
            id=self.chunk_id,
            tenant=tenant,
            knowledge_base=knowledge_base,
            knowledge=knowledge,
            content="legacy OCR",
            chunk_index=0,
            chunk_type="image_ocr",
            parent_chunk_id=self.media_parent_id,
        )

        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_to])

    def _restore_database(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_renames_legacy_media_parent_relationship_without_data_loss(self):
        apps = self.executor.loader.project_state([self.migrate_to]).apps
        Chunk = apps.get_model("personal_knowledge_base", "Chunk")

        chunk = Chunk.objects.get(id=self.chunk_id)

        self.assertEqual(chunk.media_parent_id, self.media_parent_id)
        with self.assertRaises(FieldDoesNotExist):
            Chunk._meta.get_field("parent_chunk_id")


class ChunkHierarchyMigrationCleanupTests(unittest.TestCase):
    def test_setup_failure_restores_current_leaf_schema(self):
        migrate_calls = []
        executors = []

        class FakeGraph:
            def leaf_nodes(self):
                return [("personal_knowledge_base", "current_leaf")]

        class FakeLoader:
            def __init__(self):
                self.graph = FakeGraph()

        class FailingMigrationExecutor:
            def __init__(self, connection):
                self.loader = FakeLoader()
                executors.append(self)

            def migrate(self, targets):
                migrate_calls.append((self, targets))
                if len(migrate_calls) == 1:
                    raise RuntimeError("simulated migration failure")

        migration_test = ChunkHierarchyMigrationTests(
            "test_renames_legacy_media_parent_relationship_without_data_loss"
        )
        result = unittest.TestResult()
        with patch(
            "personal_knowledge_base.test_chunk_hierarchy_migration.MigrationExecutor",
            FailingMigrationExecutor,
        ):
            migration_test.run(result)

        self.assertFalse(result.wasSuccessful())
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(len(executors), 2)
        self.assertIsNot(executors[0], executors[1])
        self.assertEqual(migrate_calls[0][1], [migration_test.migrate_from])
        self.assertEqual(migrate_calls[1][1], executors[1].loader.graph.leaf_nodes())
