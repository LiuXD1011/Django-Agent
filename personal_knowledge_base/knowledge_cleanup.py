from collections import defaultdict
from dataclasses import dataclass, field

from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from .graph_rag import delete_knowledge_graph
from .models import Chunk, Knowledge, KnowledgeImage, KnowledgeProcessingSpan, TaskRecord, WikiPendingOp
from .search import delete_chunk_index
from .tasks import _mark_recovery_failed
from .wiki_ingest import WIKI_TASK_TYPE, cleanup_wiki_for_knowledge, process_wiki_ingest


UNFINISHED_TASK_STATUSES = ("pending", "running")
MAX_WIKI_CLEANUP_BATCHES = 100
ARTIFACT_TASK_TYPE = "cleanup_knowledge_artifacts"


@dataclass(frozen=True)
class _DeleteSnapshot:
    delete_id: str
    keep_id: str
    tenant_id: int
    knowledge_base_id: str
    file_hash: str


@dataclass(frozen=True)
class CleanupPlan:
    keep_ids: tuple[str, ...]
    delete_ids: tuple[str, ...]
    invalid_task_ids: tuple[str, ...]
    superseded_task_ids: tuple[str, ...]
    _delete_snapshots: tuple[_DeleteSnapshot, ...] = field(default=(), repr=False, compare=False)
    _artifact_manifest_ids: tuple[str, ...] = field(default=(), repr=False, compare=False)


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
        _artifact_manifest_ids=tuple(
            TaskRecord.objects.filter(task_type=ARTIFACT_TASK_TYPE).values_list("id", flat=True)
        ),
    )


def _reconcile_invalid_task(task_id: str, now) -> bool:
    with transaction.atomic():
        record = TaskRecord.objects.select_for_update().filter(id=task_id).first()
        if record is None or record.status not in UNFINISHED_TASK_STATUSES:
            return False
        TaskRecord.objects.filter(id=record.id).update(updated_at=F("updated_at"))
        payload = record.payload if isinstance(record.payload, dict) else {}
        knowledge_id = str(payload.get("knowledge_id") or "")
        knowledge = Knowledge.objects.select_for_update().filter(id=knowledge_id).first() if knowledge_id else None
        if knowledge is not None and knowledge.deleted_at is None and knowledge.parse_status != "cancelled":
            return False
        return _mark_recovery_failed(record, f"knowledge {knowledge_id or '<missing>'} is not recoverable", now)


def _reconcile_superseded_task(task_id: str, now) -> bool:
    with transaction.atomic():
        record = TaskRecord.objects.select_for_update().filter(id=task_id).first()
        if record is None or record.status not in UNFINISHED_TASK_STATUSES:
            return False
        TaskRecord.objects.filter(id=record.id).update(updated_at=F("updated_at"))
        payload = record.payload if isinstance(record.payload, dict) else {}
        knowledge_id = str(payload.get("knowledge_id") or "")
        knowledge = Knowledge.objects.select_for_update().filter(id=knowledge_id).first() if knowledge_id else None
        if knowledge is None or knowledge.deleted_at is not None or knowledge.parse_status == "cancelled":
            return False
        candidates = list(
            TaskRecord.objects.select_for_update().filter(
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


def _is_current_delete_candidate(item: Knowledge, snapshot: _DeleteSnapshot, group: list[Knowledge]) -> bool:
    identity = (item.tenant_id, item.knowledge_base_id, item.file_hash)
    expected = (snapshot.tenant_id, snapshot.knowledge_base_id, snapshot.file_hash)
    if item.type != "file" or not item.file_hash or identity != expected:
        return False
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


def _create_artifact_manifest(item: Knowledge) -> TaskRecord:
    chunks = list(Chunk.objects.filter(knowledge=item).values_list("id", "seq_id"))
    owned_paths = set(
        KnowledgeImage.objects.filter(knowledge=item, storage_owned=True)
        .exclude(storage_path="")
        .values_list("storage_path", flat=True)
    )
    task_ids = list(
        TaskRecord.objects.filter(task_type="process_knowledge", payload__knowledge_id=item.id).values_list(
            "id", flat=True
        )
    )
    return TaskRecord.objects.create(
        task_type=ARTIFACT_TASK_TYPE,
        status="pending",
        payload={
            "knowledge_id": item.id,
            "tenant_id": item.tenant_id,
            "knowledge_base_id": item.knowledge_base_id,
            "file_hash": item.file_hash,
            "chunks": chunks,
            "image_paths": sorted(owned_paths),
            "task_cache_ids": task_ids,
            "original_path": item.file_path,
        },
    )


def _delete_database_state(item: Knowledge, manifest: TaskRecord) -> None:
    task_ids = manifest.payload.get("task_cache_ids") or []

    Chunk.objects.filter(knowledge=item).delete()
    KnowledgeImage.objects.filter(knowledge=item).delete()
    TaskRecord.objects.filter(id__in=task_ids).delete()
    KnowledgeProcessingSpan.objects.filter(knowledge=item).delete()
    item.delete()


def _retry_artifact_manifest(manifest_id: str) -> dict:
    manifest = TaskRecord.objects.filter(id=manifest_id, task_type=ARTIFACT_TASK_TYPE).first()
    if manifest is None:
        return {"manifest_id": manifest_id, "completed": True, "errors": []}
    TaskRecord.objects.filter(id=manifest.id).update(status="running", error_message="")
    payload = manifest.payload if isinstance(manifest.payload, dict) else {}
    errors = []
    for chunk_id, seq_id in payload.get("chunks") or []:
        try:
            delete_chunk_index(chunk_id, seq_id)
        except Exception as exc:
            errors.append(f"chunk index {chunk_id}: {exc}")
    for path in payload.get("image_paths") or []:
        if KnowledgeImage.objects.filter(storage_path=path).exists():
            continue
        try:
            default_storage.delete(path)
        except Exception as exc:
            errors.append(f"image file {path}: {exc}")
    for task_id in payload.get("task_cache_ids") or []:
        try:
            cache.delete(f"task:{task_id}")
        except Exception as exc:
            errors.append(f"task cache {task_id}: {exc}")
    original_path = str(payload.get("original_path") or "")
    if original_path and not Knowledge.objects.filter(file_path=original_path).exists():
        try:
            default_storage.delete(original_path)
        except Exception as exc:
            errors.append(f"original file {original_path}: {exc}")
    if errors:
        message = "; ".join(errors)
        TaskRecord.objects.filter(id=manifest.id).update(status="failed", error_message=message)
        return {"manifest_id": manifest.id, "completed": False, "errors": errors}
    TaskRecord.objects.filter(id=manifest.id).delete()
    return {"manifest_id": manifest.id, "completed": True, "errors": []}


def _delete_one_knowledge(snapshot: _DeleteSnapshot) -> tuple[bool, dict | None]:
    callback_result = {}
    with transaction.atomic(durable=True):
        current = Knowledge.objects.filter(id=snapshot.delete_id).first()
        if current is None:
            return False, None
        identity = (current.tenant_id, current.knowledge_base_id, current.file_hash)
        if current.type != "file" or not current.file_hash or identity != (
            snapshot.tenant_id,
            snapshot.knowledge_base_id,
            snapshot.file_hash,
        ):
            return False, None
        Knowledge.objects.filter(id=current.id).update(updated_at=F("updated_at"))
        group_query = Knowledge.objects.select_for_update().filter(
            type="file",
            tenant_id=snapshot.tenant_id,
            knowledge_base_id=snapshot.knowledge_base_id,
            file_hash=snapshot.file_hash,
        )
        group = list(group_query)
        if not _is_current_delete_candidate(current, snapshot, group):
            return False, None

        current = next(item for item in group if item.id == current.id)
        _cleanup_wiki_retract(current)
        delete_knowledge_graph(current)

        group = list(group_query)
        current = next((item for item in group if item.id == snapshot.delete_id), None)
        if current is None or not _is_current_delete_candidate(current, snapshot, group):
            raise RuntimeError(f"duplicate group changed while cleaning knowledge {snapshot.delete_id}")
        manifest = _create_artifact_manifest(current)
        _delete_database_state(current, manifest)

        def retry_after_commit():
            callback_result.update(_retry_artifact_manifest(manifest.id))

        transaction.on_commit(retry_after_commit)
    return True, callback_result


def _retry_planned_manifests(manifest_ids: tuple[str, ...]) -> dict:
    completed = []
    errors = {}
    for manifest_id in manifest_ids:
        result = _retry_artifact_manifest(manifest_id)
        if result["completed"]:
            completed.append(manifest_id)
        else:
            errors[manifest_id] = "; ".join(result["errors"])
    return {"completed": completed, "errors": errors}


def execute_knowledge_cleanup(plan: CleanupPlan) -> dict:
    if connection.in_atomic_block:
        raise RuntimeError("execute_knowledge_cleanup requires an outermost transaction boundary")
    artifact_retries = _retry_planned_manifests(plan._artifact_manifest_ids)
    now = timezone.now()
    invalid_reconciled = sum(_reconcile_invalid_task(task_id, now) for task_id in plan.invalid_task_ids)
    superseded_reconciled = sum(
        _reconcile_superseded_task(task_id, now)
        for task_id in plan.superseded_task_ids
    )

    deleted = []
    errors = {}
    snapshots = {snapshot.delete_id: snapshot for snapshot in plan._delete_snapshots}
    for knowledge_id in plan.delete_ids:
        snapshot = snapshots.get(knowledge_id)
        if snapshot is None:
            continue
        try:
            was_deleted, manifest_result = _delete_one_knowledge(snapshot)
        except Exception as exc:
            errors[knowledge_id] = str(exc)
        else:
            if not was_deleted:
                continue
            deleted.append(knowledge_id)
            if manifest_result and not manifest_result.get("completed"):
                message = "; ".join(manifest_result.get("errors") or [])
                errors[knowledge_id] = message
                artifact_retries["errors"][manifest_result["manifest_id"]] = message
            elif manifest_result:
                artifact_retries["completed"].append(manifest_result["manifest_id"])

    return {
        "deleted": deleted,
        "errors": errors,
        "invalid_tasks_reconciled": invalid_reconciled,
        "superseded_tasks_reconciled": superseded_reconciled,
        "artifact_retries": artifact_retries,
    }
