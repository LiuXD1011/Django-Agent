from datetime import timedelta
import threading
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.db import OperationalError, close_old_connections
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
        self.assertEqual(record.payload, {"knowledge_id": self.knowledge.id})
        self.assertEqual(record.result, {"knowledge_id": self.knowledge.id})

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
        cache.set(f"task:{record.id}", {"status": "running", "progress": 0.1}, timeout=86400)

        with patch("personal_knowledge_base.tasks._enqueue_sequential") as enqueue_sequential:
            result = tasks.recover_incomplete_tasks(now=now)

        record.refresh_from_db()
        self.assertEqual(record.status, "pending")
        enqueue_sequential.assert_called_once()
        self.assertEqual(enqueue_sequential.call_args.args[0], record.id)
        self.assertEqual(result["stale_reset"], 1)
        self.assertEqual(result["recovered"], 1)
        self.assertIsNone(cache.get(f"task:{record.id}"))

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

    def test_recovery_fails_unknown_pending_and_running_task_types(self):
        pending = TaskRecord.objects.create(task_type="future_task", status="pending", payload={})
        running = TaskRecord.objects.create(task_type="legacy_task", status="running", payload={})

        with patch("personal_knowledge_base.tasks._enqueue_sequential") as enqueue_sequential:
            result = tasks.recover_incomplete_tasks(now=timezone.now())

        pending.refresh_from_db()
        running.refresh_from_db()
        self.assertEqual((pending.status, running.status), ("failed", "failed"))
        self.assertEqual(pending.error_message, "unsupported task type: future_task")
        self.assertEqual(running.error_message, "unsupported task type: legacy_task")
        self.assertEqual(result["discarded"], 2)
        enqueue_sequential.assert_not_called()

    def test_recovery_excludes_cleanup_artifact_manifests(self):
        pending = TaskRecord.objects.create(
            task_type="cleanup_knowledge_artifacts", status="pending", payload={}
        )
        running = TaskRecord.objects.create(
            task_type="cleanup_knowledge_artifacts", status="running", payload={}
        )

        result = tasks.recover_incomplete_tasks(now=timezone.now())

        pending.refresh_from_db()
        running.refresh_from_db()
        self.assertEqual((pending.status, running.status), ("pending", "running"))
        self.assertEqual(result["discarded"], 0)

    def test_recovery_merges_duplicate_unfinished_tasks(self):
        now = timezone.now()
        kept = self.create_task()
        duplicate = self.create_task()
        TaskRecord.objects.filter(id=kept.id).update(created_at=now - timedelta(minutes=2))
        TaskRecord.objects.filter(id=duplicate.id).update(created_at=now - timedelta(minutes=1))

        with patch("personal_knowledge_base.tasks._enqueue_sequential") as enqueue_sequential:
            result = tasks.recover_incomplete_tasks(now=now)

        duplicate.refresh_from_db()
        self.assertEqual(duplicate.status, "failed")
        self.assertEqual(duplicate.error_message, f"superseded by recoverable task {kept.id}")
        enqueue_sequential.assert_called_once()
        self.assertEqual(enqueue_sequential.call_args.args[0], kept.id)
        self.assertEqual(result["superseded"], 1)
        self.assertEqual(result["recovered"], 1)

    def test_recovery_keeps_fresh_running_task_over_older_pending_task(self):
        now = timezone.now()
        older_pending = self.create_task()
        fresh_running = self.create_task(status="running")
        TaskRecord.objects.filter(id=older_pending.id).update(created_at=now - timedelta(minutes=2))
        TaskRecord.objects.filter(id=fresh_running.id).update(
            created_at=now - timedelta(minutes=1),
            updated_at=now - timedelta(seconds=10),
        )

        with patch("personal_knowledge_base.tasks._enqueue_sequential") as enqueue_sequential:
            result = tasks.recover_incomplete_tasks(now=now)

        older_pending.refresh_from_db()
        fresh_running.refresh_from_db()
        self.assertEqual(fresh_running.status, "running")
        self.assertEqual(older_pending.status, "failed")
        self.assertEqual(older_pending.error_message, f"superseded by recoverable task {fresh_running.id}")
        enqueue_sequential.assert_not_called()
        self.assertEqual(result["superseded"], 1)
        self.assertEqual(result["recovered"], 0)

    def test_concurrent_recovery_scanners_keep_the_same_stable_running_owner(self):
        now = timezone.now()
        owner_a = self.create_task(status="running")
        owner_b = self.create_task(status="running")
        TaskRecord.objects.filter(id=owner_a.id).update(
            created_at=now - timedelta(minutes=2),
            updated_at=now - timedelta(seconds=5),
            payload={"knowledge_id": self.knowledge.id, "_worker_token": "owner-a"},
        )
        TaskRecord.objects.filter(id=owner_b.id).update(
            created_at=now - timedelta(minutes=1),
            updated_at=now - timedelta(seconds=10),
            payload={"knowledge_id": self.knowledge.id, "_worker_token": "owner-b"},
        )

        scanner_one_ready = threading.Event()
        scanner_two_ready = threading.Event()
        release_scanner_one = threading.Event()
        release_scanner_two = threading.Event()
        original_mark_failed = tasks._mark_recovery_failed
        errors = []

        def interleaved_mark(record, message, mark_now):
            if threading.current_thread().name == "recovery-scanner-one":
                scanner_one_ready.set()
                if not release_scanner_one.wait(5):
                    raise TimeoutError("scanner one was not released")
            elif threading.current_thread().name == "recovery-scanner-two":
                scanner_two_ready.set()
                if not release_scanner_two.wait(5):
                    raise TimeoutError("scanner two was not released")
            return original_mark_failed(record, message, mark_now)

        def scan():
            try:
                tasks.recover_incomplete_tasks(now=now)
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)
            finally:
                close_old_connections()

        scanner_one = threading.Thread(target=scan, name="recovery-scanner-one")
        scanner_two = threading.Thread(target=scan, name="recovery-scanner-two")
        with patch("personal_knowledge_base.tasks._mark_recovery_failed", side_effect=interleaved_mark):
            scanner_one.start()
            try:
                self.assertTrue(scanner_one_ready.wait(5), "scanner one did not select a loser")
                TaskRecord.objects.filter(id=owner_a.id).update(updated_at=now - timedelta(seconds=20))
                TaskRecord.objects.filter(id=owner_b.id).update(updated_at=now - timedelta(seconds=1))

                scanner_two.start()
                self.assertTrue(scanner_two_ready.wait(5), "scanner two did not select a loser")
                release_scanner_one.set()
                scanner_one.join(5)
                release_scanner_two.set()
                scanner_two.join(5)
            finally:
                release_scanner_one.set()
                release_scanner_two.set()
                scanner_one.join(5)
                if scanner_two.ident is not None:
                    scanner_two.join(5)

        self.assertEqual(errors, [])
        self.assertFalse(scanner_one.is_alive())
        self.assertFalse(scanner_two.is_alive())
        owner_a.refresh_from_db()
        owner_b.refresh_from_db()
        self.assertEqual(owner_a.status, "running")
        self.assertEqual(owner_a.payload["_worker_token"], "owner-a")
        self.assertEqual(owner_b.status, "failed")

    def test_recovery_does_not_clear_a_token_claimed_after_its_snapshot(self):
        now = timezone.now()
        pending = self.create_task()
        fresh_owner = self.create_task(status="running")
        TaskRecord.objects.filter(id=pending.id).update(created_at=now - timedelta(minutes=2))
        TaskRecord.objects.filter(id=fresh_owner.id).update(
            created_at=now - timedelta(minutes=1),
            updated_at=now - timedelta(seconds=5),
            payload={"knowledge_id": self.knowledge.id, "_worker_token": "existing-owner"},
        )
        original_mark_failed = tasks._mark_recovery_failed

        def claim_then_mark(record, message, mark_now):
            if record.id == pending.id:
                claimed = TaskRecord.objects.filter(id=pending.id, status="pending").update(
                    status="running",
                    progress=0.1,
                    updated_at=now,
                    payload={"knowledge_id": self.knowledge.id, "_worker_token": "post-snapshot-owner"},
                )
                self.assertEqual(claimed, 1)
                cache.set(f"task:{pending.id}", {"status": "running", "progress": 0.1}, timeout=86400)
            return original_mark_failed(record, message, mark_now)

        with patch("personal_knowledge_base.tasks._mark_recovery_failed", side_effect=claim_then_mark):
            result = tasks.recover_incomplete_tasks(now=now)

        pending.refresh_from_db()
        self.assertEqual(pending.status, "running")
        self.assertEqual(pending.payload["_worker_token"], "post-snapshot-owner")
        self.assertEqual(tasks.task_status(pending.id)["status"], "running")
        self.assertEqual(result["superseded"], 0)

    def test_stale_reset_cannot_publish_pending_over_a_new_owner_cache(self):
        now = timezone.now()
        record = self.create_task(status="running")
        TaskRecord.objects.filter(id=record.id).update(
            updated_at=now - timedelta(seconds=91),
            payload={"knowledge_id": self.knowledge.id, "_worker_token": "owner-a"},
        )
        task_cache_key = f"task:{record.id}"
        cache.set(task_cache_key, {"status": "running", "progress": 0.1}, timeout=86400)
        real_cache_set = cache.set
        real_cache_delete = cache.delete
        interleaved = False

        def claim_owner_b():
            nonlocal interleaved
            if interleaved:
                return
            interleaved = True
            claimed = TaskRecord.objects.filter(id=record.id, status="pending").update(
                status="running",
                progress=0.1,
                updated_at=now,
                payload={"knowledge_id": self.knowledge.id, "_worker_token": "owner-b"},
            )
            self.assertEqual(claimed, 1)
            real_cache_set(task_cache_key, {"status": "running", "progress": 0.1}, timeout=86400)

        def interleaved_set(key, value, *args, **kwargs):
            if key == task_cache_key and value.get("status") == "pending":
                claim_owner_b()
            return real_cache_set(key, value, *args, **kwargs)

        def interleaved_delete(key, *args, **kwargs):
            if key == task_cache_key:
                claim_owner_b()
            return real_cache_delete(key, *args, **kwargs)

        with (
            patch("personal_knowledge_base.tasks.cache.set", side_effect=interleaved_set),
            patch("personal_knowledge_base.tasks.cache.delete", side_effect=interleaved_delete),
            patch("personal_knowledge_base.tasks._enqueue_sequential") as enqueue_sequential,
        ):
            result = tasks.recover_incomplete_tasks(now=now)

        record.refresh_from_db()
        self.assertTrue(interleaved)
        self.assertEqual(result["stale_reset"], 1)
        self.assertEqual(record.status, "running")
        self.assertEqual(record.payload["_worker_token"], "owner-b")
        self.assertEqual(tasks.task_status(record.id)["status"], "running")
        enqueue_sequential.assert_not_called()

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

    def test_cleanup_management_command_does_not_schedule_recovery(self):
        invocations = (
            (["manage.py", "cleanup_knowledge_state"], {}),
            (["/workspace/manage.py", "cleanup_knowledge_state", "--confirm"], {}),
            (["django-admin", "cleanup_knowledge_state"], {}),
            (["/venv/bin/django-admin", "cleanup_knowledge_state"], {}),
        )
        for argv, environ in invocations:
            with self.subTest(argv=argv):
                self.assertFalse(tasks.should_schedule_recovery(argv, environ))

    def test_python_module_django_management_commands_do_not_schedule_recovery(self):
        for command in ("migrate", "test", "shell", "cleanup_knowledge_state", "future_custom_command"):
            with self.subTest(command=command):
                self.assertFalse(tasks.should_schedule_recovery(["python", "-m", "django", command], {}))

        self.assertFalse(tasks.should_schedule_recovery(["python", "-m", "django", "runserver"], {}))
        self.assertTrue(
            tasks.should_schedule_recovery(
                ["python", "-m", "django", "runserver"], {"RUN_MAIN": "true"}
            )
        )

    def test_django_main_module_argv_does_not_schedule_management_recovery(self):
        runner = "/venv/lib/python3.12/site-packages/django/__main__.py"
        for command in ("migrate", "test", "shell", "cleanup_knowledge_state", "future_custom_command"):
            with self.subTest(command=command):
                self.assertFalse(tasks.should_schedule_recovery([runner, command], {}))

        self.assertFalse(tasks.should_schedule_recovery([runner, "runserver"], {}))
        self.assertTrue(tasks.should_schedule_recovery([runner, "runserver"], {"RUN_MAIN": "true"}))

    def test_arbitrary_custom_management_command_does_not_schedule_recovery(self):
        for runner in ("manage.py", "/workspace/manage.py", "django-admin", "/venv/bin/django-admin"):
            with self.subTest(runner=runner):
                self.assertFalse(tasks.should_schedule_recovery([runner, "future_custom_command"], {}))

    def test_runserver_child_and_non_management_services_keep_scheduling_behavior(self):
        self.assertFalse(tasks.should_schedule_recovery(["manage.py", "runserver"], {}))
        self.assertTrue(tasks.should_schedule_recovery(["manage.py", "runserver"], {"RUN_MAIN": "true"}))
        self.assertFalse(tasks.should_schedule_recovery(["django-admin", "runserver"], {}))
        self.assertTrue(tasks.should_schedule_recovery(["django-admin", "runserver"], {"RUN_MAIN": "true"}))
        self.assertTrue(tasks.should_schedule_recovery(["gunicorn", "config.wsgi:application"], {}))
        self.assertTrue(tasks.should_schedule_recovery(["uvicorn", "config.asgi:application"], {}))

    def test_pytest_and_unittest_processes_do_not_schedule_recovery(self):
        cases = (
            (["/venv/bin/pytest", "-q"], {}),
            (["/venv/lib/python3.12/site-packages/pytest/__main__.py", "-q"], {}),
            (["/usr/lib/python3.12/unittest/__main__.py", "discover"], {}),
            (["python"], {"PYTEST_CURRENT_TEST": "test_task_recovery.py::test_case"}),
        )
        for argv, environ in cases:
            with self.subTest(argv=argv, environ=environ):
                self.assertFalse(tasks.should_schedule_recovery(argv, environ))

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
        TaskRecord.objects.filter(id=record.id).update(
            payload={"knowledge_id": self.knowledge.id, "_worker_token": "owner-a"},
            updated_at=now - timedelta(minutes=2),
        )
        stop_event = Mock()
        stop_event.wait.side_effect = [False, True]

        with patch("personal_knowledge_base.tasks.close_old_connections") as close_connections:
            try:
                tasks._heartbeat_task(record.id, stop_event, worker_token="owner-a")
            except TypeError as exc:
                self.fail(f"heartbeat does not support fenced ownership: {exc}")

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
            try:
                tasks._heartbeat_task(record.id, stop_event, worker_token="owner-a")
            except TypeError as exc:
                self.fail(f"heartbeat does not support fenced ownership: {exc}")

        self.assertEqual(queryset.update.call_count, 2)
        warning.assert_called_once()

    def test_heartbeat_cannot_refresh_a_new_owner_lease(self):
        old_updated_at = timezone.now() - timedelta(minutes=2)
        record = self.create_task(status="running")
        TaskRecord.objects.filter(id=record.id).update(
            payload={"knowledge_id": self.knowledge.id, "_worker_token": "owner-b"},
            updated_at=old_updated_at,
        )
        stop_event = Mock()
        stop_event.wait.side_effect = [False, True]

        try:
            tasks._heartbeat_task(record.id, stop_event, worker_token="owner-a")
        except TypeError as exc:
            self.fail(f"heartbeat does not support fenced ownership: {exc}")

        record.refresh_from_db()
        self.assertEqual(record.updated_at, old_updated_at)

    def test_expired_owner_cannot_finalize_after_recovery_reclaims_task(self):
        owner_a_started = threading.Event()
        release_owner_a = threading.Event()
        owner_a_errors = []
        record = self.create_task()

        def owner_a_fn():
            owner_a_started.set()
            if not release_owner_a.wait(5):
                raise TimeoutError("owner A was not released")
            return {"owner": "A"}

        def run_owner_a():
            try:
                tasks._run_task(record.id, owner_a_fn)
            except Exception as exc:  # pragma: no cover - asserted below
                owner_a_errors.append(exc)

        owner_a_thread = threading.Thread(target=run_owner_a, name="test-owner-a")
        owner_a_thread.start()
        try:
            self.assertTrue(owner_a_started.wait(5), "owner A did not claim the task")
            record.refresh_from_db()
            self.assertEqual(record.status, "running")

            now = timezone.now()
            TaskRecord.objects.filter(id=record.id).update(updated_at=now - timedelta(seconds=91))
            with patch("personal_knowledge_base.tasks._enqueue_sequential", return_value=True):
                recovery = tasks.recover_incomplete_tasks(now=now)
            self.assertEqual(recovery["stale_reset"], 1)

            tasks._run_task(record.id, lambda: {"owner": "B"})
            self.assertEqual(cache.get(f"task:{record.id}")["result"], {"owner": "B"})
        finally:
            release_owner_a.set()
            owner_a_thread.join(5)

        self.assertFalse(owner_a_thread.is_alive(), "owner A did not stop")
        self.assertEqual(owner_a_errors, [])
        record.refresh_from_db()
        self.assertEqual(record.status, "completed")
        self.assertEqual(record.result, {"owner": "B"})
        self.assertEqual(cache.get(f"task:{record.id}")["result"], {"owner": "B"})

    def test_recovery_fails_and_caches_callable_resolution_errors(self):
        record = self.create_task()
        with (
            patch("personal_knowledge_base.tasks.resolve_task_callable", side_effect=RuntimeError("resolver unavailable")),
            patch("personal_knowledge_base.tasks._enqueue_sequential") as enqueue_sequential,
        ):
            try:
                result = tasks.recover_incomplete_tasks(now=timezone.now())
            except RuntimeError as exc:
                self.fail(f"recovery leaked callable resolution error: {exc}")

        record.refresh_from_db()
        self.assertEqual(record.status, "failed")
        self.assertIn("resolver unavailable", record.error_message)
        self.assertEqual(cache.get(f"task:{record.id}")["status"], "failed")
        enqueue_sequential.assert_not_called()
        self.assertEqual(result["discarded"], 1)

    def test_recovery_fails_and_caches_enqueue_errors(self):
        record = self.create_task()
        with patch("personal_knowledge_base.tasks._enqueue_sequential", side_effect=RuntimeError("queue unavailable")):
            try:
                result = tasks.recover_incomplete_tasks(now=timezone.now())
            except RuntimeError as exc:
                self.fail(f"recovery leaked enqueue error: {exc}")

        record.refresh_from_db()
        self.assertEqual(record.status, "failed")
        self.assertIn("queue unavailable", record.error_message)
        self.assertEqual(cache.get(f"task:{record.id}")["status"], "failed")
        self.assertEqual(result["discarded"], 1)

    def test_sequential_queue_deduplicates_task_ids_in_process(self):
        record = self.create_task()
        task_fn = Mock()

        with patch.object(tasks, "_executor") as executor:
            tasks._enqueue_sequential(record.id, task_fn)
            tasks._enqueue_sequential(record.id, task_fn)

        self.assertEqual(list(tasks._task_queue), [(record.id, task_fn)])
        executor.submit.assert_called_once_with(tasks._process_queue)
