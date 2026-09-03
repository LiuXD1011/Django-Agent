import logging
import os
import sys
import time
import threading
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import OperationalError, ProgrammingError, close_old_connections, connection, models, transaction
from django.utils import timezone

from .models import Knowledge, TaskRecord


logger = logging.getLogger(__name__)
_executor: ThreadPoolExecutor | None = None
MAX_RETRIES = 3
RETRY_DELAY = 3  # 秒
HEARTBEAT_INTERVAL = 15
STALE_LEASE_SECONDS = 90
STARTUP_RECOVERY_DELAY = 0.1
WORKER_TOKEN_KEY = "_worker_token"
OPEN_RAG_EVALUATION_TASK_TYPE = "open_rag_evaluation"
TASK_QUEUES = {
    "process_knowledge": "documents",
    "rebuild_vector_index": "documents",
    "prepare_open_rag_dataset": "evaluation",
    OPEN_RAG_EVALUATION_TASK_TYPE: "evaluation",
}
MODEL_INTENSIVE_TASK_TYPES = {
    "process_knowledge",
    "rebuild_vector_index",
    "prepare_open_rag_dataset",
    OPEN_RAG_EVALUATION_TASK_TYPE,
}
RECOVERABLE_SEQUENTIAL_TASK_TYPES = {
    "prepare_open_rag_dataset",
    OPEN_RAG_EVALUATION_TASK_TYPE,
}

# 任务队列：SQLite 不支持并发写入，使用队列保证顺序执行
_task_queue: deque = deque()
_evaluation_task_queue: deque = deque()
_queued_task_ids: set[str] = set()
_queue_lock = threading.Lock()
_queue_worker_running = False
_evaluation_queue_worker_running = False


def start_task_runner():
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=max(2, settings.APP_TASK_WORKERS), thread_name_prefix="personal-kb-task")


def enqueue(task_type: str, fn=None, payload: dict | None = None) -> TaskRecord:
    record = TaskRecord.objects.create(
        task_type=task_type,
        payload=payload or {},
        status="pending",
        queue_name=TASK_QUEUES.get(task_type, "default"),
    )
    cache.set(f"task:{record.id}", {"status": "pending", "progress": 0}, timeout=86400)
    if fn is None:
        # Recovery-safe task types resolve their callable only after the record
        # has an ID.  This avoids a closure race when asynchronous dispatch
        # starts before ``enqueue`` returns.
        fn = lambda task_id=record.id: _run_resolved_task(task_id)
    if getattr(settings, "APP_TASKS_SYNC", False):
        _run_task(record.id, fn)
        return TaskRecord.objects.get(id=record.id)

    # Evaluation jobs are consumed by ``run_task_worker --queue evaluation``.
    # Running them in the web process makes leases and restart recovery moot.
    if record.queue_name == "evaluation":
        return record

    _schedule_async_dispatch(task_type, record.id, fn)
    return record


def dispatch_existing_task(task_id: str) -> bool:
    """Dispatch a pending persisted task without creating a new record."""
    record = TaskRecord.objects.filter(id=task_id, status="pending").first()
    if record is None:
        return False
    fn = resolve_task_callable(record)
    if fn is None:
        return False
    _dispatch_task(record.task_type, record.id, fn)
    return True


def run_persisted_task(task_id: str) -> bool:
    """Run one pending task synchronously in a dedicated worker process."""
    record = TaskRecord.objects.filter(id=task_id, status="pending").first()
    if record is None:
        return False
    try:
        fn = resolve_task_callable(record)
    except Exception as exc:
        logger.exception("Unable to resolve persisted task %s", task_id)
        _mark_recovery_failed(record, f"unable to resolve task callable: {type(exc).__name__}", timezone.now())
        return False
    if fn is None:
        _mark_recovery_failed(record, "task payload is not recoverable", timezone.now())
        return False
    _run_task(record.id, fn)
    return True


def _schedule_async_dispatch(task_type: str, task_id: str, fn):
    if not connection.in_atomic_block:
        _dispatch_task(task_type, task_id, fn)
        return

    def dispatch_after_commit(task_type=task_type, task_id=task_id, fn=fn):
        try:
            _dispatch_task(task_type, task_id, fn)
        except Exception:
            logger.exception("Failed to dispatch committed task %s; it remains pending for recovery", task_id)

    try:
        transaction.on_commit(dispatch_after_commit)
    except Exception:
        logger.exception("Failed to schedule committed task %s for dispatch; it remains pending for recovery", task_id)


def _dispatch_task(task_type: str, task_id: str, fn):
    start_task_runner()

    # SQLite 不支持并发写入，文档处理与向量重建任务使用队列顺序执行
    if task_type in MODEL_INTENSIVE_TASK_TYPES:
        _enqueue_sequential(task_id, fn)
    else:
        assert _executor is not None
        _executor.submit(_run_task, task_id, fn)


def _enqueue_sequential(task_id: str, fn, queue_name: str | None = None):
    """将任务加入顺序执行队列（避免 SQLite 并发写入锁定）。"""
    global _queue_worker_running, _evaluation_queue_worker_running
    start_task_runner()
    if queue_name is None:
        queue_name = TaskRecord.objects.filter(id=task_id).values_list("queue_name", flat=True).first() or "default"
    is_evaluation = queue_name == "evaluation"
    queue = _evaluation_task_queue if is_evaluation else _task_queue
    with _queue_lock:
        if task_id in _queued_task_ids:
            return False
        _queued_task_ids.add(task_id)
        queue.append((task_id, fn))
        worker_running = _evaluation_queue_worker_running if is_evaluation else _queue_worker_running
        if not worker_running:
            if is_evaluation:
                _evaluation_queue_worker_running = True
            else:
                _queue_worker_running = True
            assert _executor is not None
            _executor.submit(_process_evaluation_queue if is_evaluation else _process_queue)
    return True


def _drain_queue(queue: deque, *, evaluation: bool):
    """顺序处理队列中的任务。"""
    global _queue_worker_running, _evaluation_queue_worker_running
    while True:
        with _queue_lock:
            if not queue:
                if evaluation:
                    _evaluation_queue_worker_running = False
                else:
                    _queue_worker_running = False
                return
            task_id, fn = queue.popleft()
            _queued_task_ids.discard(task_id)
        try:
            _run_task(task_id, fn)
        except Exception:
            logger.exception("Queue task %s failed unexpectedly", task_id)
        # 任务间短暂延迟，让 SQLite 释放锁
        time.sleep(0.5)


def _process_queue():
    _drain_queue(_task_queue, evaluation=False)


def _process_evaluation_queue():
    _drain_queue(_evaluation_task_queue, evaluation=True)


def _run_task(task_id: str, fn):
    close_old_connections()
    # 确保 SQLite WAL 模式已启用
    _ensure_wal_mode()
    pending_payload = TaskRecord.objects.filter(id=task_id, status="pending").values_list("payload", flat=True).first()
    if pending_payload is None:
        close_old_connections()
        return
    original_payload = _payload_without_worker_token(pending_payload)
    worker_token = uuid.uuid4().hex
    claimed_payload = {**original_payload, WORKER_TOKEN_KEY: worker_token}
    claimed = TaskRecord.objects.filter(id=task_id, status="pending").update(
        status="running",
        progress=0.1,
        payload=claimed_payload,
        claimed_by=worker_token,
        lease_expires_at=timezone.now() + timedelta(seconds=STALE_LEASE_SECONDS),
        attempt_count=models.F("attempt_count") + 1,
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
        args=(task_id, stop_event, worker_token),
        daemon=True,
        name=f"task-heartbeat-{task_id}",
    )
    heartbeat.start()

    try:
        last_exc = None
        for attempt in range(MAX_RETRIES):
            try:
                result = fn() or {}
                final_status = "completed"
                if record.task_type == OPEN_RAG_EVALUATION_TASK_TYPE and result.get("verified") is False:
                    final_status = "partial"
                finalized = _owned_task_records(task_id, worker_token).update(
                    status=final_status,
                    progress=1 if final_status == "completed" else float(result.get("progress") or 1),
                    payload=original_payload,
                    result=result,
                    error_message="",
                    claimed_by="",
                    lease_expires_at=None,
                    updated_at=timezone.now(),
                )
                if finalized:
                    cache.set(
                        f"task:{task_id}",
                        {"status": final_status, "progress": 1, "result": result},
                        timeout=86400,
                    )
                    return
                if TaskRecord.objects.filter(id=task_id, cancel_requested_at__isnull=False).exists():
                    TaskRecord.objects.filter(id=task_id, status="running").update(
                        status="cancelled", claimed_by="", lease_expires_at=None, updated_at=timezone.now()
                    )
                    return
            except Exception as exc:
                last_exc = exc
                current_status = TaskRecord.objects.filter(id=task_id).values_list("status", flat=True).first()
                if current_status == "cancelled" or (
                    record.task_type == OPEN_RAG_EVALUATION_TASK_TYPE
                    and exc.__class__.__name__ == "OpenRagEvaluationCancelled"
                ):
                    TaskRecord.objects.filter(id=task_id).update(
                        status="cancelled", claimed_by="", lease_expires_at=None, updated_at=timezone.now()
                    )
                    cache.set(
                        f"task:{task_id}",
                        {"status": "cancelled", "progress": record.progress, "error": str(exc)},
                        timeout=7 * 24 * 60 * 60,
                    )
                    return
                if "database is locked" in str(exc) and attempt < MAX_RETRIES - 1:
                    logger.warning("task %s hit database lock, retrying (%d/%d)...", task_id, attempt + 1, MAX_RETRIES)
                    close_old_connections()
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                break

        # 所有重试都失败
        logger.error("task %s failed: %s", task_id, last_exc)
        latest_result = TaskRecord.objects.filter(id=task_id).values_list("result", flat=True).first()
        partial_result = latest_result if isinstance(latest_result, dict) else {}
        partial_status = "partial" if record.task_type == OPEN_RAG_EVALUATION_TASK_TYPE and partial_result.get("partial_metrics") else "failed"
        finalized = _owned_task_records(task_id, worker_token).update(
            status=partial_status,
            payload=original_payload,
            error_message=str(last_exc),
            claimed_by="",
            lease_expires_at=None,
            updated_at=timezone.now(),
        )
        if finalized:
            cache.set(
                f"task:{task_id}",
                        {"status": partial_status, "progress": record.progress, "error_message": str(last_exc)},
                timeout=86400,
            )
    finally:
        stop_event.set()
        heartbeat.join()
        close_old_connections()


def _run_resolved_task(task_id: str):
    record = TaskRecord.objects.get(id=task_id)
    fn = resolve_task_callable(record)
    if fn is None:
        raise RuntimeError(f"task payload is not recoverable: {record.task_type}")
    return fn()


def _payload_without_worker_token(payload) -> dict:
    cleaned = dict(payload) if isinstance(payload, dict) else {}
    cleaned.pop(WORKER_TOKEN_KEY, None)
    return cleaned


def _owned_task_records(task_id: str, worker_token: str):
    return TaskRecord.objects.filter(
        models.Q(claimed_by=worker_token)
        | models.Q(claimed_by="", **{f"payload__{WORKER_TOKEN_KEY}": worker_token}),
        id=task_id,
        status="running",
        cancel_requested_at__isnull=True,
    )


def _heartbeat_task(task_id: str, stop_event, worker_token: str):
    while not stop_event.wait(HEARTBEAT_INTERVAL):
        close_old_connections()
        try:
            refreshed = _owned_task_records(task_id, worker_token).update(
                updated_at=timezone.now(),
                lease_expires_at=timezone.now() + timedelta(seconds=STALE_LEASE_SECONDS),
            )
            if not refreshed:
                return
        except (OperationalError, ProgrammingError) as exc:
            logger.warning("Task %s heartbeat failed; retrying: %s", task_id, exc)
        finally:
            close_old_connections()


def resolve_task_callable(record: TaskRecord):
    if record.task_type == "prepare_open_rag_dataset":
        from .eval_dataset_registry import get_dataset_spec
        from .open_rag_benchmark import prepare_open_rag_dataset

        payload = record.payload if isinstance(record.payload, dict) else {}
        dataset_id = str(payload.get("dataset_id") or "")
        version = str(payload.get("dataset_version") or "")
        if not dataset_id or not version:
            return None
        return lambda: prepare_open_rag_dataset(get_dataset_spec(dataset_id, version))
    if record.task_type == OPEN_RAG_EVALUATION_TASK_TYPE:
        payload = record.payload if isinstance(record.payload, dict) else {}
        if not payload.get("tenant_id") or not payload.get("dataset_id") or not payload.get("dataset_version"):
            return None
        return lambda task_id=record.id: run_evaluation_task(task_id)
    if record.task_type == "rebuild_vector_index":
        from .search import rebuild_vector_index

        return lambda: rebuild_vector_index(task_id=record.id)
    if record.task_type != "process_knowledge":
        return None
    payload = record.payload if isinstance(record.payload, dict) else {}
    knowledge_id = str(payload.get("knowledge_id") or "")
    if not knowledge_id:
        return None
    from .document_processing import process_knowledge

    return lambda: (process_knowledge(knowledge_id), {"knowledge_id": knowledge_id})[1]


class OpenRagEvaluationCancelled(RuntimeError):
    """Raised by cooperative checkpoints after a caller cancels a run."""


def run_evaluation_task(task_id: str) -> dict:
    record = TaskRecord.objects.get(id=task_id)
    payload = record.payload if isinstance(record.payload, dict) else {}
    if (payload.get("source") or {}).get("type") == "tenant_dataset":
        return run_tenant_evaluation_task(task_id)
    return run_open_rag_evaluation_task(task_id)


def _runtime_configuration_degradations(tenant, payload: dict) -> list[str]:
    """Detect model changes made after preflight; those runs cannot verify."""
    expected = payload.get("effective_pipeline") if isinstance(payload.get("effective_pipeline"), dict) else {}
    if not expected:
        return []
    from .model_providers import active_embedding_config, active_rerank_config, default_model

    reasons = []
    embedding = active_embedding_config(tenant)
    expected_embedding = str(expected.get("embedding_model") or "")
    if expected_embedding and str((embedding or {}).get("model") or "") != expected_embedding:
        reasons.append("embedding_model_changed_after_preflight")
    rerank = expected.get("rerank") if isinstance(expected.get("rerank"), dict) else {}
    if rerank.get("requested") and str(rerank.get("model") or "") != str((active_rerank_config(tenant) or {}).get("model") or ""):
        reasons.append("rerank_model_changed_after_preflight")
    for key in ("answer_model", "judge_model"):
        expected_model = str(expected.get(key) or "")
        if not expected_model:
            continue
        explicit_id = str(payload.get(f"{key}_id") or "")
        if explicit_id and explicit_id.startswith("env-"):
            current_name = str(getattr(settings, "LLM_CHAT_MODEL", ""))
            if current_name and current_name != expected_model:
                reasons.append(f"{key}_changed_after_preflight")
        elif explicit_id:
            from .models import ModelConfig

            current = ModelConfig.objects.filter(id=explicit_id, tenant=tenant, status="active", deleted_at__isnull=True).first()
            current_name = str(((current.parameters or {}).get("model") if current else "") or (current.name if current else ""))
            if current is None or current_name != expected_model:
                reasons.append(f"{key}_changed_after_preflight")
        else:
            current = default_model(tenant, "chat")
            current_name = str(((current.parameters or {}).get("model") if current else "") or (current.name if current else ""))
            if current_name and current_name != expected_model:
                reasons.append(f"{key}_changed_after_preflight")
    return reasons


def _open_rag_checkpoint_path(tenant_id: str, task_id: str):
    from pathlib import Path

    return Path(settings.BASE_DIR) / ".cache" / "open-rag-runs" / str(tenant_id) / f"{task_id}.json"


def _safe_open_rag_result(value):
    """Persist only aggregate metrics; checkpoints must not retain corpus text."""
    if not isinstance(value, dict):
        return value
    return {
        key: _safe_open_rag_result(item)
        for key, item in value.items()
        if key not in {"details", "per_question", "contexts", "content", "answer", "ground_truth", "query", "question", "source"}
    }


_RETRIEVAL_REFERENCE_FIELDS = {
    "id", "chunk_id", "doc_id", "section_id", "knowledge_id", "knowledge_base_id",
    "score", "rerank_score", "keyword_rank", "vector_rank", "rrf_score", "match_sources",
}


def _checkpoint_retrieved_results(retrieved) -> dict:
    sanitized = {}
    for query_id, raw in (retrieved or {}).items():
        if isinstance(raw, (list, tuple)) and len(raw) == 2:
            rows, meta = raw
            sanitized[str(query_id)] = [
                [
                    {key: item[key] for key in _RETRIEVAL_REFERENCE_FIELDS if key in item}
                    for item in (rows or [])
                    if isinstance(item, dict)
                ],
                _safe_open_rag_result(meta),
            ]
        elif isinstance(raw, dict):
            rows = raw.get("results") or []
            sanitized[str(query_id)] = {
                **{key: value for key, value in raw.items() if key != "results"},
                "results": [
                    {key: item[key] for key in _RETRIEVAL_REFERENCE_FIELDS if key in item}
                    for item in rows
                    if isinstance(item, dict)
                ],
            }
    return sanitized


def _checkpoint_answers(answers) -> dict:
    return {
        str(entry_id): {
            key: value
            for key, value in item.items()
            if key in {"answer", "valid", "error", "query_id"}
        }
        for entry_id, item in (answers or {}).items()
        if isinstance(item, dict)
    }


def _resume_incomplete_answer_stages(completed, answers, scores):
    """Re-open answer and judge stages when a checkpoint contains failed answers."""
    rows = answers.values() if isinstance(answers, dict) else answers or []
    if any(
        isinstance(row, dict)
        and (
            not row.get("valid", True)
            or ("answer" in row and not str(row.get("answer") or "").strip())
        )
        for row in rows
    ):
        return [stage for stage in completed if stage not in {"answer_generation", "ragas"}], []
    if "ragas" in completed:
        from .ragas_adapter import is_usable_ragas_score

        score_rows = [score for score in (scores or []) if isinstance(score, dict) and score]
        if not score_rows or any(not is_usable_ragas_score(score) for score in score_rows):
            return [stage for stage in completed if stage != "ragas"], scores or []
    return list(completed), scores


def _resume_degraded_open_stages(completed, partial_metrics):
    completed = list(completed)
    partial_metrics = partial_metrics if isinstance(partial_metrics, dict) else {}
    if "retrieval" in completed and (partial_metrics.get("retrieval") or {}).get("verified") is False:
        return []
    if "chunking" in completed and (partial_metrics.get("chunking") or {}).get("verified") is False:
        completed.remove("chunking")
    return completed


def _ragas_checkpoint_counts(scores) -> tuple[int, int]:
    from .ragas_adapter import is_usable_ragas_score

    processed_scores = [score for score in (scores or []) if isinstance(score, dict) and score]
    return len(processed_scores), sum(not is_usable_ragas_score(score) for score in processed_scores)


def _ragas_metric_summary(scores, expected_total: int) -> dict:
    from .ragas_adapter import METRIC_NAMES, is_usable_ragas_score

    valid_scores = [score for score in (scores or []) if is_usable_ragas_score(score)]
    count = len(valid_scores)
    expected_total = max(0, int(expected_total))
    summary = {
        metric: (sum(score[metric] for score in valid_scores) / count if count else None)
        for metric in METRIC_NAMES
    }
    ragas_verified = bool(valid_scores) and count == expected_total
    summary.update({
        "verified": ragas_verified,
        "verification_status": "verified" if ragas_verified else ("degraded" if valid_scores else "unverified"),
        "dataset_status": "verified" if ragas_verified else "unverified",
        "total_questions": expected_total,
        "failed_questions": max(0, expected_total - count),
        "valid_coverage": count / max(expected_total, 1),
    })
    return summary


def _read_open_rag_checkpoint(tenant_id: str, task_id: str) -> dict:
    import json

    path = _open_rag_checkpoint_path(tenant_id, task_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_open_rag_checkpoint(tenant_id: str, task_id: str, payload: dict) -> None:
    import json
    import os

    path = _open_rag_checkpoint_path(tenant_id, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.part")
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(serialized)
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)


def _cleanup_open_rag_checkpoints() -> None:
    from pathlib import Path

    root = Path(settings.BASE_DIR) / ".cache" / "open-rag-runs"
    if not root.exists():
        return
    expired_before = time.time() - 7 * 24 * 60 * 60
    for path in root.glob("*/*.json"):
        try:
            if path.stat().st_mtime < expired_before:
                path.unlink()
        except OSError:
            logger.debug("Unable to remove expired Open RAG checkpoint %s", path, exc_info=True)


def _open_rag_cancelled(task_id: str, worker_token: str = "") -> bool:
    record = TaskRecord.objects.filter(id=task_id).values(
        "status", "cancel_requested_at", "claimed_by"
    ).first()
    return (
        not record
        or record["status"] != "running"
        or record["cancel_requested_at"] is not None
        or bool(worker_token and record["claimed_by"] != worker_token)
    )


def _update_open_rag_runtime(
    task_id: str,
    *,
    stage: str,
    progress: float,
    stage_progress: float,
    completed_stages: list[str],
    partial_metrics: dict,
    completed_questions: int | None = None,
    total_questions: int | None = None,
    failed_questions: int | None = None,
    valid_coverage: float | None = None,
) -> bool:
    record = TaskRecord.objects.filter(id=task_id, status="running").first()
    if record is None:
        return False
    payload = dict(record.payload or {})
    payload.update({
        "stage": stage,
        "stage_progress": max(0.0, min(float(stage_progress), 1.0)),
        "completed_stages": list(completed_stages),
    })
    previous_runtime = record.result if isinstance(record.result, dict) else {}
    runtime = {
        "stage": stage,
        "progress": max(0.0, min(float(progress), 1.0)),
        "stage_progress": max(0.0, min(float(stage_progress), 1.0)),
        "completed_stages": list(completed_stages),
        "partial_metrics": _safe_open_rag_result(partial_metrics),
        "completed_questions": max(0, int(completed_questions if completed_questions is not None else previous_runtime.get("completed_questions") or 0)),
        "total_questions": max(0, int(total_questions if total_questions is not None else payload.get("sample_size") or 0)),
        "failed_questions": max(0, int(failed_questions if failed_questions is not None else previous_runtime.get("failed_questions") or 0)),
        "valid_coverage": valid_coverage if valid_coverage is not None else previous_runtime.get("valid_coverage"),
    }
    updated = TaskRecord.objects.filter(id=task_id, status="running").update(
        payload=payload,
        result=runtime,
        progress=runtime["progress"],
        updated_at=timezone.now(),
    )
    if updated:
        cache.set(f"task:{task_id}", {"status": "running", **runtime}, timeout=86400)
    return bool(updated)


def run_open_rag_evaluation_task(task_id: str) -> dict:
    """Execute one tenant-isolated public evaluation with resumable stages.

    The benchmark helpers remain read-only.  This orchestrator only stores
    aggregate, sanitized stage output in ``TaskRecord`` and a seven-day
    filesystem checkpoint for restart recovery.
    """
    from .eval_dataset_registry import get_dataset_spec
    from .eval_reports import save_open_evaluation_report
    from .models import Tenant
    from .open_rag_benchmark import (
        MAX_SAMPLE_SIZE,
        OpenRagDatasetError,
        open_dataset_status,
        run_open_rag_chunking,
        run_open_rag_evaluation,
        generate_open_rag_answers,
        run_open_rag_retrieval,
        run_open_rag_strategy_retrieval,
        retrieve_open_rag_questions,
        sample_open_rag_questions,
    )

    _cleanup_open_rag_checkpoints()
    record = TaskRecord.objects.get(id=task_id)
    payload = dict(record.payload or {})
    tenant_id = str(payload.get("tenant_id") or "")
    tenant = Tenant.objects.filter(id=tenant_id).first()
    if tenant is None:
        raise RuntimeError("Open RAG task tenant is not recoverable")
    sample_size = int(payload.get("sample_size") or 180)
    if sample_size < 1 or sample_size > MAX_SAMPLE_SIZE:
        raise RuntimeError("Open RAG task sample_size is invalid")
    primary_strategy = str(payload.get("primary_chunking_strategy") or "")
    comparison_strategies = [str(value) for value in (payload.get("comparison_chunking_strategies") or [])]
    isolated_pipeline = bool(primary_strategy)
    selected_strategies = [primary_strategy, *comparison_strategies] if isolated_pipeline else list(payload.get("chunking_strategies") or [])
    if not selected_strategies:
        selected_strategies = ["auto_parent_child"]
    spec = get_dataset_spec(str(payload.get("dataset_id")), str(payload.get("dataset_version")))
    if not open_dataset_status(spec).get("ready"):
        raise OpenRagDatasetError("Open RAG dataset is not ready")
    runtime_configuration_degradations = _runtime_configuration_degradations(tenant, payload)

    checkpoint = _read_open_rag_checkpoint(tenant_id, task_id)
    if checkpoint.get("configuration_fingerprint") != payload.get("configuration_fingerprint"):
        checkpoint = {}
    completed = list(checkpoint.get("completed_stages") or [])
    partial = dict(checkpoint.get("partial_metrics") or {})
    retrieved_results = checkpoint.get("retrieved_results")
    strategy_retrievals = checkpoint.get("strategy_retrievals") if isinstance(checkpoint.get("strategy_retrievals"), dict) else {}
    answer_result = checkpoint.get("answer_result")
    ragas_scores = checkpoint.get("ragas_scores")
    if isolated_pipeline and retrieved_results:
        # Sanitized checkpoints intentionally omit source content.  An
        # isolated strategy cannot be rehydrated from the global section
        # table, so rerun its retrieval stage rather than scoring empty
        # contexts after a worker restart.
        missing_context = any(
            isinstance(raw, (list, tuple)) and len(raw) == 2
            and any(isinstance(item, dict) and "content" not in item for item in (raw[0] or []))
            for raw in retrieved_results.values()
        )
        if missing_context:
            completed = [stage for stage in completed if stage != "retrieval"]
            retrieved_results = None
            strategy_retrievals.pop(primary_strategy, None)
    original_completed = set(completed)
    completed = _resume_degraded_open_stages(completed, partial)
    if "retrieval" in original_completed and "retrieval" not in completed:
        retrieved_results = None
        answer_result = None
        ragas_scores = None
        partial = {}
    elif "chunking" in original_completed and "chunking" not in completed:
        partial.pop("chunking", None)
    completed, ragas_scores = _resume_incomplete_answer_stages(
        completed,
        (answer_result or {}).get("details", []),
        ragas_scores,
    )
    if "answer_generation" not in completed:
        partial.pop("answer_generation", None)
    if "ragas" not in completed:
        partial.pop("rag", None)
        partial.pop("ragas", None)
    stages = (
        ("retrieval", 0.10, 0.35),
        ("chunking", 0.35, 0.60),
        ("answer_generation", 0.60, 0.78),
        ("ragas", 0.78, 0.95),
    )

    worker_token = str(payload.get(WORKER_TOKEN_KEY) or record.claimed_by or "")

    def check_cancelled():
        if _open_rag_cancelled(task_id, worker_token):
            raise OpenRagEvaluationCancelled("Open RAG evaluation cancelled")

    def write_checkpoint(**intermediate):
        checkpoint_payload = {
            "configuration_fingerprint": payload.get("configuration_fingerprint", ""),
            "tenant_id": tenant_id,
            "completed_stages": completed,
            "partial_metrics": partial,
            "retrieved_results": _checkpoint_retrieved_results(retrieved_results),
            "strategy_retrievals": {
                str(strategy): {
                    "retrieved_results": _checkpoint_retrieved_results((value or {}).get("retrieved_results") if isinstance(value, dict) else value),
                    "chunk_count": int((value or {}).get("chunk_count") or 0) if isinstance(value, dict) else 0,
                    "documents": int((value or {}).get("documents") or 0) if isinstance(value, dict) else 0,
                    "reasons": list((value or {}).get("reasons") or []) if isinstance(value, dict) else [],
                }
                for strategy, value in strategy_retrievals.items()
            },
            "answer_result": {
                **{key: value for key, value in (answer_result or {}).items() if key not in {"details", "retrieved_results"}},
                "details": list(_checkpoint_answers({
                    str(item.get("query_id")): item
                    for item in (answer_result or {}).get("details", [])
                    if isinstance(item, dict) and item.get("query_id")
                }).values()),
            } if answer_result else None,
            "ragas_scores": ragas_scores,
            **intermediate,
        }
        _write_open_rag_checkpoint(tenant_id, task_id, checkpoint_payload)

    def checkpoint_stage(stage: str, result: dict, progress: float):
        if stage not in completed:
            completed.append(stage)
        partial["rag" if stage == "ragas" else stage] = _safe_open_rag_result(result)
        write_checkpoint()
        _update_open_rag_runtime(
            task_id,
            stage=stage,
            progress=progress,
            stage_progress=1,
            completed_stages=completed,
            partial_metrics=partial,
            completed_questions=sample_size,
            total_questions=sample_size,
            failed_questions=int(result.get("failed_questions") or 0),
            valid_coverage=result.get("valid_coverage"),
        )

    for stage, start, end in stages:
        check_cancelled()
        if stage in completed:
            continue
        if stage == "retrieval":
            resumed_questions = len(retrieved_results or {})
            resumed_failed = 0
        elif stage == "answer_generation":
            resumed_details = list((answer_result or {}).get("details") or [])
            resumed_failed = sum(not item.get("valid", True) for item in resumed_details)
            resumed_questions = len(resumed_details) - resumed_failed
        elif stage == "ragas":
            judged_questions, judge_failures = _ragas_checkpoint_counts(ragas_scores)
            answer_failures = int((answer_result or {}).get("failed_questions") or 0)
            resumed_questions = min(sample_size, answer_failures + judged_questions)
            resumed_failed = answer_failures + judge_failures
        else:
            resumed_questions = 0
            resumed_failed = 0
        resumed_ratio = resumed_questions / max(sample_size, 1)
        if not _update_open_rag_runtime(
            task_id,
            stage=stage,
            progress=start + (end - start) * resumed_ratio,
            stage_progress=resumed_ratio,
            completed_stages=completed,
            partial_metrics=partial,
            completed_questions=resumed_questions,
            total_questions=sample_size,
            failed_questions=resumed_failed,
            valid_coverage=max(0, resumed_questions - resumed_failed) / max(sample_size, 1),
        ):
            check_cancelled()
        if stage == "retrieval":
            sampled_rows = sample_open_rag_questions(spec, sample_size, int(payload.get("seed") or 0))
            def retrieval_progress(done, total, current=None, *_args):
                nonlocal retrieved_results, strategy_retrievals
                retrieved_results = current if isinstance(current, dict) else retrieved_results
                if isolated_pipeline:
                    strategy_retrievals[primary_strategy] = {
                        "retrieved_results": retrieved_results,
                        "chunk_count": (strategy_retrievals.get(primary_strategy) or {}).get("chunk_count", 0),
                        "documents": (strategy_retrievals.get(primary_strategy) or {}).get("documents", 0),
                        "reasons": (strategy_retrievals.get(primary_strategy) or {}).get("reasons", []),
                    }
                write_checkpoint()
                _update_open_rag_runtime(
                    task_id, stage=stage, progress=start + (end - start) * done / max(total, 1),
                    stage_progress=done / max(total, 1), completed_stages=completed, partial_metrics=partial,
                    completed_questions=len(retrieved_results or {}), total_questions=total,
                    failed_questions=0, valid_coverage=len(retrieved_results or {}) / max(total, 1),
                )
            if isolated_pipeline:
                primary_payload = strategy_retrievals.get(primary_strategy)
                if not isinstance(primary_payload, dict) or not isinstance(primary_payload.get("retrieved_results"), dict):
                    primary_payload = run_open_rag_strategy_retrieval(
                        tenant,
                        spec,
                        primary_strategy,
                        sample_size,
                        int(payload.get("seed") or 0),
                        retrieval_strategy=payload.get("retrieval_strategy", "hybrid"),
                        rerank_enabled=bool(payload.get("rerank_enabled", True)),
                        cancel_callback=check_cancelled,
                        progress_callback=retrieval_progress,
                    )
                strategy_retrievals[primary_strategy] = primary_payload
                retrieved_results = primary_payload.get("retrieved_results") or {}
                result = run_open_rag_retrieval(
                    tenant, spec, sample_size, int(payload.get("seed") or 0),
                    payload.get("retrieval_strategy", "hybrid"), retrieved_results,
                    rerank_enabled=bool(payload.get("rerank_enabled", True)),
                )
                result["effective_pipeline"] = {
                    "chunking_strategy": primary_strategy,
                    "retrieval_strategy": payload.get("retrieval_strategy", "hybrid"),
                    "rerank_enabled": bool(payload.get("rerank_enabled", True)),
                    "index_scope": "full_corpus",
                    "index_algorithm_version": payload.get("index_algorithm_version", "evaluation-index-v2"),
                }
            else:
                def legacy_retrieval_progress(done, total, current):
                    return retrieval_progress(done, total, current)
                retrieved_results = retrieve_open_rag_questions(
                    tenant,
                    spec,
                    sampled_rows,
                    retrieval_strategy=payload.get("retrieval_strategy", "hybrid"),
                    top_k=20,
                    rerank_enabled=bool(payload.get("rerank_enabled", True)),
                    cancel_callback=check_cancelled,
                    progress_callback=legacy_retrieval_progress,
                    existing_results=retrieved_results,
                )
                result = run_open_rag_retrieval(
                    tenant, spec, sample_size, int(payload.get("seed") or 0),
                    payload.get("retrieval_strategy", "hybrid"), retrieved_results,
                    rerank_enabled=bool(payload.get("rerank_enabled", True)),
                )
        elif stage == "chunking":
            def chunking_progress(done, total, strategy_done=1, strategy_total=1):
                strategy_ratio = ((strategy_done - 1) + done / max(total, 1)) / max(strategy_total, 1)
                _update_open_rag_runtime(
                    task_id,
                    stage=stage,
                    progress=start + (end - start) * strategy_ratio,
                    stage_progress=strategy_ratio,
                    completed_stages=completed,
                    partial_metrics=partial,
                    completed_questions=min(total, int(strategy_ratio * total)),
                    total_questions=total,
                    failed_questions=0,
                    valid_coverage=strategy_ratio,
                )

            result = run_open_rag_chunking(
                tenant,
                spec,
                sample_size,
                int(payload.get("seed") or 0),
                selected_strategies,
                retrieved_results=None if isolated_pipeline else retrieved_results,
                cancel_callback=check_cancelled,
                progress_callback=chunking_progress,
                isolated_full_corpus=isolated_pipeline,
                primary_strategy=primary_strategy or None,
                strategy_retrievals=strategy_retrievals if isolated_pipeline else None,
                retrieval_strategy=payload.get("retrieval_strategy", "hybrid"),
                rerank_enabled=bool(payload.get("rerank_enabled", True)),
            )
        elif stage == "answer_generation":
            def answer_progress(done, total, details):
                nonlocal answer_result
                answer_result = {
                    "details": details,
                    "total_questions": total,
                    "failed_questions": sum(not item.get("valid", True) for item in details),
                }
                write_checkpoint()
                _update_open_rag_runtime(
                    task_id, stage=stage, progress=start + (end - start) * done / total,
                    stage_progress=done / total, completed_stages=completed, partial_metrics=partial,
                    completed_questions=done, total_questions=total,
                    failed_questions=answer_result["failed_questions"],
                    valid_coverage=(done - answer_result["failed_questions"]) / max(total, 1),
                )
            answer_result = generate_open_rag_answers(
                tenant=tenant,
                spec=spec,
                sample_size=sample_size,
                seed=int(payload.get("seed") or 0),
                answer_model_id=str(payload.get("answer_model_id") or payload.get("eval_llm_model") or ""),
                retrieval_strategy=payload.get("retrieval_strategy", "hybrid"),
                rerank_enabled=bool(payload.get("rerank_enabled", True)),
                retrieved_results=retrieved_results,
                cancel_callback=check_cancelled,
                progress_callback=answer_progress,
                existing_details=(answer_result or {}).get("details", []),
            )
            result = {key: value for key, value in answer_result.items() if key != "retrieved_results"}
        else:
            def ragas_progress(done, total, scores):
                nonlocal ragas_scores
                ragas_scores = scores
                _processed, failed = _ragas_checkpoint_counts(scores)
                answer_failures = int((answer_result or {}).get("failed_questions") or 0)
                completed_count = min(sample_size, answer_failures + done)
                failed += answer_failures
                write_checkpoint()
                _update_open_rag_runtime(
                    task_id, stage=stage, progress=start + (end - start) * completed_count / max(sample_size, 1),
                    stage_progress=completed_count / max(sample_size, 1), completed_stages=completed, partial_metrics=partial,
                    completed_questions=completed_count, total_questions=sample_size,
                    failed_questions=failed,
                    valid_coverage=max(0, completed_count - failed) / max(sample_size, 1),
                )
            result = run_open_rag_evaluation(
                tenant=tenant,
                spec=spec,
                sample_size=sample_size,
                seed=int(payload.get("seed") or 0),
                judge_model_id=str(payload.get("judge_model_id") or payload.get("eval_llm_model") or ""),
                retrieval_strategy=payload.get("retrieval_strategy", "hybrid"),
                retrieved_results=retrieved_results,
                answer_result=answer_result,
                progress_callback=ragas_progress,
                cancel_callback=check_cancelled,
                existing_scores=ragas_scores,
            )
        check_cancelled()
        checkpoint_stage(stage, result, end)

    stage_verified = all(bool((partial.get("rag" if stage == "ragas" else stage) or {}).get("verified")) for stage, _start, _end in stages) and not runtime_configuration_degradations
    primary_chunking = partial.get("chunking", {}) if isinstance(partial.get("chunking"), dict) else {}
    primary_metrics = primary_chunking.get("primary") or {}
    comparisons = primary_chunking.get("comparisons") or {}
    primary_retrieval = partial.get("retrieval", {})
    primary_rag = partial.get("rag", partial.get("ragas", {}))
    usable = bool(primary_retrieval or primary_rag)
    verified = bool(stage_verified and usable)
    verification_status = "verified" if verified else ("degraded" if usable else "failed")
    effective_pipeline = dict(payload.get("effective_pipeline") or {})
    runtime_degradations = sorted(set(runtime_configuration_degradations) | {
        str(reason.get("message") if isinstance(reason, dict) else reason)
        for item in (primary_retrieval, primary_metrics, primary_rag)
        if isinstance(item, dict)
        for reason in (item.get("reasons") or item.get("degradations") or [])
    })
    effective_pipeline.update({
        "primary_chunking_strategy": primary_strategy or effective_pipeline.get("primary_chunking_strategy"),
        "comparison_chunking_strategies": comparison_strategies,
        "index_scope": "full_corpus" if isolated_pipeline else effective_pipeline.get("index_scope", "shared_dataset_index"),
        "index_algorithm_version": payload.get("index_algorithm_version", "evaluation-index-v2"),
        "degradations": runtime_degradations,
    })
    if any("rerank" in reason.lower() for reason in runtime_degradations):
        effective_pipeline["rerank"] = {
            **(effective_pipeline.get("rerank") or {}),
            "requested": bool(payload.get("rerank_enabled", True)),
            "effective": False,
            "status": "degraded",
        }
    report_result = {
        "verified": verified,
        "verification_status": verification_status,
        "sample_size": sample_size,
        "primary": {"retrieval": primary_retrieval, "rag": primary_rag, "chunking": primary_metrics},
        "comparisons": comparisons,
        "retrieval": primary_retrieval,
        "chunking": primary_chunking,
        "answer_generation": partial.get("answer_generation", {}),
        "rag": primary_rag,
    }
    requested_configuration = payload.get("requested_configuration") or {
        "source": {"type": "open_dataset", "dataset_id": spec.dataset_id, "dataset_version": spec.version},
        "primary_chunking_strategy": primary_strategy or (payload.get("chunking_strategies") or ["auto_parent_child"])[0],
        "comparison_chunking_strategies": comparison_strategies,
        "retrieval_strategy": payload.get("retrieval_strategy", "hybrid"),
        "rerank_enabled": bool(payload.get("rerank_enabled", True)),
        "answer_model_id": payload.get("answer_model_id", payload.get("eval_llm_model", "")),
        "judge_model_id": payload.get("judge_model_id", payload.get("eval_llm_model", "")),
    }
    metadata = save_open_evaluation_report(
        tenant=tenant,
        task_run_id=task_id,
        evaluation_type="open_rag_evaluation",
        evaluator="ragas",
        verified=verified,
        verification_status=verification_status,
        dataset={"id": spec.dataset_id, "version": spec.version, "entries": sample_size, "sha256": spec.sha256, "documents": spec.expected_documents},
        result=report_result,
        requested_configuration=requested_configuration,
        effective_pipeline=effective_pipeline,
        configuration=requested_configuration,
    )
    try:
        from .observability import report_evaluation_run

        report_evaluation_run(
            name="eval.open_rag",
            task_run_id=task_id,
            metrics={
                "verification_status": verification_status,
                "dataset": {"id": spec.dataset_id, "version": spec.version, "entries": sample_size},
                "primary": {"retrieval": primary_retrieval, "rag": primary_rag, "chunking": primary_chunking},
                "comparisons": comparisons,
            },
            metadata={"tenant_id": tenant_id, "evaluation_type": "open_rag_evaluation"},
        )
    except Exception:
        logger.debug("langfuse eval report failed", exc_info=True)
    report_pointer = {
        "id": metadata.get("report_id"),
        "report_id": metadata.get("report_id"),
        "task_run_id": task_id,
        "url": metadata.get("report_url"),
        "available": True,
    }
    if verified:
        _open_rag_checkpoint_path(tenant_id, task_id).unlink(missing_ok=True)
    metric_results = [primary_retrieval, primary_rag, primary_metrics]
    failed_questions = max((int(item.get("failed_questions") or 0) for item in metric_results), default=0)
    coverages = [float(item["valid_coverage"]) for item in metric_results if item.get("valid_coverage") is not None]
    final_metrics = {
        "primary": {"retrieval": primary_retrieval, "rag": primary_rag},
        "comparisons": comparisons,
        # compatibility aliases
        "rag": primary_rag,
        "retrieval": primary_retrieval,
        "chunking": primary_chunking,
    }
    return {
        "stage": "completed",
        "completed_stages": completed,
        "partial_metrics": {"primary": final_metrics["primary"], "comparisons": comparisons, **partial},
        "metrics": final_metrics,
        "effective_pipeline": effective_pipeline,
        "verification_status": verification_status,
        "verified": verified,
        "sample_size": sample_size,
        "completed_questions": sample_size,
        "total_questions": sample_size,
        "failed_questions": failed_questions,
        "valid_coverage": min(coverages) if coverages else None,
        "eta_seconds": 0,
        "report_id": metadata.get("report_id"),
        "report_url": metadata.get("report_url"),
        "report": report_pointer,
    }


def _tenant_evaluation_search(tenant, kb_id: str, query: str, strategy: str, rerank_enabled: bool):
    """Run the selected production retriever once and return reusable contexts.

    评测与生产共用 hybrid_search_ex 同一管线：hybrid 即生产默认形态；
    keyword / vector 是显式关闭一路召回的消融（vector_top_k=0 / keyword_top_k=0）；
    rerank_enabled=False 对应 rerank_top_k=0（未配置重排模型时生产侧自动降级）。
    top_k=20 为指标窗口（Hit@10 / MRR@10 / Recall@20），管线内部候选量
    按生产倍数推导（召回 4×top_k、重排输入 2×top_k），与生产行为一致。
    """
    from .search import hybrid_search_ex

    normalized = str(strategy or "hybrid").lower()
    if normalized not in {"keyword", "vector", "hybrid"}:
        normalized = "hybrid"
    results, meta = hybrid_search_ex(
        tenant.id,
        [kb_id],
        query,
        20,
        keyword_top_k=0 if normalized == "vector" else None,
        vector_top_k=0 if normalized == "keyword" else None,
        rerank_top_k=None if rerank_enabled else 0,
    )
    return results, meta


def _tenant_retrieval_metrics(results: list[dict], evidence: list[dict]) -> tuple[float, float, float]:
    from .models import Chunk

    chunk_ids = [str(item.get("chunk_id") or "") for item in results]
    chunks = {
        chunk.id: chunk
        for chunk in Chunk.objects.filter(id__in=chunk_ids, deleted_at__isnull=True)
    }
    relevant_hits = []
    covered = set()
    for rank, chunk_id in enumerate(chunk_ids, start=1):
        chunk = chunks.get(chunk_id)
        if chunk is None:
            continue
        matched = {
            index for index, row in enumerate(evidence)
            if str(row.get("knowledge_id")) == str(chunk.knowledge_id)
            and chunk.start_at < int(row.get("source_end") or 0)
            and chunk.end_at > int(row.get("source_start") or 0)
        }
        if matched:
            relevant_hits.append(rank)
        if rank <= 20:
            covered.update(matched)
    hit = float(any(rank <= 10 for rank in relevant_hits))
    mrr = 1.0 / relevant_hits[0] if relevant_hits and relevant_hits[0] <= 10 else 0.0
    recall = len(covered) / len(evidence) if evidence else 0.0
    return hit, mrr, recall


def _validate_tenant_evaluation_documents(tenant_id: str, knowledge_base_id: str, entries: list[dict]) -> None:
    expected = {}
    for entry in entries:
        for document in entry.get("documents") or []:
            knowledge_id = str(document.get("knowledge_id") or "")
            file_hash = str(document.get("file_hash") or document.get("version") or "").strip().lower()
            if not knowledge_id or not file_hash:
                raise RuntimeError("evaluation dataset document version is missing")
            previous = expected.setdefault(knowledge_id, file_hash)
            if previous != file_hash:
                raise RuntimeError("evaluation dataset has conflicting document versions")
    documents = {
        str(item.id): str(item.file_hash or "").strip().lower()
        for item in Knowledge.objects.filter(
            id__in=expected,
            tenant_id=tenant_id,
            knowledge_base_id=knowledge_base_id,
            deleted_at__isnull=True,
        )
    }
    if set(documents) != set(expected) or any(documents[key] != value for key, value in expected.items()):
        raise RuntimeError("evaluation dataset document version drift")


def run_tenant_evaluation_task(task_id: str) -> dict:
    """Evaluate one published evaluation_v2 dataset without loading templates."""
    from concurrent.futures import ThreadPoolExecutor

    from .chunking_eval import retrieve_chunking_strategy, run_chunking_comparison
    from .eval_reports import save_evaluation_report
    from .model_providers import chat_completion
    from .models import GenericResource, Tenant
    from .ragas_adapter import evaluate_dataset

    record = TaskRecord.objects.get(id=task_id)
    payload = dict(record.payload or {})
    tenant_id = str(payload.get("tenant_id") or "")
    tenant = Tenant.objects.filter(id=tenant_id).first()
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    dataset = GenericResource.objects.filter(
        id=source.get("dataset_id"), tenant=tenant, resource_type__in=("rag_eval_datasets", "rag_eval_testsets"),
        status="published", deleted_at__isnull=True,
    ).first()
    if tenant is None or dataset is None or (dataset.data or {}).get("schema_version") != "evaluation_v2":
        raise RuntimeError("published evaluation_v2 dataset is unavailable")
    entries = list((dataset.data or {}).get("entries") or [])
    if not entries or str((dataset.data or {}).get("dataset_hash") or "") != str(payload.get("dataset_hash") or ""):
        raise RuntimeError("evaluation dataset version drift")
    kb_id = str(source.get("knowledge_base_id") or "")
    if str((dataset.data or {}).get("knowledge_base_id") or "") != kb_id:
        raise RuntimeError("evaluation dataset knowledge base drift")
    _validate_tenant_evaluation_documents(tenant_id, kb_id, entries)
    runtime_configuration_degradations = _runtime_configuration_degradations(tenant, payload)
    checkpoint = _read_open_rag_checkpoint(tenant_id, task_id)
    if checkpoint.get("configuration_fingerprint") != payload.get("configuration_fingerprint"):
        checkpoint = {}
    completed = list(checkpoint.get("completed_stages") or [])
    metrics = dict(checkpoint.get("metrics") or {})
    retrieved = dict(checkpoint.get("retrieved_results") or {})
    if payload.get("primary_chunking_strategy") and retrieved and any(
        isinstance(item, dict) and any(isinstance(row, dict) and not row.get("content") for row in (item.get("results") or []))
        for item in retrieved.values()
    ):
        completed = [stage for stage in completed if stage != "retrieval"]
        retrieved = {}
    answers = dict(checkpoint.get("answers") or {})
    judge_scores = checkpoint.get("judge_scores")
    completed, judge_scores = _resume_incomplete_answer_stages(completed, answers, judge_scores)

    def contexts_for_entry(entry_id: str) -> list[str]:
        from .models import Chunk
        from .open_rag_benchmark import _bounded_contexts

        rows = retrieved.get(entry_id, {}).get("results", [])
        inline_contexts = [row for row in rows[:5] if isinstance(row, dict) and row.get("content")]
        if inline_contexts:
            return _bounded_contexts(inline_contexts)
        chunk_ids = [str(row.get("chunk_id") or row.get("id") or "") for row in rows[:5]]
        chunks = {
            str(chunk.id): chunk.content
            for chunk in Chunk.objects.filter(
                id__in=chunk_ids,
                tenant=tenant,
                knowledge_base_id=kb_id,
                deleted_at__isnull=True,
            )
        }
        return _bounded_contexts([
            {"content": chunks[chunk_id]}
            for chunk_id in chunk_ids
            if chunk_id in chunks
        ])

    worker_token = str(payload.get(WORKER_TOKEN_KEY) or record.claimed_by or "")

    def check_cancelled():
        if _open_rag_cancelled(task_id, worker_token):
            raise OpenRagEvaluationCancelled("evaluation cancelled")

    tenant_chunk_dataset = [{
        "id": entry.get("id"),
        "query": entry.get("question", ""),
        "documents": entry.get("documents", []),
        "evidence": entry.get("evidence", []),
    } for entry in entries]
    primary_strategy = str(payload.get("primary_chunking_strategy") or "")
    isolated_retrieved = None
    if primary_strategy:
        try:
            isolated_retrieved = retrieve_chunking_strategy(
                tenant,
                tenant_chunk_dataset,
                primary_strategy,
                knowledge_base_id=kb_id,
                retrieval_strategy=str(payload.get("retrieval_strategy") or "hybrid"),
                rerank_enabled=bool(payload.get("rerank_enabled", True)),
                cancel_callback=check_cancelled,
            )
        except Exception as exc:
            logger.warning("Tenant isolated primary retrieval failed", exc_info=True)
            isolated_retrieved = {}

    def save_checkpoint(stage: str, done: int, total: int):
        _write_open_rag_checkpoint(tenant_id, task_id, {
            "configuration_fingerprint": payload.get("configuration_fingerprint", ""),
            "tenant_id": tenant_id,
            "completed_stages": completed,
            "metrics": metrics,
            "retrieved_results": _checkpoint_retrieved_results(retrieved),
            "answers": _checkpoint_answers(answers),
            "judge_scores": judge_scores,
        })
        stage_ranges = {"retrieval": (0.05, 0.35), "chunking": (0.35, 0.55), "answer_generation": (0.55, 0.78), "ragas": (0.78, 0.96)}
        start, end = stage_ranges[stage]
        if stage == "retrieval":
            failed = sum(not item.get("valid", False) for item in retrieved.values())
        elif stage == "answer_generation":
            failed = sum(not item.get("valid", False) for item in answers.values())
        elif stage == "ragas":
            processed, judge_failed = _ragas_checkpoint_counts(judge_scores)
            answer_failed = sum(not item.get("valid", False) for item in answers.values())
            done = min(total, answer_failed + processed)
            failed = answer_failed + judge_failed
        else:
            failed = 0
        ratio = done / max(total, 1)
        _update_open_rag_runtime(
            task_id, stage=stage, progress=start + (end - start) * ratio, stage_progress=ratio,
            completed_stages=completed, partial_metrics=metrics,
            completed_questions=done, total_questions=total,
            failed_questions=failed,
            valid_coverage=max(0, done - failed) / max(total, 1),
        )

    if "retrieval" not in completed:
        valid_rows = []
        failed = 0
        for index, entry in enumerate(entries, start=1):
            check_cancelled()
            entry_id = str(entry.get("id"))
            if entry_id not in retrieved:
                try:
                    if primary_strategy and isolated_retrieved is not None:
                        isolated_item = isolated_retrieved.get(entry_id) or isolated_retrieved.get(str(index - 1))
                        if isolated_item is None:
                            raise RuntimeError("isolated_retrieval_missing")
                        retrieved[entry_id] = isolated_item
                    else:
                        rows, meta = _tenant_evaluation_search(
                            tenant, kb_id, str(entry.get("question") or ""),
                            str(payload.get("retrieval_strategy") or "hybrid"), bool(payload.get("rerank_enabled", True)),
                        )
                        hit, mrr, recall = _tenant_retrieval_metrics(rows, list(entry.get("evidence") or []))
                        retrieved[entry_id] = {"results": rows, "meta": meta, "hit_at_10": hit, "mrr_at_10": mrr, "recall_at_20": recall, "valid": True}
                except Exception as exc:
                    logger.warning("Tenant evaluation retrieval failed for %s", entry_id, exc_info=True)
                    retrieved[entry_id] = {"results": [], "valid": False, "error": f"retrieval_failed:{type(exc).__name__}"}
            item = retrieved[entry_id]
            if item.get("valid"):
                valid_rows.append(item)
            else:
                failed += 1
            if index % 20 == 0 or index == len(entries):
                save_checkpoint("retrieval", index, len(entries))
        count = len(valid_rows) or 1
        retrieval_degradations = sorted({
            str(reason.get("reason") if isinstance(reason, dict) else reason)
            for item in valid_rows
            for reason in ((item.get("meta") or {}).get("degradations") or [])
        })
        retrieval_status = "verified" if valid_rows and not failed and not retrieval_degradations else ("degraded" if valid_rows else "unverified")
        metrics["retrieval"] = {
            "verified": retrieval_status == "verified", "verification_status": retrieval_status,
            "dataset_status": "verified" if retrieval_status == "verified" else "unverified",
            "degradations": retrieval_degradations,
            "hit_at_10_new": sum(item["hit_at_10"] for item in valid_rows) / count if valid_rows else None,
            "mrr_new": sum(item["mrr_at_10"] for item in valid_rows) / count if valid_rows else None,
            "recall_new": sum(item["recall_at_20"] for item in valid_rows) / count if valid_rows else None,
            "questions": len(entries), "failed_questions": failed, "valid_coverage": len(valid_rows) / len(entries),
            "dataset_hash": payload.get("dataset_hash"),
        }
        completed.append("retrieval")
        save_checkpoint("retrieval", len(entries), len(entries))

    if "chunking" not in completed:
        check_cancelled()
        chunk_dataset = tenant_chunk_dataset
        last_chunking_checkpoint = -1

        def tenant_chunking_progress(done, total, strategy_done=1, strategy_total=1):
            nonlocal last_chunking_checkpoint
            strategy_ratio = ((strategy_done - 1) + done / max(total, 1)) / max(strategy_total, 1)
            checkpoint_step = int(strategy_ratio * 20)
            if checkpoint_step != last_chunking_checkpoint or strategy_ratio >= 1:
                last_chunking_checkpoint = checkpoint_step
                save_checkpoint("chunking", int(strategy_ratio * len(entries)), len(entries))

        tenant_strategies = [
            str(payload.get("primary_chunking_strategy") or "auto_parent_child"),
            *[str(value) for value in (payload.get("comparison_chunking_strategies") or [])],
        ]
        metrics["chunking"] = run_chunking_comparison(
            tenant.id,
            dataset=chunk_dataset,
            strategies=tenant_strategies,
            tenant=tenant,
            knowledge_base_id=kb_id,
            retrieval_strategy=str(payload.get("retrieval_strategy") or "hybrid"),
            rerank_enabled=bool(payload.get("rerank_enabled", True)),
            cancel_callback=check_cancelled,
            progress_callback=tenant_chunking_progress,
        )
        metrics["chunking"]["primary_strategy"] = tenant_strategies[0]
        metrics["chunking"]["primary"] = (metrics["chunking"].get("strategies") or {}).get(tenant_strategies[0], {})
        metrics["chunking"]["comparisons"] = {
            strategy: value for strategy, value in (metrics["chunking"].get("strategies") or {}).items()
            if strategy != tenant_strategies[0]
        }
        metrics["chunking"]["dataset_hash"] = payload.get("dataset_hash")
        completed.append("chunking")
        save_checkpoint("chunking", 1, 1)

    if "answer_generation" not in completed:
        pending = [
            entry for entry in entries
            if str(entry.get("id")) not in answers
            or not answers[str(entry.get("id"))].get("valid", True)
        ]

        def generate(entry):
            check_cancelled()
            entry_id = str(entry.get("id"))
            contexts = contexts_for_entry(entry_id)
            messages = [
                {"role": "system", "content": "根据给定知识库上下文回答问题。"},
                {"role": "user", "content": f"上下文：\n{'\n\n'.join(contexts) or '没有找到相关信息'}\n\n问题：{entry.get('question', '')}"},
            ]
            try:
                answer = chat_completion(
                    tenant,
                    messages,
                    str(payload.get("answer_model_id") or ""),
                    max_tokens=512,
                    enable_thinking=False,
                )
                if not str(answer or "").strip():
                    raise ValueError("Empty model response")
            except Exception as exc:
                logger.warning("Tenant evaluation answer generation failed for %s", entry_id, exc_info=True)
                return entry_id, {"valid": False, "error": f"answer_generation_failed:{type(exc).__name__}"}
            return entry_id, {"valid": True, "question": entry.get("question", ""), "answer": answer, "contexts": contexts, "ground_truth": entry.get("reference_answer") or entry.get("ground_truth") or entry.get("answer", "")}

        completed_answers = sum(
            1 for entry in entries
            if answers.get(str(entry.get("id")), {}).get("valid", False)
        )
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="tenant-eval-answer") as executor:
            for index, result in enumerate(executor.map(generate, pending), start=completed_answers + 1):
                entry_id, answer = result
                answers[entry_id] = answer
                if index % 10 == 0 or index == len(entries):
                    save_checkpoint("answer_generation", index, len(entries))
        completed.append("answer_generation")
        save_checkpoint("answer_generation", len(entries), len(entries))

    if "ragas" not in completed:
        ordered_answers = []
        for entry in entries:
            entry_id = str(entry.get("id"))
            saved = answers.get(entry_id)
            if not saved or not saved.get("valid", True):
                continue
            ordered_answers.append({
                "question": entry.get("question", ""),
                "answer": saved.get("answer", ""),
                "contexts": contexts_for_entry(entry_id),
                "ground_truth": entry.get("reference_answer") or entry.get("ground_truth") or entry.get("answer", ""),
            })

        def judge_progress(done, total, scores):
            nonlocal judge_scores
            judge_scores = scores
            save_checkpoint("ragas", done, len(entries))

        judge_scores = evaluate_dataset(
            ordered_answers, tenant, str(payload.get("judge_model_id") or ""),
            progress_callback=judge_progress, cancel_callback=check_cancelled, existing_scores=judge_scores,
        )
        metrics["rag"] = {
            **_ragas_metric_summary(judge_scores, len(entries)),
            "dataset_hash": payload.get("dataset_hash"),
        }
        completed.append("ragas")
        save_checkpoint("ragas", len(entries), len(entries))

    chunking_result = metrics.get("chunking", {}) if isinstance(metrics.get("chunking"), dict) else {}
    primary_chunking = chunking_result.get("primary") or {}
    comparisons = chunking_result.get("comparisons") or {}
    primary_metrics = {
        "retrieval": metrics.get("retrieval", {}),
        "rag": metrics.get("rag", {}),
        "chunking": primary_chunking,
    }
    stage_verified = all(bool(metrics.get(key, {}).get("verified")) for key in ("rag", "retrieval", "chunking")) and not runtime_configuration_degradations
    usable = bool(metrics.get("retrieval") or metrics.get("rag"))
    verification_status = "verified" if stage_verified else ("degraded" if usable else "failed")
    verified = verification_status == "verified"
    requested_configuration = payload.get("requested_configuration") or {
        "source": source,
        "primary_chunking_strategy": payload.get("primary_chunking_strategy") or (payload.get("chunking_strategies") or ["auto_parent_child"])[0],
        "comparison_chunking_strategies": payload.get("comparison_chunking_strategies") or (payload.get("chunking_strategies") or [])[1:],
        "retrieval_strategy": payload.get("retrieval_strategy", "hybrid"),
        "rerank_enabled": bool(payload.get("rerank_enabled", True)),
        "answer_model_id": payload.get("answer_model_id", ""),
        "judge_model_id": payload.get("judge_model_id", ""),
    }
    effective_pipeline = dict(payload.get("effective_pipeline") or {})
    tenant_degradations = sorted(set(runtime_configuration_degradations) | {
        str(reason.get("message") if isinstance(reason, dict) else reason)
        for item in (metrics.get("retrieval", {}), metrics.get("chunking", {}), metrics.get("rag", {}))
        if isinstance(item, dict)
        for reason in (item.get("reasons") or item.get("degradations") or [])
    })
    effective_pipeline["degradations"] = tenant_degradations
    if any("rerank" in reason.lower() for reason in tenant_degradations):
        effective_pipeline["rerank"] = {
            **(effective_pipeline.get("rerank") or {}),
            "requested": bool(payload.get("rerank_enabled", True)),
            "effective": False,
            "status": "degraded",
        }
    metadata = save_evaluation_report(
        tenant=tenant,
        task_run_id=task_id,
        evaluation_type="unified_evaluation",
        evaluator="ragas",
        verified=verified,
        verification_status=verification_status,
        dataset={
            "id": dataset.id,
            "version": (dataset.data or {}).get("version"),
            "entries": len(entries),
            "sha256": payload.get("dataset_hash"),
            "documents": sorted({
                (str(document.get("knowledge_id") or ""), str(document.get("file_hash") or document.get("version") or ""))
                for entry in entries for document in (entry.get("documents") or [])
            }),
        },
        result={"metrics": {"primary": primary_metrics, "comparisons": comparisons, **metrics}, "verified": verified, "verification_status": verification_status},
        requested_configuration=requested_configuration,
        effective_pipeline=effective_pipeline,
        configuration=requested_configuration,
    )
    try:
        from .observability import report_evaluation_run

        report_evaluation_run(
            name="eval.tenant_rag",
            task_run_id=task_id,
            metrics={
                "verification_status": verification_status,
                "dataset": {"id": str(dataset.id), "entries": len(entries)},
                "primary": primary_metrics,
                "rag": metrics.get("rag", {}),
                "retrieval": metrics.get("retrieval", {}),
                "chunking": chunking_result,
            },
            dataset_name=f"tenant-eval:{dataset.id}",
            entries=entries,
            metadata={"tenant_id": tenant_id, "evaluation_type": "unified_evaluation"},
        )
    except Exception:
        logger.debug("langfuse eval report failed", exc_info=True)
    report_pointer = {
        "id": metadata.get("report_id"),
        "report_id": metadata.get("report_id"),
        "task_run_id": task_id,
        "url": metadata.get("report_url"),
        "available": True,
    }
    if verified:
        _open_rag_checkpoint_path(tenant_id, task_id).unlink(missing_ok=True)
    metric_results = [metrics.get("retrieval", {}), metrics.get("rag", {}), primary_chunking]
    failed_questions = max((int(item.get("failed_questions") or 0) for item in metric_results), default=0)
    coverages = [float(item["valid_coverage"]) for item in metric_results if item.get("valid_coverage") is not None]
    final_metrics = {"primary": primary_metrics, "comparisons": comparisons, "rag": metrics.get("rag", {}), "retrieval": metrics.get("retrieval", {}), "chunking": chunking_result}
    return {
        "stage": "completed", "completed_stages": completed,
        "partial_metrics": {"primary": primary_metrics, "comparisons": comparisons, **metrics},
        "metrics": final_metrics,
        "effective_pipeline": effective_pipeline,
        "verification_status": verification_status,
        "verified": verified, "sample_size": len(entries),
        "completed_questions": len(entries), "total_questions": len(entries),
        "failed_questions": failed_questions,
        "valid_coverage": min(coverages) if coverages else None,
        "eta_seconds": 0,
        "report_id": metadata.get("report_id"),
        "report_url": metadata.get("report_url"), "report": report_pointer,
    }


def _mark_recovery_failed(record: TaskRecord, message: str, now) -> bool:
    updated = TaskRecord.objects.filter(
        id=record.id,
        status=record.status,
        payload=record.payload,
    ).update(
        status="failed",
        payload=_payload_without_worker_token(record.payload),
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
    counts = {
        "recovered": 0,
        "stale_reset": 0,
        "superseded": 0,
        "discarded": 0,
    }
    unsupported_records = TaskRecord.objects.filter(
        status__in=("pending", "running"),
    ).exclude(task_type__in=("process_knowledge", "cleanup_knowledge_artifacts", "rebuild_vector_index", "prepare_open_rag_dataset", OPEN_RAG_EVALUATION_TASK_TYPE))
    for record in unsupported_records.order_by("created_at", "id"):
        if _mark_recovery_failed(record, f"unsupported task type: {record.task_type}", now):
            counts["discarded"] += 1

    stale_reset = 0
    stale_records = TaskRecord.objects.filter(
        task_type="process_knowledge",
        status="running",
        updated_at__lt=stale_before,
    ).order_by("created_at", "id")
    for stale_record in stale_records:
        reset = TaskRecord.objects.filter(
            id=stale_record.id,
            status="running",
            updated_at__lt=stale_before,
            payload=stale_record.payload,
        ).update(
            status="pending",
            progress=0,
            payload=_payload_without_worker_token(stale_record.payload),
            updated_at=now,
        )
        if reset:
            stale_reset += 1
            cache.delete(f"task:{stale_record.id}")

    counts["stale_reset"] = stale_reset
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
        running = [record for record in group if record.status == "running"]
        if running:
            kept = min(running, key=lambda record: (record.created_at, record.id))
        else:
            kept = group[0]
        for duplicate in (record for record in group if record.id != kept.id):
            message = f"superseded by recoverable task {kept.id}"
            if _mark_recovery_failed(duplicate, message, now):
                counts["superseded"] += 1

        kept.refresh_from_db(fields=("status", "payload"))
        if kept.status != "pending":
            continue
        Knowledge.objects.filter(
            id=kept.payload.get("knowledge_id"),
            deleted_at__isnull=True,
        ).exclude(parse_status="cancelled").update(parse_status="pending", updated_at=now)
        try:
            fn = resolve_task_callable(kept)
        except Exception as exc:
            message = f"unable to resolve task callable: {exc}"
            if _mark_recovery_failed(kept, message, now):
                counts["discarded"] += 1
            continue
        if fn is None:
            if _mark_recovery_failed(kept, "task payload is not recoverable", now):
                counts["discarded"] += 1
            continue
        try:
            enqueued = _enqueue_sequential(kept.id, fn)
        except Exception as exc:
            message = f"unable to enqueue recoverable task: {exc}"
            if _mark_recovery_failed(kept, message, now):
                counts["discarded"] += 1
            continue
        if enqueued:
            counts["recovered"] += 1

    # Model-intensive tasks without a knowledge_id are resolved generically.
    for task_type in ("prepare_open_rag_dataset", OPEN_RAG_EVALUATION_TASK_TYPE, "rebuild_vector_index"):
        records = TaskRecord.objects.filter(task_type=task_type).filter(
            models.Q(status="pending")
            | models.Q(status="running", lease_expires_at__lt=now)
            | models.Q(status="running", lease_expires_at__isnull=True, updated_at__lt=stale_before)
        ).order_by("created_at", "id")
        for record in records:
            try:
                fn = resolve_task_callable(record)
            except Exception as exc:
                if _mark_recovery_failed(record, f"unable to resolve {task_type} callable: {exc}", now):
                    counts["discarded"] += 1
                continue
            if fn is None:
                if _mark_recovery_failed(record, f"{task_type} task payload is not recoverable", now):
                    counts["discarded"] += 1
                continue
            reset = TaskRecord.objects.filter(
                id=record.id,
                status=record.status,
            ).update(
                status="pending",
                payload=_payload_without_worker_token(record.payload),
                claimed_by="",
                lease_expires_at=None,
                updated_at=now,
            )
            cache.delete(f"task:{record.id}")
            if not reset:
                continue
            if record.queue_name == "evaluation":
                counts["recovered"] += 1
                if record.status == "running":
                    counts["stale_reset"] += 1
                continue
            try:
                enqueued = _enqueue_sequential(record.id, fn)
            except Exception as exc:
                record.refresh_from_db()
                if _mark_recovery_failed(record, f"unable to enqueue {task_type}: {exc}", now):
                    counts["discarded"] += 1
                continue
            if enqueued:
                counts["recovered"] += 1
                if record.status == "running":
                    counts["stale_reset"] += 1

    return counts


def should_schedule_recovery(argv=None, environ=None) -> bool:
    argv = list(sys.argv if argv is None else argv)
    environ = os.environ if environ is None else environ
    runner = str(argv[0]).lower().replace("\\", "/") if argv else ""
    runner_name = runner.rsplit("/", 1)[-1]
    if "PYTEST_CURRENT_TEST" in environ:
        return False
    if "pytest" in runner or "py.test" in runner_name or "unittest" in runner:
        return False
    if any(str(argument).lower() == "unittest" for argument in argv[1:]):
        return False
    is_django_module = len(argv) >= 3 and argv[1:3] == ["-m", "django"]
    command_index = 3 if is_django_module else 1
    command = argv[command_index] if len(argv) > command_index else ""
    is_django_main = runner.endswith("/django/__main__.py")
    is_management_command = runner_name in {"manage.py", "django-admin", "django-admin.py", "django-admin.exe"}
    is_management_command = is_management_command or is_django_module or is_django_main
    if is_management_command:
        if command == "runserver":
            autoreload_child = str(environ.get("RUN_MAIN", "")).lower() == "true"
            no_reload = any(str(argument).lower() == "--noreload" for argument in argv[command_index + 1 :])
            return autoreload_child or no_reload
        return False
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
        # 启动时若向量索引处于 needs_rebuild（如维度迁移后）且无在途重建任务，自动入队一个，
        # 避免升级后向量检索长期停留在 FTS-only 降级。
        try:
            from .search import ensure_rebuild_task_enqueued

            ensure_rebuild_task_enqueued(reason="startup_reindex_check")
        except (OperationalError, ProgrammingError) as exc:
            logger.warning("Startup vector reindex check skipped: %s", exc)
        except Exception:
            logger.exception("Startup vector reindex check failed")
        finally:
            close_old_connections()

    initial_timer = threading.Timer(STARTUP_RECOVERY_DELAY, run_recovery)
    initial_timer.daemon = True
    initial_timer.name = "task-startup-recovery"
    lease_timer = threading.Timer(STALE_LEASE_SECONDS + STARTUP_RECOVERY_DELAY, run_recovery)
    lease_timer.daemon = True
    lease_timer.name = "task-startup-lease-recovery"
    initial_timer.start()
    lease_timer.start()
    return initial_timer, lease_timer


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
