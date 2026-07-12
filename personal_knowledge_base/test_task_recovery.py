from datetime import timedelta
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.db import OperationalError
from django.test import TransactionTestCase
from django.utils import timezone

from personal_knowledge_base import tasks
from personal_knowledge_base.apps import PersonalKnowledgeBaseConfig
from personal_knowledge_base.models import Knowledge, KnowledgeBase, TaskRecord, Tenant


class TaskRecoveryTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(name="Recovery tenant", api_key="task-recovery")
        self.knowledge_base = KnowledgeBase.objects.create(
            tenant=self.tenant,
            name="Recovery knowledge base",
        )
        self.knowledge = Knowledge.objects.create(
            tenant=self.tenant,
            knowledge_base=self.knowledge_base,
            type="file",
            title="recoverable.pdf",
            source="recoverable.pdf",
        )

    def tearDown(self):
        with tasks._queue_lock:
            tasks._task_queue.clear()
            if hasattr(tasks, "_queued_task_ids"):
                tasks._queued_task_ids.clear()
            tasks._queue_worker_running = False
        cache.clear()

    def create_task(self, *, status="pending", knowledge=None):
        knowledge = knowledge or self.knowledge
        return TaskRecord.objects.create(
            task_type="process_knowledge",
            status=status,
            payload={"knowledge_id": knowledge.id},
        )

    def test_run_task_claims_pending_record_only_once(self):
        record = self.create_task()
        task_fn = Mock(return_value={"knowledge_id": self.knowledge.id})

        tasks._run_task(record.id, task_fn)
        tasks._run_task(record.id, task_fn)

        self.assertEqual(task_fn.call_count, 1)
        record.refresh_from_db()
        self.assertEqual(record.status, "completed")

    def test_recovery_enqueues_pending_process_knowledge(self):
        record = self.create_task()

        with (
            patch("personal_knowledge_base.tasks._enqueue_sequential") as enqueue_sequential,
            patch("personal_knowledge_base.document_processing.process_knowledge") as process_knowledge,
        ):
            result = tasks.recover_incomplete_tasks(now=timezone.now())

            enqueue_sequential.assert_called_once()
            queued_task_id, queued_fn = enqueue_sequential.call_args.args
            self.assertEqual(queued_task_id, record.id)
            self.assertEqual(queued_fn(), {"knowledge_id": self.knowledge.id})

        process_knowledge.assert_called_once_with(self.knowledge.id)
        self.assertEqual(
            result,
            {"recovered": 1, "stale_reset": 0, "superseded": 0, "discarded": 0},
        )

    def test_recovery_resets_running_task_with_expired_lease(self):
        now = timezone.now()
        record = self.create_task(status="running")
        TaskRecord.objects.filter(id=record.id).update(updated_at=now - timedelta(seconds=91))

        with patch("personal_knowledge_base.tasks._enqueue_sequential") as enqueue_sequential:
            result = tasks.recover_incomplete_tasks(now=now)

        record.refresh_from_db()
        self.assertEqual(record.status, "pending")
        enqueue_sequential.assert_called_once()
        self.assertEqual(enqueue_sequential.call_args.args[0], record.id)
        self.assertEqual(result["stale_reset"], 1)
        self.assertEqual(result["recovered"], 1)

    def test_recovery_keeps_running_task_with_fresh_lease(self):
        now = timezone.now()
        record = self.create_task(status="running")
        TaskRecord.objects.filter(id=record.id).update(updated_at=now - timedelta(seconds=89))

        with patch("personal_knowledge_base.tasks._enqueue_sequential") as enqueue_sequential:
            result = tasks.recover_incomplete_tasks(now=now)

        record.refresh_from_db()
        self.assertEqual(record.status, "running")
        enqueue_sequential.assert_not_called()
        self.assertEqual(
            result,
            {"recovered": 0, "stale_reset": 0, "superseded": 0, "discarded": 0},
        )

    def test_recovery_merges_duplicate_unfinished_tasks(self):
        now = timezone.now()
        kept = self.create_task()
        duplicate = self.create_task(status="running")
        TaskRecord.objects.filter(id=kept.id).update(created_at=now - timedelta(minutes=2))
        TaskRecord.objects.filter(id=duplicate.id).update(created_at=now - timedelta(minutes=1), updated_at=now)

        with patch("personal_knowledge_base.tasks._enqueue_sequential") as enqueue_sequential:
            result = tasks.recover_incomplete_tasks(now=now)

        duplicate.refresh_from_db()
        self.assertEqual(duplicate.status, "failed")
        self.assertEqual(duplicate.error_message, f"superseded by recoverable task {kept.id}")
        enqueue_sequential.assert_called_once()
        self.assertEqual(enqueue_sequential.call_args.args[0], kept.id)
        self.assertEqual(result["superseded"], 1)
        self.assertEqual(result["recovered"], 1)

    def test_recovery_discards_task_for_soft_deleted_knowledge(self):
        record = self.create_task()
        Knowledge.objects.filter(id=self.knowledge.id).update(deleted_at=timezone.now())

        with patch("personal_knowledge_base.tasks._enqueue_sequential") as enqueue_sequential:
            result = tasks.recover_incomplete_tasks(now=timezone.now())

        record.refresh_from_db()
        self.assertEqual(record.status, "failed")
        self.assertIn("not recoverable", record.error_message)
        enqueue_sequential.assert_not_called()
        self.assertEqual(result["discarded"], 1)

    def test_recovery_discards_task_for_cancelled_knowledge(self):
        record = self.create_task()
        Knowledge.objects.filter(id=self.knowledge.id).update(parse_status="cancelled")

        with patch("personal_knowledge_base.tasks._enqueue_sequential") as enqueue_sequential:
            result = tasks.recover_incomplete_tasks(now=timezone.now())

        record.refresh_from_db()
        self.assertEqual(record.status, "failed")
        self.assertIn("not recoverable", record.error_message)
        enqueue_sequential.assert_not_called()
        self.assertEqual(result["discarded"], 1)

    def test_recovery_discards_task_for_missing_knowledge(self):
        record = self.create_task()
        self.knowledge.delete()

        with patch("personal_knowledge_base.tasks._enqueue_sequential") as enqueue_sequential:
            result = tasks.recover_incomplete_tasks(now=timezone.now())

        record.refresh_from_db()
        self.assertEqual(record.status, "failed")
        self.assertIn("not recoverable", record.error_message)
        enqueue_sequential.assert_not_called()
        self.assertEqual(result["discarded"], 1)

    def test_management_commands_do_not_schedule_recovery(self):
        for command in ("test", "migrate", "makemigrations", "shell", "collectstatic"):
            with self.subTest(command=command):
                self.assertFalse(tasks.should_schedule_recovery(["manage.py", command], {}))

        self.assertFalse(tasks.should_schedule_recovery(["manage.py", "runserver"], {}))
        self.assertTrue(tasks.should_schedule_recovery(["manage.py", "runserver"], {"RUN_MAIN": "true"}))
        self.assertTrue(tasks.should_schedule_recovery(["gunicorn", "config.wsgi"], {}))

    def test_startup_recovery_uses_a_daemon_timer_and_handles_database_setup_errors(self):
        timer = Mock()
        with (
            patch("personal_knowledge_base.tasks.should_schedule_recovery", return_value=True),
            patch("personal_knowledge_base.tasks.threading.Timer", return_value=timer) as timer_class,
            patch(
                "personal_knowledge_base.tasks.recover_incomplete_tasks",
                side_effect=OperationalError("task_records is unavailable"),
            ) as recover,
            patch("personal_knowledge_base.tasks.close_old_connections") as close_connections,
            patch("personal_knowledge_base.tasks.logger.warning") as warning,
        ):
            scheduled = tasks.schedule_startup_recovery()
            callback = timer_class.call_args.args[1]
            callback()

        self.assertIs(scheduled, timer)
        self.assertEqual(timer_class.call_args.args[0], tasks.STARTUP_RECOVERY_DELAY)
        self.assertTrue(timer.daemon)
        timer.start.assert_called_once_with()
        recover.assert_called_once_with()
        self.assertEqual(close_connections.call_count, 2)
        warning.assert_called_once()

    def test_apps_ready_schedules_recovery_after_executor_initialization(self):
        call_order = []
        with (
            patch("personal_knowledge_base.startup.check_sqlite_capabilities", side_effect=lambda: call_order.append("sqlite")),
            patch("personal_knowledge_base.tasks.start_task_runner", side_effect=lambda: call_order.append("executor")),
            patch(
                "personal_knowledge_base.tasks.schedule_startup_recovery",
                side_effect=lambda: call_order.append("recovery"),
                create=True,
            ),
        ):
            PersonalKnowledgeBaseConfig("personal_knowledge_base", __import__("personal_knowledge_base")).ready()

        self.assertEqual(call_order, ["sqlite", "executor", "recovery"])

    def test_heartbeat_refreshes_only_a_running_task(self):
        now = timezone.now()
        record = self.create_task(status="running")
        TaskRecord.objects.filter(id=record.id).update(updated_at=now - timedelta(minutes=2))
        stop_event = Mock()
        stop_event.wait.side_effect = [False, True]

        with patch("personal_knowledge_base.tasks.close_old_connections") as close_connections:
            tasks._heartbeat_task(record.id, stop_event)

        record.refresh_from_db()
        self.assertGreater(record.updated_at, now - timedelta(seconds=15))
        self.assertEqual(stop_event.wait.call_args_list[0].args, (15,))
        self.assertEqual(close_connections.call_count, 2)

    def test_heartbeat_continues_after_a_transient_database_error(self):
        record = self.create_task(status="running")
        stop_event = Mock()
        stop_event.wait.side_effect = [False, False, True]
        queryset = Mock()
        queryset.update.side_effect = [OperationalError("database is locked"), 1]

        with (
            patch("personal_knowledge_base.tasks.TaskRecord.objects.filter", return_value=queryset),
            patch("personal_knowledge_base.tasks.close_old_connections"),
            patch("personal_knowledge_base.tasks.logger.warning") as warning,
        ):
            tasks._heartbeat_task(record.id, stop_event)

        self.assertEqual(queryset.update.call_count, 2)
        warning.assert_called_once()

    def test_sequential_queue_deduplicates_task_ids_in_process(self):
        record = self.create_task()
        task_fn = Mock()

        with patch.object(tasks, "_executor") as executor:
            tasks._enqueue_sequential(record.id, task_fn)
            tasks._enqueue_sequential(record.id, task_fn)

        self.assertEqual(list(tasks._task_queue), [(record.id, task_fn)])
        executor.submit.assert_called_once_with(tasks._process_queue)
