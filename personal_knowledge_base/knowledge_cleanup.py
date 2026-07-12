from collections import defaultdict
from dataclasses import dataclass

from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from .graph_rag import delete_knowledge_graph
from .models import Chunk, Knowledge, KnowledgeImage, KnowledgeProcessingSpan, TaskRecord
from .search import delete_chunk_index
from .tasks import _mark_recovery_failed
from .wiki_ingest import cleanup_wiki_for_knowledge


UNFINISHED_TASK_STATUSES = ("pending", "running")


@dataclass(frozen=True)
class CleanupPlan:
    keep_ids: tuple[str, ...]
    delete_ids: tuple[str, ...]
    invalid_task_ids: tuple[str, ...]
    superseded_task_ids: tuple[str, ...]


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
    for key in sorted(groups):
        ordered = sorted(groups[key], key=_knowledge_sort_key)
        keep_ids.append(ordered[0].id)
        delete_ids.extend(item.id for item in ordered[1:])

    invalid_task_ids = []
    tasks_by_knowledge: dict[str, list[TaskRecord]] = defaultdict(list)
    records = TaskRecord.objects.filter(
        task_type="process_knowledge",
        status__in=UNFINISHED_TASK_STATUSES,
    ).order_by("created_at", "id")
    for record in records:
        payload = record.payload if isinstance(record.payload, dict) else {}
        knowledge_id = str(payload.get("knowledge_id") or "")
        valid = bool(knowledge_id) and Knowledge.objects.filter(
            id=knowledge_id,
            deleted_at__isnull=True,
        ).exclude(parse_status="cancelled").exists()
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
    )


def _reconcile_invalid_task(task_id: str, now) -> bool:
    record = TaskRecord.objects.filter(id=task_id).first()
    if record is None or record.status not in UNFINISHED_TASK_STATUSES:
        return False
    payload = record.payload if isinstance(record.payload, dict) else {}
    knowledge_id = str(payload.get("knowledge_id") or "")
    return _mark_recovery_failed(record, f"knowledge {knowledge_id or '<missing>'} is not recoverable", now)


def _reconcile_superseded_task(task_id: str, superseded_ids: tuple[str, ...], now) -> bool:
    record = TaskRecord.objects.filter(id=task_id).first()
    if record is None or record.status not in UNFINISHED_TASK_STATUSES:
        return False
    payload = record.payload if isinstance(record.payload, dict) else {}
    knowledge_id = str(payload.get("knowledge_id") or "")
    candidates = list(
        TaskRecord.objects.filter(
            task_type="process_knowledge",
            status__in=UNFINISHED_TASK_STATUSES,
            payload__knowledge_id=knowledge_id,
        ).exclude(id__in=superseded_ids)
    )
    if not candidates:
        return False
    kept = min(candidates, key=_task_sort_key)
    return _mark_recovery_failed(record, f"superseded by recoverable task {kept.id}", now)


def _delete_one_knowledge(item: Knowledge) -> None:
    cleanup_wiki_for_knowledge(item)
    delete_knowledge_graph(item)

    with transaction.atomic():
        chunks = list(Chunk.objects.filter(knowledge=item))
        for chunk in chunks:
            delete_chunk_index(chunk.id, chunk.seq_id)
        Chunk.objects.filter(knowledge=item).delete()

        images = list(KnowledgeImage.objects.filter(knowledge=item))
        owned_paths = {image.storage_path for image in images if image.storage_owned and image.storage_path}
        for path in owned_paths:
            shared = KnowledgeImage.objects.filter(storage_owned=True, storage_path=path).exclude(knowledge=item).exists()
            if not shared:
                default_storage.delete(path)
        KnowledgeImage.objects.filter(knowledge=item).delete()

        TaskRecord.objects.filter(task_type="process_knowledge", payload__knowledge_id=item.id).delete()
        KnowledgeProcessingSpan.objects.filter(knowledge=item).delete()
        file_path = item.file_path
        item.delete()

        if file_path and not Knowledge.objects.filter(file_path=file_path).exists():
            default_storage.delete(file_path)


def execute_knowledge_cleanup(plan: CleanupPlan) -> dict:
    now = timezone.now()
    invalid_reconciled = sum(_reconcile_invalid_task(task_id, now) for task_id in plan.invalid_task_ids)
    superseded_reconciled = sum(
        _reconcile_superseded_task(task_id, plan.superseded_task_ids, now)
        for task_id in plan.superseded_task_ids
    )

    deleted = []
    errors = {}
    for knowledge_id in plan.delete_ids:
        item = Knowledge.objects.filter(id=knowledge_id).select_related("knowledge_base", "tenant").first()
        if item is None:
            continue
        try:
            _delete_one_knowledge(item)
        except Exception as exc:
            errors[knowledge_id] = str(exc)
        else:
            deleted.append(knowledge_id)

    return {
        "deleted": deleted,
        "errors": errors,
        "invalid_tasks_reconciled": invalid_reconciled,
        "superseded_tasks_reconciled": superseded_reconciled,
    }
