"""MARLIN-R2A ownership fencing: deterministic interleavings plus one real
two-process mutex run.

In-process scenarios drive the production fenced helpers against a real
(TaskTestCase-managed) database: a stale owner's progress write, checkpoint
publish and completion delete must all be refused after the row changed hands,
while the legitimate owner keeps working and legacy ownerless records stay
usable. The process scenario reproduces the dangerous interleaving with two
real OS processes on one temporary SQLite database plus checkpoint directory:
the reclaim holds the database write lock inside its transaction while the old
owner attempts a checkpoint publish, which must block, then refuse. Barriers
are files; every child is reaped with a bounded timeout and an exit-code
check. No sleep-based ordering, no real models, no network, no user data.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.db.models import F
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone

from personal_knowledge_base import tasks
from personal_knowledge_base.models import GenericResource, KnowledgeBase, TaskRecord, Tenant


def _score(value):
    return {"faithfulness": value, "answer_relevancy": value, "context_precision": value}


class TaskOwnershipFencingTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(name="Ownership tenant", api_key="task-ownership")
        self.user_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.user_root.cleanup)
        override = override_settings(APP_DATA_DIR=Path(self.user_root.name))
        override.enable()
        self.addCleanup(override.disable)

    def create_owned_task(self, *, token="owner-a", status="running"):
        record = TaskRecord.objects.create(
            task_type="open_rag_evaluation",
            status="pending",
            queue_name="evaluation",
            payload={"tenant_id": self.tenant.id, "sample_size": 3},
        )
        if status != "pending":
            claimed = TaskRecord.objects.filter(id=record.id, status="pending").update(
                status=status,
                progress=0.1,
                payload={"tenant_id": self.tenant.id, "sample_size": 3, "_worker_token": token},
                claimed_by=token,
                lease_expires_at=timezone.now() + timedelta(seconds=90),
                attempt_count=F("attempt_count") + 1,
                updated_at=timezone.now(),
            )
            self.assertEqual(claimed, 1)
        return TaskRecord.objects.get(id=record.id)

    def runtime_update(self, token, *, stage="retrieval", progress=0.2):
        return tasks._update_open_rag_runtime(
            self.record.id,
            worker_token=token,
            stage=stage,
            progress=progress,
            stage_progress=progress,
            completed_stages=[stage],
            partial_metrics={"retrieval": {"verified": True}},
            completed_questions=1,
            total_questions=3,
            failed_questions=0,
            valid_coverage=1 / 3,
        )

    def test_owned_runtime_update_writes_row_and_cache(self):
        self.record = self.create_owned_task(token="owner-a")

        self.assertTrue(self.runtime_update("owner-a"))

        self.record.refresh_from_db()
        self.assertEqual(self.record.result["stage"], "retrieval")
        self.assertEqual(self.record.payload["_worker_token"], "owner-a")
        cached = cache.get(f"task:{self.record.id}")
        self.assertEqual(cached["status"], "running")
        self.assertEqual(cached["stage"], "retrieval")

    def test_stale_owner_runtime_update_cannot_touch_new_owner(self):
        self.record = self.create_owned_task(token="owner-a")
        self.assertTrue(self.runtime_update("owner-a"))
        self.record.refresh_from_db()
        stale_result = dict(self.record.result)

        claimed = TaskRecord.objects.filter(id=self.record.id, status="running").update(
            status="pending", claimed_by="", lease_expires_at=None,
            payload={"tenant_id": self.tenant.id, "sample_size": 3}, updated_at=timezone.now(),
        )
        self.assertEqual(claimed, 1)
        claimed = TaskRecord.objects.filter(id=self.record.id, status="pending").update(
            status="running", progress=0.1,
            payload={"tenant_id": self.tenant.id, "sample_size": 3, "_worker_token": "owner-b"},
            claimed_by="owner-b",
            lease_expires_at=timezone.now() + timedelta(seconds=90),
            updated_at=timezone.now(),
        )
        self.assertEqual(claimed, 1)
        cache.delete(f"task:{self.record.id}")

        self.assertFalse(self.runtime_update("owner-a"))

        self.record.refresh_from_db()
        self.assertEqual(self.record.claimed_by, "owner-b")
        self.assertEqual(self.record.payload["_worker_token"], "owner-b")
        # 新 owner 的行保持认领时的样子：旧 owner 的 progress 写被整体拒绝。
        self.assertEqual(self.record.result, stale_result)
        # 0 行不写 cache：本进程缓存不得把新 owner 的任务伪装成旧 owner 的 running。
        self.assertIsNone(cache.get(f"task:{self.record.id}"))

    def test_snapshot_taken_before_reclaim_cannot_be_written_after(self):
        """防快照被抢后改写：先取快照，行易主后再提交更新，CAS 必须 0 行。"""
        self.record = self.create_owned_task(token="owner-a")
        self.assertTrue(self.runtime_update("owner-a"))
        self.record.refresh_from_db()
        stale_result = dict(self.record.result)
        claimed = TaskRecord.objects.filter(id=self.record.id, status="running").update(
            status="pending", claimed_by="", lease_expires_at=None,
            payload={"tenant_id": self.tenant.id, "sample_size": 3}, updated_at=timezone.now(),
        )
        self.assertEqual(claimed, 1)
        claimed = TaskRecord.objects.filter(id=self.record.id, status="pending").update(
            status="running", progress=0.1,
            payload={"tenant_id": self.tenant.id, "sample_size": 3, "_worker_token": "owner-b"},
            claimed_by="owner-b", updated_at=timezone.now(),
        )
        self.assertEqual(claimed, 1)

        # owner-a 的旧快照仍指向自己，但 UPDATE 谓词按当前行重估 → 拒绝。
        self.assertFalse(self.runtime_update("owner-a"))
        self.record.refresh_from_db()
        self.assertEqual(self.record.result, stale_result)
        self.assertEqual(self.record.progress, 0.1)

    def test_legacy_empty_token_updates_ownerless_record_only(self):
        self.record = TaskRecord.objects.create(
            task_type="open_rag_evaluation",
            status="running",
            queue_name="evaluation",
            claimed_by="",
            payload={"tenant_id": self.tenant.id, "sample_size": 3},
        )

        self.assertTrue(self.runtime_update(""))

        self.record.refresh_from_db()
        self.assertEqual(self.record.result["stage"], "retrieval")

        claimed = TaskRecord.objects.filter(id=self.record.id).update(
            claimed_by="owner-b", payload={**self.record.payload, "_worker_token": "owner-b"},
        )
        self.assertEqual(claimed, 1)
        cache.delete(f"task:{self.record.id}")
        self.assertFalse(self.runtime_update(""))

    def test_owned_checkpoint_publish_roundtrip_and_permissions(self):
        self.record = self.create_owned_task(token="owner-a")
        payload = {"configuration_fingerprint": "config", "completed_stages": ["retrieval"]}

        self.assertTrue(tasks._write_fenced_open_rag_checkpoint(
            task_id=self.record.id, worker_token="owner-a", tenant_id=self.tenant.id, payload=payload,
        ))

        path = tasks._open_rag_checkpoint_path(self.tenant.id, self.record.id)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), payload)
        if os.name == "posix":
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(tasks._read_open_rag_checkpoint(self.tenant.id, self.record.id), payload)
        self.assertEqual(list(path.parent.glob("*.part")), [])

    def test_stale_owner_checkpoint_publish_is_refused_and_file_preserved(self):
        self.record = self.create_owned_task(token="owner-a")
        owner_payload = {"configuration_fingerprint": "config", "completed_stages": ["retrieval"], "writer": "owner-b"}
        self.assertTrue(tasks._write_fenced_open_rag_checkpoint(
            task_id=self.record.id, worker_token="owner-a", tenant_id=self.tenant.id,
            payload={"configuration_fingerprint": "config", "writer": "owner-a"},
        ))
        claimed = TaskRecord.objects.filter(id=self.record.id, status="running").update(
            claimed_by="owner-b", payload={**self.record.payload, "_worker_token": "owner-b"},
        )
        self.assertEqual(claimed, 1)
        self.assertTrue(tasks._write_fenced_open_rag_checkpoint(
            task_id=self.record.id, worker_token="owner-b", tenant_id=self.tenant.id, payload=owner_payload,
        ))

        self.assertFalse(tasks._write_fenced_open_rag_checkpoint(
            task_id=self.record.id, worker_token="owner-a", tenant_id=self.tenant.id,
            payload={"configuration_fingerprint": "config", "writer": "stale-owner-a"},
        ))

        path = tasks._open_rag_checkpoint_path(self.tenant.id, self.record.id)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["writer"], "owner-b")
        self.assertEqual(list(path.parent.glob("*.part")), [])

    def test_stale_owner_completion_delete_is_refused_new_owner_file_survives(self):
        self.record = self.create_owned_task(token="owner-a")
        self.assertTrue(tasks._write_fenced_open_rag_checkpoint(
            task_id=self.record.id, worker_token="owner-a", tenant_id=self.tenant.id,
            payload={"writer": "owner-a"},
        ))
        claimed = TaskRecord.objects.filter(id=self.record.id, status="running").update(
            claimed_by="owner-b", payload={**self.record.payload, "_worker_token": "owner-b"},
        )
        self.assertEqual(claimed, 1)

        self.assertFalse(tasks._delete_fenced_open_rag_checkpoint(
            task_id=self.record.id, worker_token="owner-a", tenant_id=self.tenant.id,
        ))
        path = tasks._open_rag_checkpoint_path(self.tenant.id, self.record.id)
        self.assertTrue(path.is_file())

        self.assertTrue(tasks._delete_fenced_open_rag_checkpoint(
            task_id=self.record.id, worker_token="owner-b", tenant_id=self.tenant.id,
        ))
        self.assertFalse(path.exists())

    def test_failed_publish_and_serialize_clean_their_unique_temp_file(self):
        self.record = self.create_owned_task(token="owner-a")
        path = tasks._open_rag_checkpoint_path(self.tenant.id, self.record.id)

        # CAS 拒绝（非 owner）→ finally 回收本次临时文件。
        self.assertFalse(tasks._write_fenced_open_rag_checkpoint(
            task_id=self.record.id, worker_token="not-the-owner", tenant_id=self.tenant.id,
            payload={"writer": "intruder"},
        ))
        self.assertEqual(list(path.parent.glob("*.part")), [])

        # 序列化失败（事务外）→ 临时文件同样被回收。
        with patch("json.dumps", side_effect=ValueError("unserializable")):
            with self.assertRaises(ValueError):
                tasks._write_fenced_open_rag_checkpoint(
                    task_id=self.record.id, worker_token="owner-a", tenant_id=self.tenant.id,
                    payload={"writer": "owner-a"},
                )
        self.assertEqual(list(path.parent.glob("*.part")), [])
        self.assertFalse(path.exists())

    def test_legacy_payload_token_owner_can_publish(self):
        self.record = TaskRecord.objects.create(
            task_type="open_rag_evaluation",
            status="running",
            queue_name="evaluation",
            claimed_by="",
            payload={"tenant_id": self.tenant.id, "_worker_token": "legacy-token"},
        )

        self.assertTrue(tasks._write_fenced_open_rag_checkpoint(
            task_id=self.record.id, worker_token="legacy-token", tenant_id=self.tenant.id,
            payload={"writer": "legacy"},
        ))
        path = tasks._open_rag_checkpoint_path(self.tenant.id, self.record.id)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["writer"], "legacy")


class TaskStatusDbAuthorityTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(name="Status tenant", api_key="task-status")

    def test_terminal_states_and_deletion_come_from_the_database(self):
        record = TaskRecord.objects.create(
            task_type="open_rag_evaluation",
            status="running",
            queue_name="evaluation",
            payload={"tenant_id": self.tenant.id},
        )
        stale_cache_key = f"task:{record.id}"
        cache.set(stale_cache_key, {"status": "running", "progress": 0.4, "stage": "retrieval"}, timeout=86400)
        status = tasks.task_status(record.id)
        self.assertEqual(status["status"], "running")
        # DB 尚无 runtime result：cache 的 stage 不得作为权威字段外泄。
        self.assertNotIn("stage", status)
        self.assertEqual(status["progress"], 0)

        TaskRecord.objects.filter(id=record.id).update(
            status="completed", progress=1, result={"owner": "final"},
        )
        status = tasks.task_status(record.id)
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["result"], {"owner": "final"})

        cache.set(stale_cache_key, {"status": "completed", "progress": 1, "result": {"owner": "stale"}}, timeout=86400)
        status = tasks.task_status(record.id)
        self.assertEqual(status["result"], {"owner": "final"})

        TaskRecord.objects.filter(id=record.id).delete()
        self.assertEqual(tasks.task_status(record.id), {"status": "not_found", "progress": 0})

    def test_cancelled_database_status_shadows_stale_running_cache(self):
        record = TaskRecord.objects.create(
            task_type="open_rag_evaluation",
            status="cancelled",
            queue_name="evaluation",
            payload={"tenant_id": self.tenant.id},
        )
        cache.set(f"task:{record.id}", {"status": "running", "progress": 0.4}, timeout=86400)

        status = tasks.task_status(record.id)

        self.assertEqual(status["status"], "cancelled")

    def test_running_runtime_fields_come_from_latest_db_result(self):
        record = TaskRecord.objects.create(
            task_type="open_rag_evaluation",
            status="running",
            progress=0.9,
            queue_name="evaluation",
            claimed_by="new-owner",
            payload={"tenant_id": self.tenant.id, "_worker_token": "new-owner"},
            result={"stage": "judge", "progress": 0.9, "partial_metrics": {"retrieval": {"value": 0.9}}},
        )
        cache.set(
            f"task:{record.id}",
            {
                "status": "running",
                "progress": 0.1,
                "stage": "retrieval",
                "partial_metrics": {"retrieval": {"value": 0.1}},
            },
            timeout=86400,
        )

        status = tasks.task_status(record.id)

        # 运行态展平字段必须构建自最新 DB result：DB stage judge 不得被旧 cache
        # 的 retrieval 遮盖，partial_metrics 同理；progress 以 DB 为准。
        self.assertEqual(status["progress"], 0.9)
        self.assertEqual(status["status"], "running")
        self.assertEqual(status["stage"], "judge")
        self.assertEqual(status["partial_metrics"], {"retrieval": {"value": 0.9}})


class RunTaskRetryOwnershipTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(name="Retry tenant", api_key="task-retry")

    def create_task(self):
        return TaskRecord.objects.create(
            task_type="open_rag_evaluation",
            status="pending",
            queue_name="evaluation",
            payload={"tenant_id": self.tenant.id},
        )

    def reclaim_as_owner_b(self, record_id):
        reset = TaskRecord.objects.filter(id=record_id, status="running").update(
            status="pending", claimed_by="", lease_expires_at=None,
            payload={"tenant_id": self.tenant.id}, updated_at=timezone.now(),
        )
        self.assertEqual(reset, 1)
        claimed = TaskRecord.objects.filter(id=record_id, status="pending").update(
            status="running", progress=0.1,
            payload={"tenant_id": self.tenant.id, "_worker_token": "owner-b"},
            claimed_by="owner-b",
            lease_expires_at=timezone.now() + timedelta(seconds=90),
            updated_at=timezone.now(),
        )
        self.assertEqual(claimed, 1)

    def test_database_lock_retry_stops_after_losing_ownership(self):
        record = self.create_task()
        calls = []

        def fail_locked_after_preemption():
            calls.append(1)
            if len(calls) == 1:
                self.reclaim_as_owner_b(record.id)
                raise RuntimeError("database is locked")
            raise AssertionError("stale owner must not re-run fn after losing ownership")

        tasks._run_task(record.id, fail_locked_after_preemption)

        self.assertEqual(len(calls), 1)
        record.refresh_from_db()
        self.assertEqual(record.status, "running")
        self.assertEqual(record.claimed_by, "owner-b")
        self.assertEqual(record.payload["_worker_token"], "owner-b")
        self.assertEqual(cache.get(f"task:{record.id}"), {"status": "running", "progress": 0.1})

    def test_database_lock_retry_with_cancel_request_marks_cancelled_once(self):
        record = self.create_task()
        calls = []

        def request_cancel_then_fail_locked():
            calls.append(1)
            if len(calls) == 1:
                TaskRecord.objects.filter(id=record.id).update(cancel_requested_at=timezone.now())
                raise RuntimeError("database is locked")
            raise AssertionError("cancelled task must not re-run fn")

        tasks._run_task(record.id, request_cancel_then_fail_locked)

        self.assertEqual(len(calls), 1)
        record.refresh_from_db()
        self.assertEqual(record.status, "cancelled")
        self.assertEqual(record.claimed_by, "")
        self.assertIsNotNone(record.cancel_requested_at)
        self.assertEqual(cache.get(f"task:{record.id}")["status"], "cancelled")

    def test_owned_database_lock_still_retries_bounded(self):
        record = self.create_task()
        calls = []

        def fail_locked_once():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("database is locked")
            return {"knowledge_id": "done"}

        with patch.object(tasks, "RETRY_DELAY", 0):
            tasks._run_task(record.id, fail_locked_once)

        self.assertEqual(len(calls), 2)
        record.refresh_from_db()
        self.assertEqual(record.status, "completed")

    def test_ownership_transfer_during_retry_sleep_stops_callable(self):
        record = self.create_task()
        calls = []

        def fail_locked_only():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("database is locked")
            raise AssertionError("stale owner must not re-run fn after ownership transferred during sleep")

        def takeover_during_sleep(_seconds):
            TaskRecord.objects.filter(id=record.id, status="running").update(
                claimed_by="owner-b",
                payload={"tenant_id": self.tenant.id, "_worker_token": "owner-b"},
            )

        with patch.object(tasks, "RETRY_DELAY", 0), patch.object(tasks.time, "sleep", side_effect=takeover_during_sleep):
            tasks._run_task(record.id, fail_locked_only)

        self.assertEqual(len(calls), 1)
        record.refresh_from_db()
        self.assertEqual(record.status, "running")
        self.assertEqual(record.claimed_by, "owner-b")


class EvaluationCallbackOwnershipStopTests(SimpleTestCase):
    """fenced 回调被拒后必须停止，而不是继续昂贵工作。"""

    def _tenant_patches(self, record, dataset, fenced_return):
        runtime_update = Mock(return_value=True)
        patches = {
            "personal_knowledge_base.tasks.TaskRecord.objects.get": Mock(return_value=record),
            "personal_knowledge_base.models.Tenant.objects.filter": Mock(
                return_value=SimpleNamespace(first=lambda: SimpleNamespace(id="tenant"))
            ),
            "personal_knowledge_base.models.GenericResource.objects.filter": Mock(
                return_value=SimpleNamespace(first=lambda: dataset)
            ),
            "personal_knowledge_base.tasks._read_open_rag_checkpoint": Mock(return_value={}),
            "personal_knowledge_base.tasks._write_fenced_open_rag_checkpoint": Mock(return_value=fenced_return),
            "personal_knowledge_base.tasks._update_open_rag_runtime": runtime_update,
            "personal_knowledge_base.tasks._open_rag_cancelled": Mock(return_value=False),
            "personal_knowledge_base.tasks._runtime_configuration_degradations": Mock(return_value=[]),
            "personal_knowledge_base.tasks._validate_tenant_evaluation_documents": Mock(),
            "personal_knowledge_base.tasks._tenant_evaluation_search": Mock(return_value=([], {})),
            "personal_knowledge_base.tasks._tenant_retrieval_metrics": Mock(return_value=(1.0, 1.0, 1.0)),
            "personal_knowledge_base.tasks._cleanup_open_rag_checkpoints": Mock(),
        }
        return patches, runtime_update

    def test_tenant_save_checkpoint_stops_when_fence_refuses(self):
        entries = [{"id": f"entry-{i}", "question": f"question-{i}", "evidence": []} for i in range(3)]
        record = SimpleNamespace(payload={
            "tenant_id": "tenant", "dataset_hash": "hash", "configuration_fingerprint": "config",
            "source": {"type": "tenant_dataset", "dataset_id": "dataset", "knowledge_base_id": "kb"},
        }, claimed_by="worker")
        dataset = SimpleNamespace(id="dataset", data={
            "schema_version": "evaluation_v2", "dataset_hash": "hash", "knowledge_base_id": "kb",
            "entries": entries,
        })
        patches, runtime_update = self._tenant_patches(record, dataset, fenced_return=False)
        with ExitStack() as stack:
            for name, replacement in patches.items():
                stack.enter_context(patch(name, new=replacement))
            with self.assertRaises(tasks.OpenRagEvaluationCancelled) as ctx:
                tasks.run_tenant_evaluation_task("task")

        self.assertIn("lost ownership", str(ctx.exception))
        runtime_update.assert_not_called()

    def test_open_checkpoint_stage_stops_when_fence_refuses(self):
        checkpoint = {
            "configuration_fingerprint": "config",
            "completed_stages": ["retrieval", "chunking", "answer_generation"],
            "partial_metrics": {
                "retrieval": {"verified": True}, "chunking": {"verified": True},
                "answer_generation": {"verified": True},
            },
            "answer_result": {"total_questions": 3, "details": [
                {"query_id": f"query-{i}", "question": f"question-{i}", "answer": "saved",
                 "valid": True, "contexts": ["context"], "ground_truth": "reference"}
                for i in range(3)
            ]},
            "ragas_scores": [_score(0.1), _score(0.2), _score(0.3)],
            "ragas_example_ids": ["query-0", "query-1", "query-2"],
        }
        record = SimpleNamespace(payload={
            "tenant_id": "tenant", "dataset_id": "open", "dataset_version": "v1",
            "sample_size": 3, "configuration_fingerprint": "config",
        }, claimed_by="worker")
        runtime_update = Mock(return_value=True)
        patches = {
            "personal_knowledge_base.tasks.TaskRecord.objects.get": Mock(return_value=record),
            "personal_knowledge_base.models.Tenant.objects.filter": Mock(
                return_value=SimpleNamespace(first=lambda: SimpleNamespace(id="tenant"))
            ),
            "personal_knowledge_base.tasks._read_open_rag_checkpoint": Mock(return_value=checkpoint),
            "personal_knowledge_base.tasks._write_fenced_open_rag_checkpoint": Mock(return_value=False),
            "personal_knowledge_base.tasks._update_open_rag_runtime": runtime_update,
            "personal_knowledge_base.tasks._open_rag_cancelled": Mock(return_value=False),
            "personal_knowledge_base.tasks._runtime_configuration_degradations": Mock(return_value=[]),
            "personal_knowledge_base.tasks._cleanup_open_rag_checkpoints": Mock(),
            "personal_knowledge_base.eval_dataset_registry.get_dataset_spec": Mock(
                return_value=SimpleNamespace(dataset_id="open", version="v1", sha256="hash", expected_documents=1)
            ),
            "personal_knowledge_base.open_rag_benchmark.open_dataset_status": Mock(return_value={"ready": True}),
            "personal_knowledge_base.open_rag_benchmark.run_open_rag_evaluation": Mock(
                return_value={"verified": True, "failed_questions": 0, "valid_coverage": 1.0}
            ),
            "personal_knowledge_base.eval_reports.save_open_evaluation_report": Mock(
                return_value={"report_id": "report"}
            ),
            "personal_knowledge_base.observability.report_evaluation_run": Mock(),
        }
        with ExitStack() as stack:
            for name, replacement in patches.items():
                stack.enter_context(patch(name, new=replacement))
            with self.assertRaises(tasks.OpenRagEvaluationCancelled) as ctx:
                tasks.run_open_rag_evaluation_task("task")

        self.assertIn("lost ownership", str(ctx.exception))
        # ragas 阶段入口的 runtime 更新在 checkpoint 之前合法发生；
        # fenced 拒绝后不得再有任何后续 runtime 写。
        self.assertEqual(runtime_update.call_count, 1)


# ── round2：原始 claim 身份上下文绑定 ─────────────────────────────────────


class WorkerIdentityBindingTests(TransactionTestCase):
    """原始 (task_id, worker_token) 必须限定在执行上下文；evaluation 入口
    不得从再次读取的 fresh DB 冒用新 owner token，也不得跨 task 串用。"""

    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(name="Identity tenant", api_key="task-identity")
        self.kb = KnowledgeBase.objects.create(name="identity-kb", tenant=self.tenant)
        self.user_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.user_root.cleanup)
        override = override_settings(APP_DATA_DIR=Path(self.user_root.name))
        override.enable()
        self.addCleanup(override.disable)

    def create_pending_task(self, *, extra_payload=None):
        payload = {"tenant_id": self.tenant.id, "sample_size": 3}
        if extra_payload:
            payload.update(extra_payload)
        return TaskRecord.objects.create(
            task_type="open_rag_evaluation",
            status="pending",
            queue_name="evaluation",
            payload=payload,
        )

    def claim_as_owner_a(self, record_id):
        original = TaskRecord.objects.get(id=record_id).payload
        claimed = TaskRecord.objects.filter(id=record_id, status="pending").update(
            status="running",
            progress=0.1,
            payload={**original, "_worker_token": "owner-a"},
            claimed_by="owner-a",
            lease_expires_at=timezone.now() + timedelta(seconds=90),
            attempt_count=1,
            updated_at=timezone.now(),
        )
        self.assertEqual(claimed, 1)

    def preemptive_reclaim_to_owner_b(self, record_id):
        """claim 之后、evaluation 读取身份之前发生的恢复重置 + 新 owner 认领。"""
        original = TaskRecord.objects.get(id=record_id).payload
        stripped = {key: value for key, value in original.items() if key != "_worker_token"}
        reset = TaskRecord.objects.filter(id=record_id, status="running").update(
            status="pending", claimed_by="", lease_expires_at=None,
            payload=stripped, updated_at=timezone.now(),
        )
        self.assertEqual(reset, 1)
        claimed = TaskRecord.objects.filter(id=record_id, status="pending").update(
            status="running", progress=0.1,
            payload={**stripped, "_worker_token": "owner-b"},
            claimed_by="owner-b",
            lease_expires_at=timezone.now() + timedelta(seconds=90),
            updated_at=timezone.now(),
        )
        self.assertEqual(claimed, 1)

    def test_run_task_binds_original_identity_for_fn_and_resets_after_return(self):
        record = self.create_pending_task()
        seen = []

        def fn():
            claimed_payload = TaskRecord.objects.filter(id=record.id).values_list("payload", flat=True).first()
            seen.append((tasks._WORKER_IDENTITY.get(), (claimed_payload or {}).get("_worker_token")))
            return {}

        tasks._run_task(record.id, fn)

        self.assertEqual(len(seen), 1)
        (bound_task_id, bound_token), claimed_token = seen[0]
        self.assertEqual(bound_task_id, record.id)
        self.assertTrue(bound_token)
        # 绑定身份与 claim 写入 payload 的 token 同源。
        self.assertEqual(bound_token, claimed_token)
        self.assertIsNone(tasks._WORKER_IDENTITY.get())

    def test_run_task_resets_identity_after_exception_and_retry_keeps_same_token(self):
        record = self.create_pending_task()
        seen = []

        def fn():
            seen.append(tasks._WORKER_IDENTITY.get())
            if len(seen) == 1:
                raise RuntimeError("database is locked")
            return {}

        with patch.object(tasks, "RETRY_DELAY", 0):
            tasks._run_task(record.id, fn)

        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0], seen[1])
        self.assertIsNone(tasks._WORKER_IDENTITY.get())

    def test_identity_context_cannot_be_reused_across_tasks(self):
        context = tasks._WORKER_IDENTITY.set(("some-other-task", "owner-a"))
        try:
            with self.assertRaises(RuntimeError):
                tasks._evaluation_worker_identity("this-task", {}, "")
        finally:
            tasks._WORKER_IDENTITY.reset(context)

    def test_resolver_falls_back_to_record_identity_without_context(self):
        record = TaskRecord.objects.create(
            task_type="open_rag_evaluation",
            status="running",
            queue_name="evaluation",
            claimed_by="",
            payload={"tenant_id": self.tenant.id, "_worker_token": "legacy-token"},
        )
        # legacy/离线直调边界：无上下文时回落 record 自身身份，不跨 task 串用。
        self.assertEqual(
            tasks._evaluation_worker_identity(record.id, record.payload, record.claimed_by),
            "legacy-token",
        )
        claimed = TaskRecord.objects.filter(id=record.id).update(
            claimed_by="claimed-owner", payload={"tenant_id": self.tenant.id},
        )
        self.assertEqual(claimed, 1)
        record.refresh_from_db()
        self.assertEqual(
            tasks._evaluation_worker_identity(record.id, record.payload, record.claimed_by),
            "claimed-owner",
        )
        self.assertEqual(tasks._evaluation_worker_identity(record.id, {}, ""), "")

    def _open_entry_patches(self, retrieval_mock):
        return {
            "personal_knowledge_base.tasks._runtime_configuration_degradations": Mock(return_value=[]),
            "personal_knowledge_base.eval_dataset_registry.get_dataset_spec": Mock(
                return_value=SimpleNamespace(dataset_id="open", version="v1", sha256="hash", expected_documents=1)
            ),
            "personal_knowledge_base.open_rag_benchmark.open_dataset_status": Mock(return_value={"ready": True}),
            "personal_knowledge_base.open_rag_benchmark.sample_open_rag_questions": Mock(
                return_value=[{"query_id": f"query-{i}"} for i in range(3)]
            ),
            "personal_knowledge_base.open_rag_benchmark.retrieve_open_rag_questions": retrieval_mock,
            "personal_knowledge_base.open_rag_benchmark.run_open_rag_retrieval": Mock(return_value={"verified": True}),
        }

    def _assert_preempted_owner_cannot_write(self, record_id):
        record = TaskRecord.objects.get(id=record_id)
        self.assertEqual(record.claimed_by, "owner-b")
        self.assertEqual(record.payload["_worker_token"], "owner-b")
        self.assertIsNone(record.result)
        self.assertNotIn("stage", record.payload)
        self.assertFalse(tasks._open_rag_checkpoint_path(self.tenant.id, record_id).exists())
        self.assertIsNone(cache.get(f"task:{record_id}"))

    def test_open_evaluation_entry_keeps_original_token_after_preemptive_reclaim(self):
        record = self.create_pending_task(extra_payload={
            "dataset_id": "open", "dataset_version": "v1", "configuration_fingerprint": "config",
        })
        self.claim_as_owner_a(record.id)
        retrieval_mock = Mock(return_value={})
        context = tasks._WORKER_IDENTITY.set((record.id, "owner-a"))
        try:
            self.preemptive_reclaim_to_owner_b(record.id)
            patches = self._open_entry_patches(retrieval_mock)
            with ExitStack() as stack:
                for name, replacement in patches.items():
                    stack.enter_context(patch(name, new=replacement))
                with self.assertRaises(tasks.OpenRagEvaluationCancelled):
                    tasks.run_open_rag_evaluation_task(record.id)
        finally:
            tasks._WORKER_IDENTITY.reset(context)

        self._assert_preempted_owner_cannot_write(record.id)
        retrieval_mock.assert_not_called()

    def test_tenant_evaluation_entry_keeps_original_token_after_preemptive_reclaim(self):
        dataset = GenericResource.objects.create(
            tenant=self.tenant,
            resource_type="rag_eval_datasets",
            name="identity-dataset",
            status="published",
            data={
                "schema_version": "evaluation_v2",
                "dataset_hash": "hash",
                "knowledge_base_id": self.kb.id,
                "entries": [
                    {"id": f"entry-{i}", "question": f"question-{i}", "evidence": []} for i in range(3)
                ],
            },
        )
        record = self.create_pending_task(extra_payload={
            "dataset_hash": "hash",
            "configuration_fingerprint": "config",
            "source": {"type": "tenant_dataset", "dataset_id": dataset.id, "knowledge_base_id": self.kb.id},
        })
        self.claim_as_owner_a(record.id)
        search_mock = Mock(return_value=([], {}))
        context = tasks._WORKER_IDENTITY.set((record.id, "owner-a"))
        try:
            self.preemptive_reclaim_to_owner_b(record.id)
            patches = {
                "personal_knowledge_base.tasks._runtime_configuration_degradations": Mock(return_value=[]),
                "personal_knowledge_base.tasks._validate_tenant_evaluation_documents": Mock(),
                "personal_knowledge_base.tasks._tenant_evaluation_search": search_mock,
                "personal_knowledge_base.tasks._tenant_retrieval_metrics": Mock(return_value=(1.0, 1.0, 1.0)),
            }
            with ExitStack() as stack:
                for name, replacement in patches.items():
                    stack.enter_context(patch(name, new=replacement))
                with self.assertRaises(tasks.OpenRagEvaluationCancelled):
                    tasks.run_tenant_evaluation_task(record.id)
        finally:
            tasks._WORKER_IDENTITY.reset(context)

        self._assert_preempted_owner_cannot_write(record.id)
        search_mock.assert_not_called()


# ── round2：checkpoint 过期清理的保守守卫 ─────────────────────────────────


class CheckpointCleanupGuardTests(TransactionTestCase):
    """清理只删已终结且确认仍过期的记录文件：active/可恢复任务永不清理，
    未知记录保守跳过，边界内复核状态与 mtime。"""

    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(name="Cleanup tenant", api_key="task-cleanup")
        self.user_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.user_root.cleanup)
        override = override_settings(APP_DATA_DIR=Path(self.user_root.name))
        override.enable()
        self.addCleanup(override.disable)

    def write_expired_checkpoint(self, task_id, *, age_days=8, writer="old"):
        path = tasks._open_rag_checkpoint_path(self.tenant.id, task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"writer": writer}), encoding="utf-8")
        old = time.time() - age_days * 86400
        os.utime(path, (old, old))
        return path

    def create_record(self, *, status, claimed_by=""):
        return TaskRecord.objects.create(
            task_type="open_rag_evaluation",
            status=status,
            queue_name="evaluation",
            claimed_by=claimed_by,
            payload={"tenant_id": self.tenant.id},
        )

    def test_cleanup_preserves_active_and_unknown_record_checkpoints(self):
        running = self.create_record(status="running", claimed_by="owner-a")
        pending = self.create_record(status="pending")
        running_path = self.write_expired_checkpoint(running.id)
        pending_path = self.write_expired_checkpoint(pending.id)
        unknown_path = self.write_expired_checkpoint("no-such-task")

        tasks._cleanup_open_rag_checkpoints()

        self.assertTrue(running_path.exists())
        self.assertTrue(pending_path.exists())
        self.assertTrue(unknown_path.exists())

    def test_cleanup_removes_only_terminated_expired_checkpoints(self):
        paths = {}
        for status in ("completed", "partial", "failed", "cancelled"):
            record = self.create_record(status=status)
            paths[status] = self.write_expired_checkpoint(record.id)

        tasks._cleanup_open_rag_checkpoints()

        for status, path in paths.items():
            self.assertFalse(path.exists(), f"{status} checkpoint should be cleaned")

    def test_cleanup_keeps_fresh_files_even_for_terminated_records(self):
        record = self.create_record(status="completed")
        path = self.write_expired_checkpoint(record.id, age_days=0)

        tasks._cleanup_open_rag_checkpoints()

        self.assertTrue(path.exists())

    def test_cleanup_boundary_refuses_after_resume_to_active(self):
        record = self.create_record(status="partial")
        path = self.write_expired_checkpoint(record.id)
        expired_before = time.time() - 7 * 86400
        # 扫描器 stat 之后、边界删除之前：partial 被 resume 成 running 并被新 owner 认领。
        resumed = TaskRecord.objects.filter(id=record.id, status="partial").update(
            status="running", claimed_by="owner-b",
            payload={"tenant_id": self.tenant.id, "_worker_token": "owner-b"},
            cancel_requested_at=None,
            lease_expires_at=timezone.now() + timedelta(seconds=90),
            updated_at=timezone.now(),
        )
        self.assertEqual(resumed, 1)

        tasks._cleanup_expired_open_rag_checkpoint(path, record.id, expired_before)

        self.assertTrue(path.exists())

    def test_cleanup_boundary_refuses_freshly_republished_file(self):
        record = self.create_record(status="completed")
        path = self.write_expired_checkpoint(record.id)
        expired_before = time.time() - 7 * 86400
        # 等锁期间文件被重新发布：mtime 变新，边界内必须复核而不是沿用旧 stat。
        path.write_text(json.dumps({"writer": "new-owner"}), encoding="utf-8")
        fresh = time.time()
        os.utime(path, (fresh, fresh))

        tasks._cleanup_expired_open_rag_checkpoint(path, record.id, expired_before)

        self.assertTrue(path.exists())
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["writer"], "new-owner")


# ── 跨进程 write × reclaim 互斥（真实双进程 + 临时 SQLite + 屏障文件）────────


_REPO_ROOT = Path(__file__).resolve().parents[1]

_BASE_ENV_KEYS = (
    "APPDATA", "COMSPEC", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "LOCALAPPDATA",
    "PATH", "PATHEXT", "SSL_CERT_DIR", "SSL_CERT_FILE", "SYSTEMDRIVE", "SYSTEMROOT",
    "TEMP", "TMP", "TMPDIR", "USERPROFILE",
)

_ISOLATED_SETTINGS_ENV = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "DJANGO_SETTINGS_MODULE": "config.settings",
    "DJANGO_DEBUG": "true",
    "NEO4J_ENABLE": "false",
    "LANGFUSE_ENABLED": "false",
    "LANGFUSE_AUTOSTART": "false",
    "DJANGO_ALLOWED_HOSTS": "testserver,localhost",
}

_WAIT_FOR_FILE_SECONDS = 60
_CHILD_TIMEOUT_SECONDS = 120
_MIGRATE_TIMEOUT_SECONDS = 240

_MUTEX_WORKER_SCRIPT = r"""
import json
import os
import sys
import time

args = json.loads(sys.argv[1])
os.chdir(args["repo_root"])
sys.path.insert(0, args["repo_root"])
os.environ.clear()
os.environ.update(args["env"])

import django

django.setup()

mode = args["mode"]

if mode == "migrate":
    from django.core.management import call_command

    call_command("migrate", "--noinput", verbosity=0)
    print("MIGRATED")
    sys.exit(0)

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from personal_knowledge_base import tasks
from personal_knowledge_base.models import TaskRecord

# 与生产 worker 相同的连接前置：WAL + busy_timeout，保证阻塞语义可预期。
tasks._ensure_wal_mode()

task_id = args["task_id"]
tenant_id = args["tenant_id"]


def wait_for(path, timeout=60.0):
    deadline = time.monotonic() + timeout
    while not os.path.exists(path):
        if time.monotonic() > deadline:
            raise SystemExit("barrier timeout: %s" % path)
        time.sleep(0.02)


def write_marker(path, value):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle)


def checkpoint_payload(writer):
    return {"configuration_fingerprint": "config", "writer": writer}


def reclaim_two_step(old_token, new_token):
    reset = TaskRecord.objects.filter(
        id=task_id, status="running", claimed_by=old_token,
    ).update(
        status="pending", claimed_by="", lease_expires_at=None,
        payload={"tenant_id": tenant_id, "sample_size": 3}, updated_at=timezone.now(),
    )
    assert reset == 1, "reclaim reset hit %s rows" % reset
    claimed = TaskRecord.objects.filter(id=task_id, status="pending").update(
        status="running", progress=0.1,
        payload={"tenant_id": tenant_id, "sample_size": 3, "_worker_token": new_token},
        claimed_by=new_token,
        lease_expires_at=timezone.now() + timedelta(seconds=90),
        updated_at=timezone.now(),
    )
    assert claimed == 1, "reclaim claim hit %s rows" % claimed


if mode == "setup_owner":
    TaskRecord.objects.create(
        id=task_id,
        task_type="open_rag_evaluation",
        status="running",
        queue_name="evaluation",
        progress=0.1,
        claimed_by=args["token"],
        lease_expires_at=timezone.now() + timedelta(seconds=90),
        payload={"tenant_id": tenant_id, "sample_size": 3, "_worker_token": args["token"]},
    )
    published = tasks._write_fenced_open_rag_checkpoint(
        task_id=task_id, worker_token=args["token"], tenant_id=tenant_id,
        payload=checkpoint_payload(args["token"]),
    )
    assert published, "setup owner failed to publish its checkpoint"
    write_marker(args["result_path"], {"published": True})
    print("SETUP_DONE")
    sys.exit(0)

if mode == "reclaim_hold":
    # 在事务内先完成两步 reclaim（reset + 新 owner 认领），持有数据库写锁直到
    # 老 owner 的 publish 尝试已经发生，再提交。
    with transaction.atomic():
        reclaim_two_step(args["old_token"], args["new_token"])
        write_marker(args["locked_path"], {"locked": True})
        wait_for(args["attempted_path"])
    published = tasks._write_fenced_open_rag_checkpoint(
        task_id=task_id, worker_token=args["new_token"], tenant_id=tenant_id,
        payload=checkpoint_payload(args["new_token"]),
    )
    assert published, "new owner failed to publish after reclaim"
    write_marker(args["result_path"], {"claimed": True})
    print("RECLAIM_DONE")
    sys.exit(0)

if mode == "writer_attempt":
    wait_for(args["locked_path"])
    write_marker(args["attempted_path"], {"attempted": True})
    published = tasks._write_fenced_open_rag_checkpoint(
        task_id=task_id, worker_token=args["old_token"], tenant_id=tenant_id,
        payload=checkpoint_payload("stale-%s" % args["old_token"]),
    )
    write_marker(args["result_path"], {"published": bool(published)})
    print("WRITER_DONE")
    sys.exit(0)

if mode == "reclaim_plain":
    reclaim_two_step(args["old_token"], args["new_token"])
    write_marker(args["result_path"], {"claimed": True})
    print("RECLAIM_DONE")
    sys.exit(0)

if mode == "writer_only":
    published = tasks._write_fenced_open_rag_checkpoint(
        task_id=task_id, worker_token=args["old_token"], tenant_id=tenant_id,
        payload=checkpoint_payload("stale-%s" % args["old_token"]),
    )
    write_marker(args["result_path"], {"published": bool(published)})
    print("WRITER_DONE")
    sys.exit(0)

raise SystemExit("unknown mode: %s" % mode)
"""


def _isolated_env(**overrides):
    env = {key: os.environ[key] for key in _BASE_ENV_KEYS if key in os.environ}
    env.update(_ISOLATED_SETTINGS_ENV)
    env.update(overrides)
    return env


def _wait_for_file(path, deadline_seconds=_WAIT_FOR_FILE_SECONDS):
    deadline = time.monotonic() + deadline_seconds
    while not os.path.exists(path):
        if time.monotonic() > deadline:
            raise TimeoutError("timed out waiting for %s" % os.path.basename(path))
        time.sleep(0.02)


class CheckpointWriteReclaimMutexProcessTests(SimpleTestCase):
    """真实两个进程：checkpoint publish 与 reclaim 必须互斥且失主必拒。"""

    maxDiff = None

    _GRACE_SECONDS = 10

    def _spawn(self, args):
        return subprocess.Popen(
            [sys.executable, "-c", _MUTEX_WORKER_SCRIPT, json.dumps(args)],
            cwd=str(_REPO_ROOT),
            env=args["env"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def _collect(self, process, timeout):
        try:
            return process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                return process.communicate(timeout=self._GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                raise AssertionError("worker subprocess survived kill beyond %ss" % self._GRACE_SECONDS)

    def _shutdown(self, process):
        if process.stdout is not None or process.stderr is not None:
            if process.poll() is None:
                process.terminate()
            self._collect(process, self._GRACE_SECONDS)
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=self._GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=self._GRACE_SECONDS)

    def _finish(self, process, timeout=_CHILD_TIMEOUT_SECONDS):
        stdout, stderr = self._collect(process, timeout)
        self.assertEqual(
            process.returncode,
            0,
            "worker subprocess failed (exit %s)\n--- stdout ---\n%s\n--- stderr tail ---\n%s"
            % (process.returncode, stdout, "\n".join((stderr or "").splitlines()[-15:])),
        )
        return stdout, stderr

    def _migrate(self, db_path):
        process = self._spawn({
            "mode": "migrate",
            "repo_root": str(_REPO_ROOT),
            "env": _isolated_env(DJANGO_DB_PATH=db_path),
        })
        try:
            self._finish(process, timeout=_MIGRATE_TIMEOUT_SECONDS)
        finally:
            self._shutdown(process)

    def _read_result(self, path):
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def _checkpoint_file(self, user_root, tenant_id, task_id):
        return Path(user_root) / ".cache" / "open-rag-runs" / tenant_id / f"{task_id}.json"

    def _assert_no_temp_files(self, user_root, tenant_id, task_id):
        directory = self._checkpoint_file(user_root, tenant_id, task_id).parent
        self.assertEqual(list(directory.glob("*.part")), [])

    def test_fenced_publish_and_reclaim_are_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "shared.sqlite3")
            user_root = os.path.join(tmp, "user-root")
            os.makedirs(user_root)
            self._migrate(db_path)
            tenant_id = "mutex-tenant"

            def env_for():
                return _isolated_env(DJANGO_DB_PATH=db_path, APP_DATA_DIR=user_root)

            def base_args(mode, task_id, extra):
                return {
                    "mode": mode,
                    "repo_root": str(_REPO_ROOT),
                    "task_id": task_id,
                    "tenant_id": tenant_id,
                    "env": env_for(),
                    **extra,
                }

            # 场景一（屏障确定性）：reclaim 在事务内持锁，老 owner 的 publish 必须
            # 阻塞直到提交，然后按新 owner 谓词被拒；文件内容保持新 owner 的。
            task_one = "mutex-task-barrier"
            setup = self._spawn(base_args("setup_owner", task_one, {
                "token": "owner-a", "result_path": os.path.join(tmp, "s1-setup.json"),
            }))
            try:
                self._finish(setup)
            finally:
                self._shutdown(setup)

            reclaimer = self._spawn(base_args("reclaim_hold", task_one, {
                "old_token": "owner-a", "new_token": "owner-b",
                "locked_path": os.path.join(tmp, "s1-locked"),
                "attempted_path": os.path.join(tmp, "s1-attempted"),
                "result_path": os.path.join(tmp, "s1-reclaim.json"),
            }))
            writer = None
            try:
                _wait_for_file(os.path.join(tmp, "s1-locked"))
                writer = self._spawn(base_args("writer_attempt", task_one, {
                    "old_token": "owner-a",
                    "locked_path": os.path.join(tmp, "s1-locked"),
                    "attempted_path": os.path.join(tmp, "s1-attempted"),
                    "result_path": os.path.join(tmp, "s1-writer.json"),
                }))
                self._finish(reclaimer)
                self._finish(writer)
            finally:
                self._shutdown(reclaimer)
                if writer is not None:
                    self._shutdown(writer)

            self.assertFalse(self._read_result(os.path.join(tmp, "s1-writer.json"))["published"])
            self.assertTrue(self._read_result(os.path.join(tmp, "s1-reclaim.json"))["claimed"])
            checkpoint = self._checkpoint_file(user_root, tenant_id, task_one)
            self.assertEqual(json.loads(checkpoint.read_text(encoding="utf-8"))["writer"], "owner-b")
            self._assert_no_temp_files(user_root, tenant_id, task_one)

            # 场景二（同时启动，结果与交错次序无关）：无论谁先拿到数据库写锁，
            # publish 与 reclaim 不能同时生效——publish 成功则文件必须是它的内容，
            # 失败则文件必须保持 setup owner 的内容；reclaim 最终必然成功。
            task_two = "mutex-task-race"
            setup = self._spawn(base_args("setup_owner", task_two, {
                "token": "owner-a", "result_path": os.path.join(tmp, "s2-setup.json"),
            }))
            try:
                self._finish(setup)
            finally:
                self._shutdown(setup)

            reclaimer = self._spawn(base_args("reclaim_plain", task_two, {
                "old_token": "owner-a", "new_token": "owner-b",
                "result_path": os.path.join(tmp, "s2-reclaim.json"),
            }))
            writer = self._spawn(base_args("writer_only", task_two, {
                "old_token": "owner-a", "result_path": os.path.join(tmp, "s2-writer.json"),
            }))
            try:
                self._finish(reclaimer)
                self._finish(writer)
            finally:
                self._shutdown(reclaimer)
                self._shutdown(writer)

            writer_result = self._read_result(os.path.join(tmp, "s2-writer.json"))["published"]
            self.assertTrue(self._read_result(os.path.join(tmp, "s2-reclaim.json"))["claimed"])
            checkpoint = self._checkpoint_file(user_root, tenant_id, task_two)
            content = json.loads(checkpoint.read_text(encoding="utf-8"))["writer"]
            # 线性一致：publish 赢得写锁 → 文件是它的完整内容（reclaim 排在其后）；
            # reclaim 先提交 → publish 必须被拒且文件保持 setup owner 的内容。
            if writer_result:
                self.assertEqual(content, "stale-owner-a")
            else:
                self.assertEqual(content, "owner-a")
            self._assert_no_temp_files(user_root, tenant_id, task_two)
