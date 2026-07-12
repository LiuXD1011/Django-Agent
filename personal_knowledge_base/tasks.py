import logging
import os
import sys
import time
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import OperationalError, ProgrammingError, close_old_connections, connection
from django.utils import timezone

from .models import Knowledge, TaskRecord


logger = logging.getLogger(__name__)
_executor: ThreadPoolExecutor | None = None
MAX_RETRIES = 3
RETRY_DELAY = 3  # 秒
HEARTBEAT_INTERVAL = 15
STALE_LEASE_SECONDS = 90
STARTUP_RECOVERY_DELAY = 0.1

# 任务队列：SQLite 不支持并发写入，使用队列保证顺序执行
_task_queue: deque = deque()
_queued_task_ids: set[str] = set()
_queue_lock = threading.Lock()
_queue_worker_running = False


def start_task_runner():
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=settings.APP_TASK_WORKERS, thread_name_prefix="personal-kb-task")


def enqueue(task_type: str, fn, payload: dict | None = None) -> TaskRecord:
    start_task_runner()
    record = TaskRecord.objects.create(task_type=task_type, payload=payload or {}, status="pending")
    cache.set(f"task:{record.id}", {"status": "pending", "progress": 0}, timeout=86400)
    if getattr(settings, "APP_TASKS_SYNC", False):
        _run_task(record.id, fn)
        return TaskRecord.objects.get(id=record.id)

    # SQLite 不支持并发写入，文档处理任务使用队列顺序执行
    if task_type == "process_knowledge":
        _enqueue_sequential(record.id, fn)
    else:
        assert _executor is not None
        _executor.submit(_run_task, record.id, fn)
    return record


def _enqueue_sequential(task_id: str, fn):
    """将任务加入顺序执行队列（避免 SQLite 并发写入锁定）。"""
    global _queue_worker_running
    start_task_runner()
    with _queue_lock:
        if task_id in _queued_task_ids:
            return False
        _queued_task_ids.add(task_id)
        _task_queue.append((task_id, fn))
        if not _queue_worker_running:
            _queue_worker_running = True
            assert _executor is not None
            _executor.submit(_process_queue)
    return True


def _process_queue():
    """顺序处理队列中的任务。"""
    global _queue_worker_running
    while True:
        with _queue_lock:
            if not _task_queue:
                _queue_worker_running = False
                return
            task_id, fn = _task_queue.popleft()
            _queued_task_ids.discard(task_id)
        try:
            _run_task(task_id, fn)
        except Exception:
            logger.exception("Queue task %s failed unexpectedly", task_id)
        # 任务间短暂延迟，让 SQLite 释放锁
        time.sleep(0.5)


def _run_task(task_id: str, fn):
    close_old_connections()
    # 确保 SQLite WAL 模式已启用
    _ensure_wal_mode()
    claimed = TaskRecord.objects.filter(id=task_id, status="pending").update(
        status="running",
        progress=0.1,
        updated_at=timezone.now(),
    )
    if not claimed:
        close_old_connections()
        return

    record = TaskRecord.objects.get(id=task_id)
    cache.set(f"task:{task_id}", {"status": "running", "progress": 0.1}, timeout=86400)

    stop_event = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat_task,
        args=(task_id, stop_event),
        daemon=True,
        name=f"task-heartbeat-{task_id}",
    )
    heartbeat.start()

    try:
        last_exc = None
        for attempt in range(MAX_RETRIES):
            try:
                result = fn() or {}
                record.status = "completed"
                record.progress = 1
                record.result = result
                record.error_message = ""
                record.save(update_fields=["status", "progress", "result", "error_message", "updated_at"])
                cache.set(f"task:{task_id}", {"status": "completed", "progress": 1, "result": result}, timeout=86400)
                return
            except Exception as exc:
                last_exc = exc
                if "database is locked" in str(exc) and attempt < MAX_RETRIES - 1:
                    logger.warning("task %s hit database lock, retrying (%d/%d)...", task_id, attempt + 1, MAX_RETRIES)
                    close_old_connections()
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                break

        # 所有重试都失败
        logger.error("task %s failed: %s", task_id, last_exc)
        record.status = "failed"
        record.error_message = str(last_exc)
        record.save(update_fields=["status", "error_message", "updated_at"])
        cache.set(
            f"task:{task_id}",
            {"status": "failed", "progress": record.progress, "error_message": str(last_exc)},
            timeout=86400,
        )
    finally:
        stop_event.set()
        heartbeat.join()
        close_old_connections()


def _heartbeat_task(task_id: str, stop_event):
    while not stop_event.wait(HEARTBEAT_INTERVAL):
        close_old_connections()
        try:
            refreshed = TaskRecord.objects.filter(id=task_id, status="running").update(updated_at=timezone.now())
            if not refreshed:
                return
        except (OperationalError, ProgrammingError) as exc:
            logger.warning("Task %s heartbeat failed; retrying: %s", task_id, exc)
        finally:
            close_old_connections()


def resolve_task_callable(record: TaskRecord):
    if record.task_type != "process_knowledge":
        return None
    payload = record.payload if isinstance(record.payload, dict) else {}
    knowledge_id = str(payload.get("knowledge_id") or "")
    if not knowledge_id:
        return None
    from .document_processing import process_knowledge

    return lambda: (process_knowledge(knowledge_id), {"knowledge_id": knowledge_id})[1]


def _mark_recovery_failed(record: TaskRecord, message: str, now) -> bool:
    updated = TaskRecord.objects.filter(id=record.id, status__in=("pending", "running")).update(
        status="failed",
        error_message=message,
        updated_at=now,
    )
    if updated:
        cache.set(
            f"task:{record.id}",
            {"status": "failed", "progress": record.progress, "error_message": message},
            timeout=86400,
        )
    return bool(updated)


def recover_incomplete_tasks(now=None) -> dict:
    now = now or timezone.now()
    stale_before = now - timedelta(seconds=STALE_LEASE_SECONDS)
    stale_reset = TaskRecord.objects.filter(
        task_type="process_knowledge",
        status="running",
        updated_at__lt=stale_before,
    ).update(status="pending", updated_at=now)

    counts = {
        "recovered": 0,
        "stale_reset": stale_reset,
        "superseded": 0,
        "discarded": 0,
    }
    recoverable_by_knowledge: dict[str, list[TaskRecord]] = {}
    records = TaskRecord.objects.filter(
        task_type="process_knowledge",
        status__in=("pending", "running"),
    ).order_by("created_at", "id")

    for record in records:
        payload = record.payload if isinstance(record.payload, dict) else {}
        knowledge_id = str(payload.get("knowledge_id") or "")
        knowledge_is_valid = bool(knowledge_id) and Knowledge.objects.filter(
            id=knowledge_id,
            deleted_at__isnull=True,
        ).exclude(parse_status="cancelled").exists()
        if not knowledge_is_valid:
            message = f"knowledge {knowledge_id or '<missing>'} is not recoverable"
            if _mark_recovery_failed(record, message, now):
                counts["discarded"] += 1
            continue
        recoverable_by_knowledge.setdefault(knowledge_id, []).append(record)

    for group in recoverable_by_knowledge.values():
        kept = group[0]
        for duplicate in group[1:]:
            message = f"superseded by recoverable task {kept.id}"
            if _mark_recovery_failed(duplicate, message, now):
                counts["superseded"] += 1

        kept.refresh_from_db(fields=("status", "payload"))
        if kept.status != "pending":
            continue
        fn = resolve_task_callable(kept)
        if fn is None:
            if _mark_recovery_failed(kept, "task payload is not recoverable", now):
                counts["discarded"] += 1
            continue
        if _enqueue_sequential(kept.id, fn):
            counts["recovered"] += 1

    return counts


def should_schedule_recovery(argv=None, environ=None) -> bool:
    argv = list(sys.argv if argv is None else argv)
    environ = os.environ if environ is None else environ
    command = argv[1] if len(argv) > 1 else ""
    if command in {"test", "migrate", "makemigrations", "shell", "collectstatic"}:
        return False
    if command == "runserver":
        return str(environ.get("RUN_MAIN", "")).lower() == "true"
    return True


def schedule_startup_recovery():
    if not should_schedule_recovery():
        return None

    def run_recovery():
        close_old_connections()
        try:
            result = recover_incomplete_tasks()
            logger.info("Task startup recovery completed: %s", result)
        except (OperationalError, ProgrammingError) as exc:
            logger.warning("Task startup recovery skipped: %s", exc)
        finally:
            close_old_connections()

    timer = threading.Timer(STARTUP_RECOVERY_DELAY, run_recovery)
    timer.daemon = True
    timer.name = "task-startup-recovery"
    timer.start()
    return timer


def _ensure_wal_mode():
    """确保 SQLite 使用 WAL 模式，允许读写并发。"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
    except Exception:
        pass


def task_status(task_id: str):
    cached = cache.get(f"task:{task_id}")
    if cached:
        return cached
    record = TaskRecord.objects.filter(id=task_id).first()
    if not record:
        return {"status": "not_found", "progress": 0}
    return {
        "status": record.status,
        "progress": record.progress,
        "result": record.result,
        "error_message": record.error_message,
    }
