"""收尾回归：F02 撤权、F08 短发布事务、F13 API 请求侧任务隔离。"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from datetime import timedelta
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.db import connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import tasks
from .authentication import issue_tokens
from .document_processing import process_knowledge
from .models import Chunk, Knowledge, KnowledgeBase, TaskRecord, Tenant, TenantMember, User
from .permissions import KB_DELETE, allows
from .view_security import can_administer_tenant


class RevocationCloseoutTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="closeout", api_key="closeout-key")
        self.user = User.objects.create(
            username="closeout", email="closeout@fixture.invalid",
            password_hash="unused", tenant=self.tenant,
        )
        self.member = TenantMember.objects.create(user=self.user, tenant=self.tenant, role="owner")
        self.token, self.refresh = issue_tokens(self.user)
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}

    def test_inactive_member_is_not_promoted_to_owner(self):
        self.member.status = "disabled"
        self.member.save(update_fields=["status"])
        self.assertFalse(allows(self.user, self.tenant, KB_DELETE))
        self.assertFalse(can_administer_tenant(self.user, self.tenant, self.tenant))
        self.assertEqual(self.client.get("/api/v1/knowledge-bases", **self.headers).status_code, 401)

    def test_soft_deleted_member_is_rejected(self):
        self.member.deleted_at = timezone.now()
        self.member.save(update_fields=["deleted_at"])
        self.assertEqual(self.client.get("/api/v1/knowledge-bases", **self.headers).status_code, 401)

    def test_removed_primary_membership_keeps_revocation_record(self):
        admin = User.objects.create(
            username="closeout-admin", email="closeout-admin@fixture.invalid",
            password_hash="unused", tenant=self.tenant,
        )
        TenantMember.objects.create(user=admin, tenant=self.tenant, role="admin")
        admin_token, _ = issue_tokens(admin)
        response = self.client.delete(
            f"/api/v1/tenants/{self.tenant.id}/members/{self.user.id}",
            HTTP_AUTHORIZATION=f"Bearer {admin_token}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(TenantMember.objects.filter(pk=self.member.pk, status="revoked").exists())
        self.assertEqual(self.client.get("/api/v1/knowledge-bases", **self.headers).status_code, 401)

    def test_deleted_user_access_and_refresh_are_rejected(self):
        self.user.deleted_at = timezone.now()
        self.user.save(update_fields=["deleted_at"])
        self.assertEqual(self.client.get("/api/v1/knowledge-bases", **self.headers).status_code, 401)
        response = self.client.post(
            "/api/v1/auth/refresh", data=json.dumps({"refresh_token": self.refresh}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_invalid_selected_tenant_does_not_fall_back(self):
        response = self.client.get(
            "/api/v1/knowledge-bases", HTTP_X_TENANT_ID="missing", **self.headers,
        )
        self.assertEqual(response.status_code, 401)

    def test_active_secondary_membership_survives_primary_revocation(self):
        other = Tenant.objects.create(name="secondary", api_key="secondary-key")
        TenantMember.objects.create(user=self.user, tenant=other, role="viewer")
        self.member.status = "revoked"
        self.member.save(update_fields=["status"])
        response = self.client.get(
            "/api/v1/knowledge-bases", HTTP_X_TENANT_ID=str(other.id), **self.headers,
        )
        self.assertEqual(response.status_code, 200)

    def test_inactive_tenant_cannot_login_or_refresh(self):
        self.tenant.status = "disabled"
        self.tenant.save(update_fields=["status"])
        with patch("accounts.views.verify_password", return_value=True):
            response = self.client.post(
                "/api/v1/auth/login", data=json.dumps({"email": self.user.email, "password": "fixture"}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 401)
        response = self.client.post(
            "/api/v1/auth/refresh", data=json.dumps({"refresh_token": self.refresh}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_legacy_user_without_membership_keeps_primary_access(self):
        self.member.delete()
        self.assertEqual(self.client.get("/api/v1/knowledge-bases", **self.headers).status_code, 200)
        self.assertTrue(allows(self.user, self.tenant, KB_DELETE))

    def test_viewer_and_service_cannot_read_tenant_provider_credentials(self):
        self.tenant.web_search_config = {"provider": "fixture", "api_key": "fixture-web-search-key"}
        self.tenant.save(update_fields=["web_search_config"])
        self.member.role = "viewer"
        self.member.save(update_fields=["role"])
        for headers in (self.headers, {"HTTP_X_API_KEY": self.tenant.api_key}):
            response = self.client.get("/api/v1/tenants/kv/web-search-config", **headers)
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("fixture-web-search-key", response.content.decode())


@override_settings(APP_MODE="api", RUN_TASK_BACKGROUND=False, APP_TASKS_SYNC=False)
class ApiDispatchCloseoutTests(TestCase):
    def setUp(self):
        cache.clear()
        executor = patch.object(tasks, "_executor", Mock())
        executor.start()
        self.addCleanup(executor.stop)

    def tearDown(self):
        with tasks._queue_lock:
            tasks._task_queue.clear()
            tasks._queued_task_ids.discard("fixture")
            tasks._queue_worker_running = False
        cache.clear()

    def test_api_request_only_persists_task(self):
        fn = Mock()
        with patch.object(tasks, "_dispatch_task") as dispatch:
            record = tasks.enqueue("process_knowledge", fn, {"knowledge_id": "fixture"})
        dispatch.assert_not_called()
        fn.assert_not_called()
        self.assertEqual(record.status, "pending")

    @override_settings(APP_TASKS_SYNC=True)
    def test_sync_flag_does_not_override_api_role(self):
        with patch.object(tasks, "_run_task") as run:
            record = tasks.enqueue("process_knowledge", Mock(), {"knowledge_id": "fixture"})
        run.assert_not_called()
        self.assertEqual(record.status, "pending")

    def test_deferred_dispatch_is_gated_at_execution_time(self):
        with override_settings(RUN_TASK_BACKGROUND=True):
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                tasks._schedule_async_dispatch("process_knowledge", "fixture", Mock())
        self.assertEqual(len(callbacks), 1)
        with patch.object(tasks, "start_task_runner") as runner:
            callbacks[0]()
        runner.assert_not_called()

    def test_recovery_and_direct_dispatch_cannot_start_api_threads(self):
        with patch.object(tasks, "start_task_runner") as runner, \
             patch("personal_knowledge_base.task_recovery.start_recovery_loop") as recovery, \
             patch.object(tasks, "should_schedule_recovery", return_value=True):
            tasks._dispatch_task("process_knowledge", "fixture", Mock())
            tasks._enqueue_sequential("fixture", Mock(), queue_name="documents")
            tasks.schedule_startup_recovery()
        runner.assert_not_called()
        recovery.assert_not_called()

    def test_explicit_worker_execution_still_runs(self):
        record = TaskRecord.objects.create(task_type="process_knowledge", payload={"knowledge_id": "fixture"})
        with patch.object(tasks, "resolve_task_callable", return_value=Mock()), \
             patch.object(tasks, "_run_task") as run:
            self.assertTrue(tasks.run_persisted_task(record.id))
        run.assert_called_once()

    @override_settings(APP_MODE="local", RUN_TASK_BACKGROUND=True, APP_TASKS_SYNC=True)
    def test_local_sync_behavior_is_preserved(self):
        with patch.object(tasks, "_run_task") as run:
            tasks.enqueue("process_knowledge", Mock(), {"knowledge_id": "fixture"})
        run.assert_called_once()


class PublishCloseoutTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(name="publish", api_key="publish-key")
        kb = KnowledgeBase.objects.create(tenant=self.tenant, name="publish")
        self.knowledge = Knowledge.objects.create(
            tenant=self.tenant, knowledge_base=kb, type="file", title="fixture",
            file_name="fixture.txt", file_path="fixture.txt", parse_status="pending",
        )
        self.task = TaskRecord.objects.create(
            task_type="process_knowledge", status="running", claimed_by="old-owner",
            lease_expires_at=timezone.now() + timedelta(seconds=90),
            payload={"knowledge_id": self.knowledge.id},
        )
        bound = tasks._WORKER_IDENTITY.set((self.task.id, "old-owner"))
        self.addCleanup(tasks._WORKER_IDENTITY.reset, bound)
        self.addCleanup(cache.clear)

    def test_expired_lease_cannot_publish_before_takeover(self):
        TaskRecord.objects.filter(pk=self.task.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertRaises(tasks.TaskOwnershipLost):
            tasks.assert_task_ownership()

    def test_lost_owner_cannot_even_set_processing(self):
        TaskRecord.objects.filter(pk=self.task.pk).update(claimed_by="new-owner")
        with patch("personal_knowledge_base.document_processing.default_storage.open") as opened:
            with self.assertRaises(tasks.TaskOwnershipLost):
                process_knowledge(self.knowledge.id)
        opened.assert_not_called()
        self.knowledge.refresh_from_db()
        self.assertEqual(self.knowledge.parse_status, "pending")

    def test_publish_guard_acquires_write_lock_inside_short_transaction(self):
        guard = getattr(tasks, "task_publish_transaction", None)
        self.assertIsNotNone(guard)
        with CaptureQueriesContext(connection) as queries:
            with guard():
                self.assertTrue(connection.in_atomic_block)
                self.knowledge.parse_status = "completed"
                self.knowledge.save(update_fields=["parse_status"])
        updates = [q["sql"].upper() for q in queries if q["sql"].upper().startswith("UPDATE")]
        self.assertGreaterEqual(len(updates), 2)
        self.assertIn("TASK_RECORDS", updates[0])

    def test_publish_guard_refuses_takeover_after_prior_read(self):
        tasks.assert_task_ownership()
        TaskRecord.objects.filter(pk=self.task.pk).update(claimed_by="new-owner")
        guard = getattr(tasks, "task_publish_transaction", None)
        self.assertIsNotNone(guard)
        with self.assertRaises(tasks.TaskOwnershipLost):
            with guard():
                Knowledge.objects.filter(pk=self.knowledge.pk).update(parse_status="completed")
        self.knowledge.refresh_from_db()
        self.assertEqual(self.knowledge.parse_status, "pending")

    def test_publish_failure_rolls_back_business_write(self):
        guard = getattr(tasks, "task_publish_transaction", None)
        self.assertIsNotNone(guard)
        with self.assertRaisesRegex(ValueError, "fixture failure"):
            with guard():
                Knowledge.objects.filter(pk=self.knowledge.pk).update(parse_status="completed")
                raise ValueError("fixture failure")
        self.knowledge.refresh_from_db()
        self.assertEqual(self.knowledge.parse_status, "pending")


class HealthCloseoutTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="health", api_key="health-key")
        self.user = User.objects.create(
            username="health-owner", email="health@fixture.invalid",
            password_hash="unused", tenant=self.tenant,
        )
        TenantMember.objects.create(user=self.user, tenant=self.tenant, role="owner")
        token, _ = issue_tokens(self.user)
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_pending_migrations_make_readyz_unready(self):
        with patch("django.db.migrations.executor.MigrationExecutor.migration_plan", return_value=[("pending", False)]):
            response = self.client.get("/readyz")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["components"]["migrations"]["ok"])

    def test_vector_degradation_is_not_whole_api_unreadiness(self):
        with patch("personal_knowledge_base.search.get_vector_index_state",
                   return_value={"status": "needs_rebuild", "reason": "partial_batch_failures"}):
            response = self.client.get("/readyz")
            components = self.client.get("/health/components", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(components.json()["status"], "degraded")

    def test_component_details_require_admin(self):
        self.assertEqual(self.client.get("/health/components").status_code, 401)
        member = TenantMember.objects.get(user=self.user, tenant=self.tenant)
        member.role = "viewer"
        member.save(update_fields=["role"])
        self.assertEqual(self.client.get("/health/components", **self.headers).status_code, 403)
        self.assertEqual(self.client.get("/health/components", HTTP_X_API_KEY=self.tenant.api_key).status_code, 403)

    def test_database_error_never_exposes_connection_details(self):
        with patch("django.db.backends.utils.CursorWrapper.execute",
                   side_effect=RuntimeError("password=fixture-secret host=private-host")):
            response = self.client.get("/readyz")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("fixture-secret", response.content.decode())
        self.assertNotIn("private-host", response.content.decode())


_DOCUMENT_MUTEX_SCRIPT = r"""
import json, os, sys, time
from datetime import timedelta
from pathlib import Path
args = json.loads(sys.argv[1])
import django
django.setup()
from django.db import transaction
from django.utils import timezone
from personal_knowledge_base import tasks
from personal_knowledge_base.models import Knowledge, KnowledgeBase, TaskRecord, Tenant

def marker(name):
    Path(args["directory"], name).touch()

def wait_for(name):
    path = Path(args["directory"], name)
    deadline = time.monotonic() + 30
    while not path.exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("barrier timeout: " + name)
        time.sleep(.02)

if args["mode"] == "setup":
    from django.core.management import call_command
    call_command("migrate", verbosity=0)
    tenant = Tenant.objects.create(name="mutex", api_key="mutex-key")
    kb = KnowledgeBase.objects.create(tenant=tenant, name="mutex")
    Knowledge.objects.create(id="mutex-document", tenant=tenant, knowledge_base=kb, parse_status="pending")
    TaskRecord.objects.create(
        id="mutex-task", task_type="process_knowledge", status="running", claimed_by="old-owner",
        lease_expires_at=timezone.now() + timedelta(seconds=90),
    )
    print("SETUP_DONE")
elif args["mode"] == "writer":
    bound = tasks._WORKER_IDENTITY.set(("mutex-task", "old-owner"))
    try:
        tasks.assert_task_ownership()
        marker("read")
        wait_for("locked")
        marker("attempted")
        try:
            with tasks.task_publish_transaction():
                Knowledge.objects.filter(id="mutex-document").update(parse_status="failed")
        except tasks.TaskOwnershipLost:
            print("STALE_PUBLISH_REFUSED")
        else:
            raise AssertionError("stale worker published after takeover")
    finally:
        tasks._WORKER_IDENTITY.reset(bound)
elif args["mode"] == "reclaim":
    wait_for("read")
    with transaction.atomic():
        TaskRecord.objects.filter(id="mutex-task").update(
            claimed_by="new-owner", lease_expires_at=timezone.now() + timedelta(seconds=90),
        )
        Knowledge.objects.filter(id="mutex-document").update(parse_status="completed")
        marker("locked")
        wait_for("attempted")
    print("RECLAIM_COMMITTED")
elif args["mode"] == "verify":
    assert Knowledge.objects.get(id="mutex-document").parse_status == "completed"
    assert TaskRecord.objects.get(id="mutex-task").claimed_by == "new-owner"
    print("NEW_OWNER_STATE_PRESERVED")
"""


class DocumentPublishMutexProcessTests(SimpleTestCase):
    """F08: a writer reads the old claim before another process takes over."""
    def test_document_publish_and_takeover_share_database_mutex(self):
        from .test_task_ownership import _isolated_env

        repo = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as directory:
            env = _isolated_env(
                APP_MODE="api", APP_DATA_DIR=directory,
                DJANGO_DB_PATH=str(Path(directory, "mutex.sqlite3")),
            )

            def command(mode):
                return [sys.executable, "-c", _DOCUMENT_MUTEX_SCRIPT,
                        json.dumps({"mode": mode, "directory": directory})]

            setup = subprocess.run(command("setup"), cwd=repo, env=env,
                                   capture_output=True, text=True, timeout=120)
            self.assertEqual(setup.returncode, 0, setup.stderr)
            children = []
            try:
                for mode in ("writer", "reclaim"):
                    children.append(subprocess.Popen(
                        command(mode), cwd=repo, env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    ))
                outputs = []
                for child in children:
                    out, err = child.communicate(timeout=60)
                    self.assertEqual(child.returncode, 0, err)
                    outputs.append(out)
                self.assertIn("STALE_PUBLISH_REFUSED", outputs[0])
                self.assertIn("RECLAIM_COMMITTED", outputs[1])
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.communicate(timeout=10)
            verified = subprocess.run(command("verify"), cwd=repo, env=env,
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertIn("NEW_OWNER_STATE_PRESERVED", verified.stdout)


class SearchCloseoutTests(TestCase):
    def setUp(self):
        from .search import ensure_search_tables, mark_vector_index_ready

        cache.clear()
        ensure_search_tables()
        mark_vector_index_ready("")
        self.tenant = Tenant.objects.create(name="search-closeout", api_key="search-closeout-key")
        self.kb = KnowledgeBase.objects.create(tenant=self.tenant, name="scope")

    def test_all_kb_range_does_not_mix_embedding_models(self):
        from .search import _vector_recall

        KnowledgeBase.objects.create(tenant=self.tenant, name="other-space", embedding_model_id="pinned")
        meta = {"degradations": []}
        with patch("personal_knowledge_base.model_providers.active_embedding_config", return_value={"model": "default"}), \
             patch("personal_knowledge_base.model_providers.embedding") as embed:
            _vector_recall(self.tenant.id, set(), "query", 5, self.tenant, meta)
        embed.assert_not_called()
        self.assertTrue(any("mixed_embedding_spaces" in row["reason"] for row in meta["degradations"]))

    def test_unknown_kb_range_does_not_raise_stop_iteration(self):
        from .search import _vector_recall

        with patch("personal_knowledge_base.model_providers.active_embedding_config", return_value=None):
            self.assertEqual(_vector_recall(self.tenant.id, {"missing"}, "query", 5, self.tenant,
                                           {"degradations": []}), [])

    def test_keyword_scope_is_applied_before_candidate_limit(self):
        from .search import _fts_ranked

        outside = KnowledgeBase.objects.create(tenant=self.tenant, name="outside")
        target = None
        for index in range(12):
            kb = self.kb if index == 11 else outside
            doc = Knowledge.objects.create(tenant=self.tenant, knowledge_base=kb, title="keyword")
            content = "needle " + ("filler " * 40 if kb == self.kb else "")
            chunk = Chunk.objects.create(tenant=self.tenant, knowledge_base=kb, knowledge=doc,
                                         content=content, chunk_index=0)
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO chunks_fts(chunk_id, tenant_id, knowledge_base_id, knowledge_id, title, content) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    [chunk.id, self.tenant.id, kb.id, doc.id, "keyword", content],
                )
            if kb == self.kb:
                target = chunk.id
        self.assertEqual(_fts_ranked(self.tenant.id, {self.kb.id}, "needle", 1), [target])

    def _chunk(self, model):
        doc = Knowledge.objects.create(tenant=self.tenant, knowledge_base=self.kb,
                                       title=model or "default", embedding_model_id=model)
        return Chunk.objects.create(tenant=self.tenant, knowledge_base=self.kb,
                                    knowledge=doc, content=model or "default", chunk_index=0)

    def test_rebuild_keeps_each_document_embedding_model(self):
        from django.conf import settings
        from .search import rebuild_vector_index

        self._chunk("model-a")
        self._chunk("model-b")
        def embed(tenant, texts, model_id=""):
            return [[0.] * settings.LLM_EMBEDDING_DIM for _ in texts]
        with patch("personal_knowledge_base.model_providers.embedding", side_effect=embed) as mocked:
            result = rebuild_vector_index()
        self.assertEqual(result["indexed"], 2)
        self.assertEqual({call.args[2] for call in mocked.call_args_list}, {"model-a", "model-b"})

    def test_truncated_embedding_response_cannot_mark_ready(self):
        from .model_providers import ModelConfigurationError
        from .search import get_vector_index_state, rebuild_vector_index

        self._chunk("")
        with patch("personal_knowledge_base.model_providers.embedding", return_value=[]):
            with self.assertRaises(ModelConfigurationError):
                rebuild_vector_index()
        self.assertNotEqual(get_vector_index_state()["status"], "ready")
