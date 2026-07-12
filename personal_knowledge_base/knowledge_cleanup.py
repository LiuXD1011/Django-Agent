from collections import defaultdict
from dataclasses import dataclass, field

from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from .graph_rag import delete_knowledge_graph
from .models import Chunk, Knowledge, KnowledgeImage, KnowledgeProcessingSpan, TaskRecord, WikiPendingOp
from .search import delete_chunk_index
from .tasks import _mark_recovery_failed
from .wiki_ingest import WIKI_TASK_TYPE, cleanup_wiki_for_knowledge, process_wiki_ingest


UNFINISHED_TASK_STATUSES = ("pending", "running")
MAX_WIKI_CLEANUP_BATCHES = 100


@dataclass(frozen=True)
class _DeleteSnapshot:
    delete_id: str
    keep_id: str
    tenant_id: int
    knowledge_base_id: str
    file_hash: str


@dataclass(frozen=True)
class _PostCommitCleanup:
    chunks: tuple[tuple[str, int | None], ...]
    image_paths: tuple[str, ...]
    task_ids: tuple[str, ...]
    original_path: str


@dataclass(frozen=True)
class CleanupPlan:
    keep_ids: tuple[str, ...]
    delete_ids: tuple[str, ...]
    invalid_task_ids: tuple[str, ...]
    superseded_task_ids: tuple[str, ...]
    _delete_snapshots: tuple[_DeleteSnapshot, ...] = field(default=(), repr=False, compare=False)


def _knowledge_sort_key(item: Knowledge):
    return (
        item.deleted_at is not None,
        item.parse_status != "completed",
        item.created_at,
        item.id,
    )


def _task_sort_key(record: TaskRecord):
    return (record.status != "running", record.created_at, record.id)


def plan_knowledge_cleanup() -> CleanupPlan:
    groups: dict[tuple[int, str, str], list[Knowledge]] = defaultdict(list)
    knowledge_items = Knowledge.objects.filter(type="file").exclude(file_hash="")
    for item in knowledge_items.iterator():
        groups[(item.tenant_id, item.knowledge_base_id, item.file_hash)].append(item)

    keep_ids = []
    delete_ids = []
    delete_snapshots = []
    for key in sorted(groups):
        ordered = sorted(groups[key], key=_knowledge_sort_key)
        kept = ordered[0]
        keep_ids.append(kept.id)
        for item in ordered[1:]:
            delete_ids.append(item.id)
            delete_snapshots.append(
                _DeleteSnapshot(
                    delete_id=item.id,
                    keep_id=kept.id,
                    tenant_id=item.tenant_id,
                    knowledge_base_id=item.knowledge_base_id,
                    file_hash=item.file_hash,
                )
            )

    invalid_task_ids = []
    tasks_by_knowledge: dict[str, list[TaskRecord]] = defaultdict(list)
    records = TaskRecord.objects.filter(
        task_type="process_knowledge",
        status__in=UNFINISHED_TASK_STATUSES,
    ).order_by("created_at", "id")
    records = list(records)
    referenced_ids = {
        str(record.payload.get("knowledge_id") or "")
        for record in records
        if isinstance(record.payload, dict) and record.payload.get("knowledge_id")
    }
    knowledge_states = {
        item["id"]: item
        for item in Knowledge.objects.filter(id__in=referenced_ids).values("id", "deleted_at", "parse_status")
    }
    for record in records:
        payload = record.payload if isinstance(record.payload, dict) else {}
        knowledge_id = str(payload.get("knowledge_id") or "")
        state = knowledge_states.get(knowledge_id)
        valid = bool(state) and state["deleted_at"] is None and state["parse_status"] != "cancelled"
        if not valid:
            invalid_task_ids.append(record.id)
        else:
            tasks_by_knowledge[knowledge_id].append(record)

    superseded_task_ids = []
    for knowledge_id in sorted(tasks_by_knowledge):
        group = sorted(tasks_by_knowledge[knowledge_id], key=_task_sort_key)
        superseded_task_ids.extend(record.id for record in group[1:])

    return CleanupPlan(
        keep_ids=tuple(keep_ids),
        delete_ids=tuple(delete_ids),
        invalid_task_ids=tuple(invalid_task_ids),
        superseded_task_ids=tuple(superseded_task_ids),
        _delete_snapshots=tuple(delete_snapshots),
    )


def _reconcile_invalid_task(task_id: str, now) -> bool:
    record = TaskRecord.objects.filter(id=task_id).first()
    if record is None or record.status not in UNFINISHED_TASK_STATUSES:
        return False
    payload = record.payload if isinstance(record.payload, dict) else {}
    knowledge_id = str(payload.get("knowledge_id") or "")
    knowledge_is_valid = bool(knowledge_id) and Knowledge.objects.filter(
        id=knowledge_id,
        deleted_at__isnull=True,
    ).exclude(parse_status="cancelled").exists()
    if knowledge_is_valid:
        return False
    return _mark_recovery_failed(record, f"knowledge {knowledge_id or '<missing>'} is not recoverable", now)


def _reconcile_superseded_task(task_id: str, now) -> bool:
    record = TaskRecord.objects.filter(id=task_id).first()
    if record is None or record.status not in UNFINISHED_TASK_STATUSES:
        return False
    payload = record.payload if isinstance(record.payload, dict) else {}
    knowledge_id = str(payload.get("knowledge_id") or "")
    knowledge_is_valid = bool(knowledge_id) and Knowledge.objects.filter(
        id=knowledge_id,
        deleted_at__isnull=True,
    ).exclude(parse_status="cancelled").exists()
    if not knowledge_is_valid:
        return False
    candidates = list(
        TaskRecord.objects.filter(
            task_type="process_knowledge",
            status__in=UNFINISHED_TASK_STATUSES,
            payload__knowledge_id=knowledge_id,
        )
    )
    if len(candidates) < 2:
        return False
    kept = min(candidates, key=_task_sort_key)
    if kept.id == record.id:
        return False
    return _mark_recovery_failed(record, f"superseded by recoverable task {kept.id}", now)


def _snapshot_for(plan: CleanupPlan, knowledge_id: str) -> _DeleteSnapshot | None:
    return next((snapshot for snapshot in plan._delete_snapshots if snapshot.delete_id == knowledge_id), None)


def _is_current_delete_candidate(item: Knowledge, snapshot: _DeleteSnapshot) -> bool:
    identity = (item.tenant_id, item.knowledge_base_id, item.file_hash)
    expected = (snapshot.tenant_id, snapshot.knowledge_base_id, snapshot.file_hash)
    if item.type != "file" or not item.file_hash or identity != expected:
        return False
    group = list(
        Knowledge.objects.filter(
            type="file",
            tenant_id=snapshot.tenant_id,
            knowledge_base_id=snapshot.knowledge_base_id,
            file_hash=snapshot.file_hash,
        )
    )
    if len(group) < 2:
        return False
    ordered = sorted(group, key=_knowledge_sort_key)
    return ordered[0].id == snapshot.keep_id and item.id in {candidate.id for candidate in ordered[1:]}


def _cleanup_wiki_retract(item: Knowledge) -> None:
    cleanup_wiki_for_knowledge(item)
    target = {
        "task_type": WIKI_TASK_TYPE,
        "scope": "knowledge_base",
        "scope_id": item.knowledge_base_id,
        "op": "retract",
        "dedup_key": item.id,
    }
    for _ in range(MAX_WIKI_CLEANUP_BATCHES):
        if not WikiPendingOp.objects.filter(**target).exists():
            return
        process_wiki_ingest(item.knowledge_base_id)
    if WikiPendingOp.objects.filter(**target).exists():
        raise RuntimeError(f"Wiki retract for knowledge {item.id} remained pending")


def _delete_database_state(item: Knowledge) -> _PostCommitCleanup:
    chunks = tuple(Chunk.objects.filter(knowledge=item).values_list("id", "seq_id"))
    owned_paths = set(
        KnowledgeImage.objects.filter(knowledge=item, storage_owned=True)
        .exclude(storage_path="")
        .values_list("storage_path", flat=True)
    )
    image_paths = tuple(
        sorted(
            path
            for path in owned_paths
            if not KnowledgeImage.objects.filter(storage_path=path).exclude(knowledge=item).exists()
        )
    )
    task_ids = tuple(
        TaskRecord.objects.filter(task_type="process_knowledge", payload__knowledge_id=item.id).values_list(
            "id", flat=True
        )
    )
    file_path = item.file_path

    Chunk.objects.filter(knowledge=item).delete()
    KnowledgeImage.objects.filter(knowledge=item).delete()
    TaskRecord.objects.filter(id__in=task_ids).delete()
    KnowledgeProcessingSpan.objects.filter(knowledge=item).delete()
    item.delete()

    original_path = file_path if file_path and not Knowledge.objects.filter(file_path=file_path).exists() else ""
    return _PostCommitCleanup(
        chunks=chunks,
        image_paths=image_paths,
        task_ids=task_ids,
        original_path=original_path,
    )


def _run_post_commit_cleanup(cleanup: _PostCommitCleanup) -> list[str]:
    errors = []
    for chunk_id, seq_id in cleanup.chunks:
        try:
            delete_chunk_index(chunk_id, seq_id)
        except Exception as exc:
            errors.append(f"chunk index {chunk_id}: {exc}")
    for path in cleanup.image_paths:
        try:
            default_storage.delete(path)
        except Exception as exc:
            errors.append(f"image file {path}: {exc}")
    for task_id in cleanup.task_ids:
        try:
            cache.delete(f"task:{task_id}")
        except Exception as exc:
            errors.append(f"task cache {task_id}: {exc}")
    if cleanup.original_path:
        try:
            default_storage.delete(cleanup.original_path)
        except Exception as exc:
            errors.append(f"original file {cleanup.original_path}: {exc}")
    return errors


def _delete_one_knowledge(item: Knowledge, snapshot: _DeleteSnapshot) -> tuple[bool, list[str]]:
    if not _is_current_delete_candidate(item, snapshot):
        return False, []
    _cleanup_wiki_retract(item)
    delete_knowledge_graph(item)

    with transaction.atomic():
        current = Knowledge.objects.select_for_update().filter(id=item.id).first()
        if current is None or not _is_current_delete_candidate(current, snapshot):
            return False, []
        post_commit = _delete_database_state(current)
    return True, _run_post_commit_cleanup(post_commit)


def execute_knowledge_cleanup(plan: CleanupPlan) -> dict:
    now = timezone.now()
    invalid_reconciled = sum(_reconcile_invalid_task(task_id, now) for task_id in plan.invalid_task_ids)
    superseded_reconciled = sum(
        _reconcile_superseded_task(task_id, now)
        for task_id in plan.superseded_task_ids
    )

    deleted = []
    errors = {}
    for knowledge_id in plan.delete_ids:
        snapshot = _snapshot_for(plan, knowledge_id)
        if snapshot is None:
            continue
        item = Knowledge.objects.filter(id=knowledge_id).select_related("knowledge_base", "tenant").first()
        if item is None:
            continue
        try:
            was_deleted, cleanup_errors = _delete_one_knowledge(item, snapshot)
        except Exception as exc:
            errors[knowledge_id] = str(exc)
        else:
            if not was_deleted:
                continue
            deleted.append(knowledge_id)
            if cleanup_errors:
                errors[knowledge_id] = "; ".join(cleanup_errors)

    return {
        "deleted": deleted,
        "errors": errors,
        "invalid_tasks_reconciled": invalid_reconciled,
        "superseded_tasks_reconciled": superseded_reconciled,
    }
