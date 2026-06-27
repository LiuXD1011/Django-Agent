import logging
import time
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections, connection

from .models import TaskRecord


logger = logging.getLogger(__name__)
_executor: ThreadPoolExecutor | None = None
MAX_RETRIES = 3
RETRY_DELAY = 3  # 秒

# 任务队列：SQLite 不支持并发写入，使用队列保证顺序执行
_task_queue: deque = deque()
_queue_lock = threading.Lock()
_queue_worker_running = False


def start_task_runner():
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=settings.WEKNORA_TASK_WORKERS, thread_name_prefix="personal-kb-task")


def enqueue(task_type: str, fn, payload: dict | None = None) -> TaskRecord:
    start_task_runner()
    record = TaskRecord.objects.create(task_type=task_type, payload=payload or {}, status="pending")
    cache.set(f"task:{record.id}", {"status": "pending", "progress": 0}, timeout=86400)
    if getattr(settings, "WEKNORA_TASKS_SYNC", False):
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
    with _queue_lock:
        _task_queue.append((task_id, fn))
        if not _queue_worker_running:
            _queue_worker_running = True
            _executor.submit(_process_queue)


def _process_queue():
    """顺序处理队列中的任务。"""
    global _queue_worker_running
    while True:
        with _queue_lock:
            if not _task_queue:
                _queue_worker_running = False
                return
            task_id, fn = _task_queue.popleft()
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
    record = TaskRecord.objects.get(id=task_id)
    record.status = "running"
    record.progress = 0.1
    record.save(update_fields=["status", "progress", "updated_at"])
    cache.set(f"task:{task_id}", {"status": "running", "progress": 0.1}, timeout=86400)

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
    logger.exception("task %s failed", task_id)
    record.status = "failed"
    record.error_message = str(last_exc)
    record.save(update_fields=["status", "error_message", "updated_at"])
    cache.set(f"task:{task_id}", {"status": "failed", "progress": record.progress, "error_message": str(last_exc)}, timeout=86400)
    close_old_connections()


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
