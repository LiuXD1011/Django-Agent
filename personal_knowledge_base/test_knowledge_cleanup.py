import tempfile
from io import StringIO
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from personal_knowledge_base.knowledge_cleanup import execute_knowledge_cleanup, plan_knowledge_cleanup
from personal_knowledge_base import tasks
from personal_knowledge_base.models import (
    Chunk,
    Knowledge,
    KnowledgeBase,
    KnowledgeImage,
    KnowledgeProcessingSpan,
    TaskRecord,
    Tenant,
    WikiPendingOp,
)


class KnowledgeCleanupTests(TestCase):
    def setUp(self):
        cache.clear()
        self.media_dir = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(self.media_dir.cleanup)

        self.tenant = Tenant.objects.create(name="Cleanup tenant", api_key="knowledge-cleanup")
        self.kb = KnowledgeBase.objects.create(tenant=self.tenant, name="Primary KB")
        self.other_kb = KnowledgeBase.objects.create(tenant=self.tenant, name="Other KB")

    def tearDown(self):
        cache.clear()

    def create_knowledge(
        self,
        *,
        kb=None,
        file_hash="a" * 64,
        file_name="document.txt",
        file_path="",
        parse_status="completed",
        deleted=False,
    ):
        item = Knowledge.objects.create(
            tenant=self.tenant,
            knowledge_base=kb or self.kb,
            type="file",
            title=file_name,
            source=file_name,
            file_name=file_name,
            file_path=file_path,
            file_hash=file_hash,
            parse_status=parse_status,
        )
        if deleted:
            Knowledge.objects.filter(id=item.id).update(deleted_at=timezone.now())
            item.refresh_from_db()
        return item

    def create_task(self, knowledge_id, *, status="pending"):
        return TaskRecord.objects.create(
            task_type="process_knowledge",
            status=status,
            payload={"knowledge_id": knowledge_id},
        )

    def test_plan_keeps_active_duplicate_and_ignores_other_kb(self):
        old_deleted = self.create_knowledge(file_name="old-name.txt", deleted=True)
        active = self.create_knowledge(file_name="new-name.txt")
        other_kb_copy = self.create_knowledge(kb=self.other_kb, file_name="other-kb-name.txt")

        plan = plan_knowledge_cleanup()

        self.assertIn(active.id, plan.keep_ids)
        self.assertIn(old_deleted.id, plan.delete_ids)
        self.assertIn(other_kb_copy.id, plan.keep_ids)
        self.assertNotIn(other_kb_copy.id, plan.delete_ids)

    def test_command_without_confirm_does_not_write(self):
        shared_path = default_storage.save("cleanup/dry-run.txt", ContentFile(b"dry run"))
        duplicate = self.create_knowledge(file_name="old.txt", file_path=shared_path, deleted=True)
        keeper = self.create_knowledge(file_name="active.txt", file_path=shared_path)
        task = self.create_task(duplicate.id)
        output = StringIO()

        with (
            patch("personal_knowledge_base.knowledge_cleanup.cleanup_wiki_for_knowledge") as cleanup_wiki,
            patch("personal_knowledge_base.knowledge_cleanup.delete_knowledge_graph") as delete_graph,
            patch("personal_knowledge_base.knowledge_cleanup.delete_chunk_index") as delete_index,
        ):
            call_command("cleanup_knowledge_state", stdout=output)

        self.assertTrue(Knowledge.objects.filter(id=duplicate.id).exists())
        self.assertTrue(Knowledge.objects.filter(id=keeper.id).exists())
        self.assertEqual(TaskRecord.objects.get(id=task.id).status, "pending")
        self.assertTrue(default_storage.exists(shared_path))
        cleanup_wiki.assert_not_called()
        delete_graph.assert_not_called()
        delete_index.assert_not_called()
        self.assertIn(duplicate.id, output.getvalue())

    def test_confirm_deletes_duplicate_relations_and_unshared_files(self):
        original_path = default_storage.save("cleanup/original.txt", ContentFile(b"original"))
        image_path = default_storage.save("cleanup/image.png", ContentFile(b"image"))
        duplicate = self.create_knowledge(
            file_name="old.txt",
            file_path=original_path,
            deleted=True,
        )
        self.create_knowledge(file_name="active.txt")
        chunk = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=duplicate,
            content="duplicate chunk",
            chunk_index=0,
            seq_id=17,
        )
        span = KnowledgeProcessingSpan.objects.create(knowledge=duplicate, name="parse")
        image = KnowledgeImage.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=duplicate,
            content_hash="b" * 64,
            storage_path=image_path,
            storage_owned=True,
            source_type="embedded",
        )
        task = self.create_task(duplicate.id)

        with (
            patch("personal_knowledge_base.knowledge_cleanup.cleanup_wiki_for_knowledge") as cleanup_wiki,
            patch("personal_knowledge_base.knowledge_cleanup.delete_knowledge_graph") as delete_graph,
            patch("personal_knowledge_base.knowledge_cleanup.delete_chunk_index") as delete_index,
        ):
            delete_index.side_effect = lambda *_: self.assertFalse(
                Knowledge.objects.filter(id=duplicate.id).exists()
            )
            call_command("cleanup_knowledge_state", "--confirm", stdout=StringIO())

        cleanup_wiki.assert_called_once()
        delete_graph.assert_called_once()
        delete_index.assert_called_once_with(chunk.id, 17)
        self.assertFalse(Knowledge.objects.filter(id=duplicate.id).exists())
        self.assertFalse(Chunk.objects.filter(id=chunk.id).exists())
        self.assertFalse(KnowledgeProcessingSpan.objects.filter(id=span.id).exists())
        self.assertFalse(KnowledgeImage.objects.filter(id=image.id).exists())
        self.assertFalse(TaskRecord.objects.filter(id=task.id).exists())
        self.assertFalse(default_storage.exists(original_path))
        self.assertFalse(default_storage.exists(image_path))

    def test_confirm_preserves_shared_file_path(self):
        shared_path = default_storage.save("cleanup/shared.txt", ContentFile(b"shared"))
        duplicate = self.create_knowledge(file_name="old.txt", file_path=shared_path, deleted=True)
        keeper = self.create_knowledge(file_name="active.txt", file_path=shared_path)

        with (
            patch("personal_knowledge_base.knowledge_cleanup.cleanup_wiki_for_knowledge"),
            patch("personal_knowledge_base.knowledge_cleanup.delete_knowledge_graph"),
        ):
            execute_knowledge_cleanup(plan_knowledge_cleanup())

        self.assertFalse(Knowledge.objects.filter(id=duplicate.id).exists())
        self.assertTrue(Knowledge.objects.filter(id=keeper.id).exists())
        self.assertTrue(default_storage.exists(shared_path))

    def test_external_cleanup_failure_preserves_knowledge_for_retry(self):
        original_path = default_storage.save("cleanup/retry.txt", ContentFile(b"retry"))
        duplicate = self.create_knowledge(file_name="old.txt", file_path=original_path, deleted=True)
        self.create_knowledge(file_name="active.txt")
        chunk = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=duplicate,
            content="retry chunk",
            chunk_index=0,
        )

        with (
            patch(
                "personal_knowledge_base.knowledge_cleanup.cleanup_wiki_for_knowledge",
                side_effect=RuntimeError("wiki unavailable"),
            ),
            patch("personal_knowledge_base.knowledge_cleanup.delete_knowledge_graph") as delete_graph,
        ):
            with self.assertRaises(CommandError):
                call_command("cleanup_knowledge_state", "--confirm", stdout=StringIO())

        delete_graph.assert_not_called()
        self.assertTrue(Knowledge.objects.filter(id=duplicate.id).exists())
        self.assertTrue(Chunk.objects.filter(id=chunk.id).exists())
        self.assertTrue(default_storage.exists(original_path))

    def test_invalid_and_duplicate_tasks_are_reconciled(self):
        soft_deleted = self.create_knowledge(file_hash="b" * 64, deleted=True)
        invalid = self.create_task(soft_deleted.id)
        valid = self.create_knowledge(file_hash="c" * 64)
        kept = self.create_task(valid.id)
        superseded = self.create_task(valid.id)
        missing = self.create_task("missing-knowledge-id")

        plan = plan_knowledge_cleanup()
        self.assertCountEqual(plan.invalid_task_ids, (invalid.id, missing.id))
        self.assertEqual(plan.superseded_task_ids, (superseded.id,))

        execute_knowledge_cleanup(plan)

        invalid.refresh_from_db()
        kept.refresh_from_db()
        superseded.refresh_from_db()
        missing.refresh_from_db()
        self.assertEqual(invalid.status, "failed")
        self.assertIn("not recoverable", invalid.error_message)
        self.assertEqual(missing.status, "failed")
        self.assertIn("not recoverable", missing.error_message)
        self.assertEqual(kept.status, "pending")
        self.assertEqual(superseded.status, "failed")
        self.assertEqual(superseded.error_message, f"superseded by recoverable task {kept.id}")

    def test_stale_plan_does_not_delete_candidate_after_keeper_disappears(self):
        candidate = self.create_knowledge(file_name="old.txt", deleted=True)
        keeper = self.create_knowledge(file_name="active.txt")
        plan = plan_knowledge_cleanup()
        keeper.delete()

        with (
            patch("personal_knowledge_base.knowledge_cleanup.cleanup_wiki_for_knowledge") as cleanup_wiki,
            patch("personal_knowledge_base.knowledge_cleanup.delete_knowledge_graph") as delete_graph,
        ):
            result = execute_knowledge_cleanup(plan)

        self.assertTrue(Knowledge.objects.filter(id=candidate.id).exists())
        self.assertNotIn(candidate.id, result["deleted"])
        cleanup_wiki.assert_not_called()
        delete_graph.assert_not_called()

    def test_stale_plan_does_not_delete_restored_candidate_that_is_now_keeper(self):
        candidate = self.create_knowledge(file_name="old.txt", deleted=True)
        self.create_knowledge(file_name="active.txt")
        plan = plan_knowledge_cleanup()
        Knowledge.objects.filter(id=candidate.id).update(deleted_at=None)

        with (
            patch("personal_knowledge_base.knowledge_cleanup.cleanup_wiki_for_knowledge") as cleanup_wiki,
            patch("personal_knowledge_base.knowledge_cleanup.delete_knowledge_graph") as delete_graph,
        ):
            execute_knowledge_cleanup(plan)

        self.assertTrue(Knowledge.objects.filter(id=candidate.id).exists())
        cleanup_wiki.assert_not_called()
        delete_graph.assert_not_called()

    def test_stale_plan_does_not_delete_candidate_after_hash_or_kb_changes(self):
        hash_changed = self.create_knowledge(file_hash="d" * 64, file_name="hash-old.txt", deleted=True)
        self.create_knowledge(file_hash="d" * 64, file_name="hash-active.txt")
        kb_changed = self.create_knowledge(file_hash="e" * 64, file_name="kb-old.txt", deleted=True)
        self.create_knowledge(file_hash="e" * 64, file_name="kb-active.txt")
        plan = plan_knowledge_cleanup()
        Knowledge.objects.filter(id=hash_changed.id).update(file_hash="f" * 64)
        Knowledge.objects.filter(id=kb_changed.id).update(knowledge_base=self.other_kb)

        with (
            patch("personal_knowledge_base.knowledge_cleanup.cleanup_wiki_for_knowledge") as cleanup_wiki,
            patch("personal_knowledge_base.knowledge_cleanup.delete_knowledge_graph"),
        ):
            execute_knowledge_cleanup(plan)

        self.assertTrue(Knowledge.objects.filter(id=hash_changed.id).exists())
        self.assertTrue(Knowledge.objects.filter(id=kb_changed.id).exists())
        cleanup_wiki.assert_not_called()

    def test_stale_invalid_task_plan_does_not_fail_restored_valid_task(self):
        knowledge = self.create_knowledge(file_hash="1" * 64, deleted=True)
        task = self.create_task(knowledge.id)
        plan = plan_knowledge_cleanup()
        Knowledge.objects.filter(id=knowledge.id).update(deleted_at=None)

        execute_knowledge_cleanup(plan)

        task.refresh_from_db()
        self.assertEqual(task.status, "pending")

    def test_stale_superseded_task_plan_does_not_fail_current_task_owner(self):
        knowledge = self.create_knowledge(file_hash="2" * 64)
        old_owner = self.create_task(knowledge.id)
        candidate = self.create_task(knowledge.id)
        plan = plan_knowledge_cleanup()
        old_owner.delete()

        execute_knowledge_cleanup(plan)

        candidate.refresh_from_db()
        self.assertEqual(candidate.status, "pending")

    def test_database_rollback_does_not_delete_files_or_indexes(self):
        image_path = default_storage.save("cleanup/rollback-image.png", ContentFile(b"image"))
        candidate = self.create_knowledge(file_hash="3" * 64, file_name="old.txt", deleted=True)
        self.create_knowledge(file_hash="3" * 64, file_name="active.txt")
        chunk = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=candidate,
            content="rollback chunk",
            chunk_index=0,
        )
        KnowledgeImage.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=candidate,
            content_hash="4" * 64,
            storage_path=image_path,
            storage_owned=True,
            source_type="embedded",
        )
        real_delete = Knowledge.delete

        def delete_then_fail(instance, *args, **kwargs):
            real_delete(instance, *args, **kwargs)
            raise RuntimeError("database commit boundary failure")

        with (
            patch("personal_knowledge_base.knowledge_cleanup.cleanup_wiki_for_knowledge"),
            patch("personal_knowledge_base.knowledge_cleanup.delete_knowledge_graph"),
            patch("personal_knowledge_base.knowledge_cleanup.delete_chunk_index") as delete_index,
            patch.object(Knowledge, "delete", autospec=True, side_effect=delete_then_fail),
        ):
            result = execute_knowledge_cleanup(plan_knowledge_cleanup())

        self.assertIn(candidate.id, result["errors"])
        self.assertTrue(Knowledge.objects.filter(id=candidate.id).exists())
        self.assertTrue(Chunk.objects.filter(id=chunk.id).exists())
        self.assertTrue(default_storage.exists(image_path))
        delete_index.assert_not_called()

    def test_post_commit_cleanup_failure_reports_error_without_restoring_knowledge(self):
        candidate = self.create_knowledge(file_hash="5" * 64, file_name="old.txt", deleted=True)
        self.create_knowledge(file_hash="5" * 64, file_name="active.txt")
        chunk = Chunk.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=candidate,
            content="indexed chunk",
            chunk_index=0,
        )

        with (
            patch("personal_knowledge_base.knowledge_cleanup.cleanup_wiki_for_knowledge"),
            patch("personal_knowledge_base.knowledge_cleanup.delete_knowledge_graph"),
            patch(
                "personal_knowledge_base.knowledge_cleanup.delete_chunk_index",
                side_effect=RuntimeError("index unavailable"),
            ),
        ):
            result = execute_knowledge_cleanup(plan_knowledge_cleanup())

        self.assertFalse(Knowledge.objects.filter(id=candidate.id).exists())
        self.assertIn(candidate.id, result["deleted"])
        self.assertIn("index unavailable", result["errors"][candidate.id])
        self.assertFalse(Chunk.objects.filter(id=chunk.id).exists())

    def test_deleted_task_cache_is_cleared(self):
        candidate = self.create_knowledge(file_hash="6" * 64, file_name="old.txt", deleted=True)
        self.create_knowledge(file_hash="6" * 64, file_name="active.txt")
        task = self.create_task(candidate.id)
        cache.set(f"task:{task.id}", {"status": "running", "progress": 0.5}, timeout=86400)

        with (
            patch("personal_knowledge_base.knowledge_cleanup.cleanup_wiki_for_knowledge"),
            patch("personal_knowledge_base.knowledge_cleanup.delete_knowledge_graph"),
        ):
            execute_knowledge_cleanup(plan_knowledge_cleanup())

        self.assertEqual(tasks.task_status(task.id)["status"], "not_found")

    def test_wiki_cleanup_consumes_target_retract_behind_backlog(self):
        candidate = self.create_knowledge(file_hash="7" * 64, file_name="old.txt", deleted=True)
        self.create_knowledge(file_hash="7" * 64, file_name="active.txt")
        for index in range(6):
            WikiPendingOp.objects.create(
                tenant=self.tenant,
                task_type="wiki:ingest",
                scope="knowledge_base",
                scope_id=self.kb.id,
                op="retract",
                dedup_key=f"backlog-{index}",
                payload={"knowledge_id": f"missing-{index}"},
            )

        with (
            patch("personal_knowledge_base.knowledge_cleanup.delete_knowledge_graph"),
            patch("personal_knowledge_base.knowledge_cleanup.delete_chunk_index"),
        ):
            result = execute_knowledge_cleanup(plan_knowledge_cleanup())

        self.assertIn(candidate.id, result["deleted"])
        self.assertFalse(
            WikiPendingOp.objects.filter(
                task_type="wiki:ingest",
                scope_id=self.kb.id,
                op="retract",
                dedup_key=candidate.id,
            ).exists()
        )

    def test_owned_image_file_is_preserved_when_non_owned_image_shares_path(self):
        image_path = default_storage.save("cleanup/shared-image.png", ContentFile(b"shared image"))
        candidate = self.create_knowledge(file_hash="8" * 64, file_name="old.txt", deleted=True)
        keeper = self.create_knowledge(file_hash="8" * 64, file_name="active.txt")
        KnowledgeImage.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=candidate,
            content_hash="9" * 64,
            storage_path=image_path,
            storage_owned=True,
            source_type="embedded",
        )
        KnowledgeImage.objects.create(
            tenant=self.tenant,
            knowledge_base=self.kb,
            knowledge=keeper,
            content_hash="0" * 64,
            storage_path=image_path,
            storage_owned=False,
            source_type="standalone",
        )

        with (
            patch("personal_knowledge_base.knowledge_cleanup.cleanup_wiki_for_knowledge"),
            patch("personal_knowledge_base.knowledge_cleanup.delete_knowledge_graph"),
        ):
            execute_knowledge_cleanup(plan_knowledge_cleanup())

        self.assertTrue(default_storage.exists(image_path))
