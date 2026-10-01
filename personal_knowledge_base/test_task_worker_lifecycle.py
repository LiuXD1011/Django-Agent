"""MARLIN-R2B 常驻恢复 loop 与 worker 生命周期验收。

- loop 契约用注入的 stop_event（可控 wait）同步驱动：首轮保留启动小延迟、
  之后固定间隔连续周期直到停止、失败只记简短错误并进入下一间隔、向量重建
  检查只在初始化执行一次、每轮前后 close_old_connections。3 个周期轮在
  生产间隔（30s）下等价越过旧实现 90.1s 双 Timer 的窗口——用可控 wait 证明
  继续扫描，不做真实 90s 等待。
- worker 命令：--once 先做一次确定性恢复再 drain 至空退出且不留 daemon；
  正常模式即使主循环同步执行长任务（繁忙）也有扫描，异常退出时 finally
  停止自身恢复 loop；非法/非有限 poll 间隔清楚拒绝、过小值给安全下界。
- 合并测试一次覆盖同步顺序任务、取消与租约回归；真实 loop 线程 + 真实
  恢复证明繁忙期间仍扫描。
- 跨进程场景沿用 R1/R2A 的真实双进程机制（临时共享 SQLite + 白名单 env +
  屏障文件 + 有界收割 + exitcode 断言）：持有者被 SIGKILL 崩溃后，租约窗口
  用直接 DB 写压缩（把过期时间写到过去，等价于"允许测试缩短间隔"），
  后继 worker --once（真实恢复 + 真实 drain）恰好认领一次并完成。
  无长 sleep 猜时序、无真实模型调用。
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TransactionTestCase
from django.utils import timezone

from personal_knowledge_base import task_recovery, tasks
from personal_knowledge_base.management.commands.run_task_worker import normalised_poll_interval
from personal_knowledge_base.models import Knowledge, KnowledgeBase, TaskRecord, Tenant


class TaskRecoveryLoopContractTests(SimpleTestCase):
    """同步驱动 run()：全部用注入 stop_event 的可控 wait，不起真实线程。"""

    def _loop(self, *, recovery_fn=None, startup_check_fn=None, wait_side_effects, **kwargs):
        stop_event = Mock()
        stop_event.wait.side_effect = wait_side_effects
        return task_recovery.TaskRecoveryLoop(
            recovery_fn=recovery_fn or Mock(return_value={"recovered": 0}),
            startup_check_fn=startup_check_fn,
            stop_event=stop_event,
            **kwargs,
        ), stop_event

    def test_rounds_continue_on_fixed_interval_until_stop(self):
        """5 轮可控 wait 等价 0.1/30.1/60.1/90.1/120.1 秒：越过旧实现
        90.1s 双 Timer 的最后一轮窗口之后，恢复仍持续扫描。"""
        recovery = Mock(return_value={"recovered": 0})
        loop, stop_event = self._loop(
            recovery_fn=recovery,
            wait_side_effects=[False, False, False, False, False, True],
            initial_delay_seconds=0.1,
            interval_seconds=30.0,
            include_startup_reindex_check=False,
        )

        loop.run()

        self.assertEqual(recovery.call_count, 5, "rounds at 0.1/30.1/60.1/90.1/120.1s: scanning continues past the legacy 90.1s window")
        self.assertEqual(stop_event.wait.call_args_list[0].args, (0.1,))
        self.assertEqual(
            [call.args for call in stop_event.wait.call_args_list[1:]],
            [(30.0,), (30.0,), (30.0,), (30.0,), (30.0,)],
            "periodic rounds must use the fixed testable interval",
        )

    def test_startup_reindex_check_runs_once_not_every_round(self):
        reindex = Mock(return_value="")
        loop, _ = self._loop(
            startup_check_fn=reindex,
            wait_side_effects=[False, False, False, False, True],
        )

        loop.run()

        reindex.assert_called_once_with()

    def test_worker_can_disable_startup_reindex_check(self):
        reindex = Mock(return_value="")
        loop, stop_event = self._loop(
            startup_check_fn=reindex,
            wait_side_effects=[False, True],
            include_startup_reindex_check=False,
        )

        loop.run()

        reindex.assert_not_called()

    def test_recovery_failure_logs_brief_error_and_next_round_still_runs(self):
        recover_calls = []

        def failing_recovery(queue_names):
            recover_calls.append(queue_names)
            if len(recover_calls) < 3:
                raise RuntimeError("transient recovery explosion")
            return {"recovered": 0}

        with patch("personal_knowledge_base.task_recovery.logger.warning") as warning:
            loop, _ = self._loop(
                recovery_fn=failing_recovery,
                wait_side_effects=[False, False, False, True],
                include_startup_reindex_check=False,
            )
            loop.run()  # 不向调用方泄漏异常

        self.assertEqual(len(recover_calls), 3, "next cycle must stay available after a failure")
        self.assertEqual(warning.call_count, 2)
        for call in warning.call_args_list:
            message = " ".join(str(arg) for arg in call.args)
            self.assertNotIn("Traceback", message, "failure logs must stay brief")

    def test_stop_before_first_round_runs_nothing(self):
        recovery = Mock(return_value={"recovered": 0})
        loop, _ = self._loop(
            recovery_fn=recovery,
            wait_side_effects=[True],
            include_startup_reindex_check=False,
        )

        loop.run()

        recovery.assert_not_called()

    def test_close_old_connections_wraps_every_round(self):
        with patch("personal_knowledge_base.task_recovery.close_old_connections") as close_connections:
            loop, _ = self._loop(
                wait_side_effects=[False, False, True],
                include_startup_reindex_check=False,
            )
            loop.run()

        # 两轮 × (前+后) + run() finally 一次
        self.assertEqual(close_connections.call_count, 5)

    def test_queue_names_are_passed_to_recovery(self):
        recovery = Mock(return_value={"recovered": 0})
        loop, _ = self._loop(
            recovery_fn=recovery,
            wait_side_effects=[False, True],
            queue_names=("evaluation",),
            include_startup_reindex_check=False,
        )

        loop.run()

        recovery.assert_called_once_with(("evaluation",))

    def test_invalid_intervals_are_rejected(self):
        for value in (float("nan"), float("inf"), float("-inf"), 0, -1, True, "x"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    task_recovery.TaskRecoveryLoop(interval_seconds=value)
                with self.assertRaises(ValueError):
                    task_recovery.TaskRecoveryLoop(initial_delay_seconds=value)


class RecoveryLoopSingletonTests(SimpleTestCase):
    def test_start_is_idempotent_and_stop_leaves_no_thread(self):
        with patch.object(task_recovery.TaskRecoveryLoop, "_round", return_value=None):
            first = task_recovery.start_recovery_loop(interval_seconds=0.01, initial_delay_seconds=0.01)
            threads_after_first = [
                thread for thread in threading.enumerate() if thread.name == "task-recovery-loop"
            ]
            second = task_recovery.start_recovery_loop(interval_seconds=99, initial_delay_seconds=99)
            try:
                self.assertIs(first, second, "restart must reuse the running loop")
                self.assertEqual(len(threads_after_first), 1, "at most one loop thread per process")
                self.assertTrue(first.thread.daemon)
            finally:
                self.assertTrue(task_recovery.stop_recovery_loop())

        self.assertFalse(first.is_alive())
        self.assertEqual(
            [thread for thread in threading.enumerate() if thread.name == "task-recovery-loop"],
            [],
            "stop must not leave a thread behind",
        )

    def test_stop_timeout_keeps_instance_and_blocks_second_thread(self):
        entered = threading.Event()
        release = threading.Event()

        def blocked_round(queue_names):
            entered.set()
            release.wait(5)
            return {"recovered": 0}

        try:
            loop = task_recovery.start_recovery_loop(
                queue_names=("evaluation",),
                include_startup_reindex_check=False,
                recovery_fn=blocked_round,
                initial_delay_seconds=0.001,
                interval_seconds=30.0,
            )
            self.assertTrue(entered.wait(5), "loop thread did not enter a round")
            # join 超时：单例必须保留 stopping 实例，不得提前清空全局。
            self.assertFalse(task_recovery.stop_recovery_loop(timeout=0.001))
            with self.assertRaises(RuntimeError):
                task_recovery.start_recovery_loop(
                    queue_names=("evaluation",),
                    include_startup_reindex_check=False,
                    recovery_fn=blocked_round,
                    initial_delay_seconds=0.001,
                    interval_seconds=30.0,
                )
        finally:
            release.set()
            task_recovery.stop_recovery_loop(timeout=5)

        self.assertEqual(
            [thread for thread in threading.enumerate() if thread.name == "task-recovery-loop"],
            [],
        )

    def test_alive_loop_rejects_a_different_queue_contract(self):
        entered = threading.Event()
        release = threading.Event()

        def blocked_round(queue_names):
            entered.set()
            release.wait(5)
            return {"recovered": 0}

        try:
            loop = task_recovery.start_recovery_loop(
                queue_names=("evaluation",),
                include_startup_reindex_check=False,
                recovery_fn=blocked_round,
                initial_delay_seconds=0.001,
                interval_seconds=30.0,
            )
            self.assertTrue(entered.wait(5), "loop thread did not enter a round")
            with self.assertRaises(RuntimeError):
                task_recovery.start_recovery_loop(
                    queue_names=("documents",),
                    include_startup_reindex_check=False,
                    recovery_fn=blocked_round,
                    initial_delay_seconds=0.001,
                    interval_seconds=30.0,
                )
            # 同契约仍幂等
            self.assertIs(
                loop,
                task_recovery.start_recovery_loop(
                    queue_names=("evaluation",),
                    include_startup_reindex_check=False,
                    recovery_fn=blocked_round,
                    initial_delay_seconds=0.001,
                    interval_seconds=30.0,
                ),
            )
        finally:
            release.set()
            self.assertTrue(task_recovery.stop_recovery_loop(timeout=5))

    def test_stop_without_a_loop_is_a_noop(self):
        self.assertTrue(task_recovery.stop_recovery_loop())


class WorkerLifecycleTests(TransactionTestCase):
    """worker 命令与合并行为回归（真实 DB，无真实模型调用）。"""

    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(name="Worker lifecycle tenant", api_key="worker-lifecycle")
        self.knowledge_base = KnowledgeBase.objects.create(
            tenant=self.tenant, name="Worker lifecycle knowledge base"
        )
        self.knowledge = Knowledge.objects.create(
            tenant=self.tenant,
            knowledge_base=self.knowledge_base,
            type="file",
            title="worker-lifecycle.pdf",
            source="worker-lifecycle.pdf",
        )

    def tearDown(self):
        with tasks._queue_lock:
            tasks._task_queue.clear()
            tasks._evaluation_task_queue.clear()
            if hasattr(tasks, "_queued_task_ids"):
                tasks._queued_task_ids.clear()
            tasks._queue_worker_running = False
            tasks._evaluation_queue_worker_running = False
        task_recovery.stop_recovery_loop()
        cache.clear()

    def create_task(self, *, status="pending", queue_name="documents", knowledge=None):
        knowledge = knowledge or self._make_knowledge("worker-lifecycle.pdf")
        return TaskRecord.objects.create(
            task_type="process_knowledge",
            status=status,
            queue_name=queue_name,
            payload={"knowledge_id": knowledge.id},
        )

    def _make_knowledge(self, title):
        return Knowledge.objects.create(
            tenant=self.tenant,
            knowledge_base=self.knowledge_base,
            type="file",
            title=title,
            source=title,
        )

    def create_evaluation_task(self, *, status="pending", **fields):
        defaults = {
            "task_type": "open_rag_evaluation",
            "status": status,
            "queue_name": "evaluation",
            "payload": {
                "tenant_id": self.tenant.id,
                "dataset_id": "open_rag_benchmark_100",
                "dataset_version": "arxiv-v1",
            },
        }
        defaults.update(fields)
        return TaskRecord.objects.create(**defaults)

    # -- --once 语义 ------------------------------------------------------

    def test_once_recovers_then_drains_and_exits_without_daemon(self):
        now = timezone.now()
        record = self.create_evaluation_task(
            status="running",
            claimed_by="dead-worker",
            lease_expires_at=now - timedelta(seconds=1),
            updated_at=now - timedelta(seconds=91),
            payload={
                "tenant_id": self.tenant.id,
                "dataset_id": "open_rag_benchmark_100",
                "dataset_version": "arxiv-v1",
                "_worker_token": "dead-worker",
            },
        )

        with patch(
            "personal_knowledge_base.tasks.resolve_task_callable",
            return_value=lambda: {"done": True},
        ):
            call_command("run_task_worker", "--queue", "evaluation", "--once")

        record.refresh_from_db()
        self.assertEqual(record.status, "completed")
        self.assertEqual(record.result, {"done": True})
        self.assertEqual(record.claimed_by, "")
        self.assertEqual(record.attempt_count, 1, "successor must claim exactly once")
        self.assertEqual(
            [thread for thread in threading.enumerate() if thread.name == "task-recovery-loop"],
            [],
            "--once must not leave a daemon recovery loop",
        )

    def test_once_runs_deterministic_recovery_with_queue_scope_before_draining(self):
        record = self.create_evaluation_task()
        calls = []

        def recovery_stub(now=None, queue_names=None):
            calls.append(("recover", tuple(queue_names or ())))
            return {"recovered": 0}

        def resolve_stub(snapshot):
            calls.append(("drain", snapshot.id))
            return lambda: {"done": True}

        with (
            patch("personal_knowledge_base.tasks.recover_incomplete_tasks", side_effect=recovery_stub),
            patch("personal_knowledge_base.tasks.resolve_task_callable", side_effect=resolve_stub),
        ):
            call_command("run_task_worker", "--queue", "evaluation", "--once")

        self.assertEqual(
            calls,
            [("recover", ("evaluation",)), ("drain", record.id)],
            "--once must perform one deterministic queue-scoped recovery first, then drain",
        )

    def test_once_drains_multiple_pending_until_empty(self):
        first = self.create_evaluation_task()
        second = self.create_evaluation_task()

        with patch(
            "personal_knowledge_base.tasks.resolve_task_callable",
            return_value=lambda: {"done": True},
        ):
            call_command("run_task_worker", "--queue", "evaluation", "--once")

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.status, second.status), ("completed", "completed"))

    def test_once_leaves_other_queues_untouched(self):
        evaluation = self.create_evaluation_task()
        documents = self.create_task()

        with patch(
            "personal_knowledge_base.tasks.resolve_task_callable",
            return_value=lambda: {"done": True},
        ):
            call_command("run_task_worker", "--queue", "evaluation", "--once")

        evaluation.refresh_from_db()
        documents.refresh_from_db()
        self.assertEqual(evaluation.status, "completed")
        self.assertEqual(documents.status, "pending", "--queue scope must not drain other queues")

    def test_once_recovery_failure_is_commanderror_not_success(self):
        """确定性恢复失败时 --once 必须 CommandError 非零退出，不得照常 drain。"""
        drained = []

        with (
            patch(
                "personal_knowledge_base.management.commands.run_task_worker.run_recovery_round",
                return_value=None,
            ),
            patch(
                "personal_knowledge_base.management.commands.run_task_worker.run_persisted_task",
                side_effect=lambda task_id: drained.append(task_id),
            ),
        ):
            with self.assertRaises(CommandError):
                call_command("run_task_worker", "--queue", "evaluation", "--once")

        self.assertEqual(drained, [], "failed recovery must not fall through to draining")

    # -- poll 间隔契约 -----------------------------------------------------

    def test_poll_interval_rejects_invalid_and_nonfinite_values(self):
        for value in ("nan", "inf", "-inf", "-1", "0", "junk"):
            with self.subTest(value=value):
                with self.assertRaises(CommandError):
                    call_command("run_task_worker", "--queue", "evaluation", "--poll-interval", value)

    def test_poll_interval_lower_bound_prevents_busy_wait(self):
        self.assertEqual(normalised_poll_interval("0.001"), 0.1)
        self.assertEqual(normalised_poll_interval("2.5"), 2.5)
        self.assertEqual(normalised_poll_interval(0.05), 0.1)

    # -- 正常模式：繁忙扫描 + finally 停止 + queue 边界 ---------------------

    def test_normal_mode_scans_while_busy_and_stops_loop_on_exit(self):
        record = self.create_evaluation_task()
        started = {}
        scan_seen = threading.Event()
        busy_started = threading.Event()
        recovery_calls = []

        def counting_recovery(queue_names):
            recovery_calls.append(tuple(queue_names or ()))
            scan_seen.set()
            return {"recovered": 0}

        def long_sync_task(task_id):
            busy_started.set()
            if not scan_seen.wait(5):
                raise AssertionError("recovery loop did not scan while the worker was busy")
            raise KeyboardInterrupt("driver: busy scan proven")

        def loop_factory(**kwargs):
            started.update(kwargs)
            loop = task_recovery.TaskRecoveryLoop(
                interval_seconds=0.02,
                initial_delay_seconds=0.01,
                queue_names=kwargs["queue_names"],
                include_startup_reindex_check=kwargs["include_startup_reindex_check"],
                recovery_fn=counting_recovery,
            )
            loop.start()
            return loop

        with (
            patch(
                "personal_knowledge_base.management.commands.run_task_worker.start_recovery_loop",
                side_effect=loop_factory,
            ),
            patch(
                "personal_knowledge_base.management.commands.run_task_worker.run_persisted_task",
                side_effect=long_sync_task,
            ),
        ):
            with self.assertRaises(KeyboardInterrupt):
                call_command("run_task_worker", "--queue", "evaluation")

        self.assertEqual(started, {
            "queue_names": ("evaluation",),
            "include_startup_reindex_check": False,
        })
        self.assertTrue(busy_started.is_set())
        self.assertEqual(recovery_calls, [("evaluation",)], "scan must happen while the sync task runs")
        loop_thread = [
            thread for thread in threading.enumerate() if thread.name == "task-recovery-loop"
        ]
        self.assertEqual(loop_thread, [], "finally must stop the loop on command exception")
        self.assertEqual(record.status, "pending", "interrupted driver must not touch the record")

    def test_normal_mode_web_default_loop_recovers_all_queues(self):
        """web 入口（queue_names=None）恢复原有全部队列；worker 范围见上例。"""
        stop_requested = threading.Event()

        def recovery(queue_names):
            self.assertIsNone(queue_names)
            stop_requested.set()
            return {"recovered": 0}

        loop = task_recovery.TaskRecoveryLoop(
            interval_seconds=0.02,
            initial_delay_seconds=0.01,
            recovery_fn=recovery,
            include_startup_reindex_check=False,
        )
        loop.start()
        try:
            self.assertTrue(stop_requested.wait(5), "default loop must scan all queues (queue_names=None)")
        finally:
            self.assertTrue(loop.stop())

    # -- 合并回归：同步顺序 + 取消 + 租约回归 -------------------------------

    def test_sync_sequential_cancel_and_lease_regression_combined(self):
        now = timezone.now()
        # 1) 同步顺序任务：按入队顺序经顺序队列执行并完成
        order = []
        first = self.create_task()
        second = self.create_task()
        first_fn = lambda: (order.append("first"), {"n": 1})[1]
        second_fn = lambda: (order.append("second"), {"n": 2})[1]

        with patch.object(tasks, "_executor"):
            tasks._enqueue_sequential(first.id, first_fn)
            tasks._enqueue_sequential(second.id, second_fn)

        self.assertEqual(list(tasks._task_queue), [(first.id, first_fn), (second.id, second_fn)])
        tasks._process_queue()
        self.assertEqual(order, ["first", "second"])
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.status, second.status), ("completed", "completed"))

        # 2) 取消：持有者运行中收到取消请求 → cancelled、租约清空
        cancel_target = self.create_task()

        def request_cancel_then_return():
            TaskRecord.objects.filter(id=cancel_target.id).update(cancel_requested_at=timezone.now())
            return {"cancelled": False}

        tasks._run_task(cancel_target.id, request_cancel_then_return)
        cancel_target.refresh_from_db()
        self.assertEqual(cancel_target.status, "cancelled")
        self.assertEqual(cancel_target.claimed_by, "")
        self.assertIsNone(cancel_target.lease_expires_at)

        # 3) 租约回归：fresh 租约不动；过期租约恰好重置一次，重复扫描不再重置
        # （fresh/expired 各自独立 knowledge，避免触发同 knowledge 合并语义）
        fresh = self.create_task(status="running")
        TaskRecord.objects.filter(id=fresh.id).update(
            payload={"knowledge_id": fresh.payload["knowledge_id"], "_worker_token": "owner"},
            updated_at=now - timedelta(seconds=10),
        )
        expired = self.create_task(status="running")
        TaskRecord.objects.filter(id=expired.id).update(
            payload={"knowledge_id": expired.payload["knowledge_id"], "_worker_token": "dead"},
            updated_at=now - timedelta(seconds=91),
        )

        with patch(
            "personal_knowledge_base.tasks._enqueue_sequential", return_value=True
        ) as enqueue_sequential:
            first_pass = tasks.recover_incomplete_tasks(now=now)
            second_pass = tasks.recover_incomplete_tasks(now=now)

        fresh.refresh_from_db()
        expired.refresh_from_db()
        self.assertEqual(fresh.status, "running", "active lease holder must never be reset")
        self.assertEqual(expired.status, "pending")
        self.assertEqual(first_pass["stale_reset"], 1)
        self.assertEqual(second_pass["stale_reset"], 0, "regression: reset must not repeat")
        self.assertEqual(enqueue_sequential.call_count, 2)

    def test_recovery_loop_scans_while_worker_busy(self):
        """真实 loop 线程 + 真实恢复：worker 同步执行长任务期间仍扫描恢复。"""
        busy_task = self.create_task()
        expired = self.create_task(status="running")
        TaskRecord.objects.filter(id=expired.id).update(
            payload={"knowledge_id": expired.payload["knowledge_id"], "_worker_token": "dead"},
            updated_at=timezone.now() - timedelta(seconds=91),
        )

        busy_fn_entered = threading.Event()
        release_busy_fn = threading.Event()
        busy_errors = []

        def busy_fn():
            busy_fn_entered.set()
            if not release_busy_fn.wait(10):
                busy_errors.append(TimeoutError("busy fn was not released"))
            return {"busy": True}

        def run_busy_worker():
            try:
                tasks._run_task(busy_task.id, busy_fn)
            except Exception as exc:  # pragma: no cover - _run_task 不应抛出
                busy_errors.append(exc)

        worker_thread = threading.Thread(target=run_busy_worker, name="busy-worker")
        worker_thread.start()
        loop = task_recovery.TaskRecoveryLoop(
            interval_seconds=0.05,
            initial_delay_seconds=0.01,
            include_startup_reindex_check=False,
        )
        try:
            self.assertTrue(busy_fn_entered.wait(5), "busy worker did not start")
            self.assertTrue(worker_thread.is_alive(), "busy worker must still be executing")

            with patch(
                "personal_knowledge_base.tasks._enqueue_sequential", return_value=True
            ) as enqueue_sequential:
                loop.start()
                scanned = self._wait_for(lambda: enqueue_sequential.call_count >= 1)
                self.assertTrue(
                    scanned,
                    "recovery loop did not reset the expired lease while the worker was busy",
                )
                self.assertTrue(worker_thread.is_alive(), "busy worker still runs during the scan")
        finally:
            release_busy_fn.set()
            worker_thread.join(5)
            loop_stopped = loop.stop() if loop.is_alive() else True

        self.assertEqual(busy_errors, [])
        self.assertFalse(worker_thread.is_alive())
        self.assertTrue(loop_stopped, "stop must join the loop thread")
        expired.refresh_from_db()
        self.assertEqual(expired.status, "pending", "expired lease recovered during busy execution")

    @staticmethod
    def _wait_for(predicate, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.02)
        return predicate()


# ---------------------------------------------------------------------------
# 真实跨进程：持有者崩溃 → 租约过期 → 后继 --once 恰好认领一次
# ---------------------------------------------------------------------------

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
_CHILD_TIMEOUT_SECONDS = 90
_MIGRATE_TIMEOUT_SECONDS = 240

_CRASH_WORKER_SCRIPT = r"""
import json
import os
import sys
import time

args = json.loads(sys.argv[1])
os.chdir(args["repo_root"])
sys.path.insert(0, args["repo_root"])
os.environ.clear()
os.environ.update(args["env"])
# django.setup 之前声明管理命令 argv：apps.ready 的恢复调度按管理命令过滤，
# 子进程内不得再起 web 恢复 loop。
sys.argv = ["manage.py", "run_task_worker", "--queue", args["queue"]]

import django

django.setup()

from datetime import timedelta

from django.core.management import call_command
from django.utils import timezone

from personal_knowledge_base import tasks
from personal_knowledge_base.models import TaskRecord

tasks._ensure_wal_mode()

mode = args["mode"]
task_id = args["task_id"]


def write_marker(path, value):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle)


def append_marker(path, value):
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(value) + "\n")


def snapshot(record):
    return {
        "status": record.status,
        "claimed_by": record.claimed_by,
        "attempt_count": record.attempt_count,
        "result": record.result,
    }


if mode == "migrate":
    call_command("migrate", "--noinput", verbosity=0)
    print("MIGRATED")
    sys.exit(0)

if mode == "holder":
    TaskRecord.objects.create(
        id=task_id,
        task_type="open_rag_evaluation",
        status="pending",
        queue_name=args["queue"],
        payload={
            "tenant_id": "crash-tenant",
            "dataset_id": "open_rag_benchmark_100",
            "dataset_version": "arxiv-v1",
        },
    )

    def blocking_fn():
        # _run_task 已以新 token 认领并启动心跳；记录生产认领痕迹后
        # 持有直到被测试进程 SIGKILL（真实崩溃：无 finally、无心跳停止）。
        record = TaskRecord.objects.get(id=task_id)
        append_marker(args["run_marker"], {"role": "holder", "claimed_by": record.claimed_by})
        write_marker(args["started_marker"], {"claimed_by": record.claimed_by})
        time.sleep(args.get("hold_seconds", 60))
        return {"owner": "holder"}

    tasks._run_task(task_id, blocking_fn)
    sys.exit(0)

if mode == "expire_lease":
    # 时间压缩：心跳已死，把租约/updated_at 直接写进过去，等价于等待 90s 窗口
    # 过去（任务简报明确允许测试缩短间隔）。
    now = timezone.now()
    updated = TaskRecord.objects.filter(id=task_id, status="running").update(
        lease_expires_at=now - timedelta(seconds=1),
        updated_at=now - timedelta(seconds=91),
    )
    record = TaskRecord.objects.filter(id=task_id).first()
    write_marker(args["result_path"], {
        "updated": updated,
        "status": record.status if record else None,
        "claimed_by": record.claimed_by if record else None,
        "lease_expired": bool(record and record.lease_expires_at and record.lease_expires_at < now),
    })
    print("EXPIRED")
    sys.exit(0)

if mode == "successor":
    successor_calls = []

    def stub_fn():
        successor_calls.append(1)
        append_marker(args["run_marker"], {"role": "successor", "call": len(successor_calls)})
        return {"done": True}

    original_resolve = tasks.resolve_task_callable

    def resolve(record):
        if record.id == task_id:
            return stub_fn
        return original_resolve(record)

    tasks.resolve_task_callable = resolve
    call_command("run_task_worker", "--queue", args["queue"], "--once", verbosity=2)
    record = TaskRecord.objects.get(id=task_id)
    write_marker(args["result_path"], {
        **snapshot(record),
        "successor_calls": len(successor_calls),
    })
    print("SUCCESSOR_DONE")
    sys.exit(0)

raise SystemExit("unknown mode: %s" % mode)
"""


class CrashRecoveryHandoffProcessTests(SimpleTestCase):
    """持有者进程真实崩溃后，后继 worker 经真实恢复恰好认领一次。"""

    maxDiff = None

    _GRACE_SECONDS = 10

    def _isolated_env(self, **overrides):
        env = {key: os.environ[key] for key in _BASE_ENV_KEYS if key in os.environ}
        env.update(_ISOLATED_SETTINGS_ENV)
        env.update(overrides)
        return env

    def _spawn(self, args):
        return subprocess.Popen(
            [sys.executable, "-c", _CRASH_WORKER_SCRIPT, json.dumps(args)],
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

    def _finish(self, process, timeout=_CHILD_TIMEOUT_SECONDS):
        stdout, stderr = self._collect(process, timeout)
        self.assertEqual(
            process.returncode,
            0,
            "worker subprocess failed (exit %s)\n--- stdout ---\n%s\n--- stderr tail ---\n%s"
            % (process.returncode, stdout, "\n".join((stderr or "").splitlines()[-20:])),
        )
        return stdout, stderr

    def _shutdown(self, process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=self._GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=self._GRACE_SECONDS)

    def _wait_for_file(self, path, timeout=_WAIT_FOR_FILE_SECONDS):
        deadline = time.monotonic() + timeout
        while not os.path.exists(path):
            if time.monotonic() > deadline:
                raise TimeoutError("timed out waiting for %s" % os.path.basename(path))
            time.sleep(0.02)

    def _read_json(self, path):
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def _read_lines(self, path):
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_crashed_holder_lease_is_recovered_and_claimed_exactly_once(self):
        with tempfile.TemporaryDirectory(prefix="marlin-r2b-crash-") as tmp:
            db_path = os.path.join(tmp, "shared.sqlite3")
            user_root = os.path.join(tmp, "user-root")
            os.makedirs(user_root)
            run_marker = os.path.join(tmp, "runs.jsonl")
            started_marker = os.path.join(tmp, "started.json")
            expire_marker = os.path.join(tmp, "expired.json")
            done_marker = os.path.join(tmp, "done.json")
            task_id = "crash-handoff-task-1"
            queue = "evaluation"

            def base_args(mode, extra=None):
                return {
                    "mode": mode,
                    "repo_root": str(_REPO_ROOT),
                    "queue": queue,
                    "task_id": task_id,
                    "run_marker": run_marker,
                    "started_marker": started_marker,
                    "result_path": expire_marker if mode == "expire_lease" else done_marker,
                    "env": self._isolated_env(DJANGO_DB_PATH=db_path, APP_DATA_DIR=user_root),
                    **(extra or {}),
                }

            migrate = self._spawn(base_args("migrate"))
            try:
                self._finish(migrate, timeout=_MIGRATE_TIMEOUT_SECONDS)
            finally:
                self._shutdown(migrate)

            holder = self._spawn(base_args("holder"))
            try:
                self._wait_for_file(started_marker)
                # 真实崩溃：SIGKILL，无 finally、无心跳停止；行保持 running+租约。
                holder.kill()
                holder.wait(timeout=self._GRACE_SECONDS)
                self.assertNotEqual(holder.returncode, 0)
            finally:
                self._shutdown(holder)

            expire = self._spawn(base_args("expire_lease"))
            try:
                self._finish(expire)
            finally:
                self._shutdown(expire)
            expired_state = self._read_json(expire_marker)
            self.assertEqual(expired_state["updated"], 1)
            self.assertEqual(expired_state["status"], "running")
            self.assertTrue(expired_state["claimed_by"], "crashed holder must still own the row")
            self.assertTrue(expired_state["lease_expired"])

            successor = self._spawn(base_args("successor"))
            try:
                self._finish(successor)
            finally:
                self._shutdown(successor)

            final = self._read_json(done_marker)
            self.assertEqual(final["status"], "completed")
            self.assertEqual(final["claimed_by"], "")
            self.assertEqual(final["result"], {"done": True})
            self.assertEqual(
                final["attempt_count"], 2,
                "holder claim + exactly one successor claim",
            )
            self.assertEqual(final["successor_calls"], 1)

            runs = self._read_lines(run_marker)
            self.assertEqual([run["role"] for run in runs], ["holder", "successor"])
            self.assertEqual(runs[1], {"role": "successor", "call": 1})
