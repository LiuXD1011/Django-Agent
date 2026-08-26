"""Tenant-scoped evaluation report storage and lifecycle management.

Reports can be backed by a tenant ``GenericResource`` or by the read-only
public benchmark cache.  The two stores deliberately expose the same contract:
``report_id`` identifies the downloadable artifact while ``task_run_id``
identifies the background task that produced it.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Iterable

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .models import GenericResource, Tenant


MAX_REPORTS_PER_TENANT = 50
REPORT_RESOURCE_TYPE = "rag_eval_runs"
_SENSITIVE_PARTS = ("api_key", "token", "password", "secret", "credential", "authorization")
_REPORT_DELETE_LOCK = threading.Lock()
_CONTENT_KEYS = {
    "answer",
    "content",
    "context",
    "contexts",
    "ground_truth",
    "file_path",
    "question",
    "query",
}


def _git_commit() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
            timeout=1,
        )
        return completed.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _sanitize(value):
    """Remove source text and credentials before a report is persisted."""
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if normalized_key in _CONTENT_KEYS or (normalized_key == "source" and isinstance(item, str)):
                continue
            sanitized[str(key)] = (
                "******"
                if any(part in normalized_key for part in _SENSITIVE_PARTS)
                else _sanitize(item)
            )
        return sanitized
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    return value


def _dataset_summary(dataset) -> dict:
    """Return a compact, stable dataset identity.

    Callers evaluating a versioned dataset should provide ``sha256`` or
    ``dataset_hash``.  The fallback hash keeps the old synchronous APIs
    useful, while freshness for old records remains ``unknown`` when the
    source cannot be resolved later.
    """
    if isinstance(dataset, dict):
        entries = dataset.get("entries", dataset.get("sample_size", dataset.get("count", 0)))
        explicit_hash = dataset.get("sha256") or dataset.get("dataset_hash")
        summary = {
            key: dataset[key]
            for key in ("id", "version", "entries", "sample_size", "documents")
            if key in dataset
        }
    else:
        entries = len(dataset) if isinstance(dataset, list) else 0
        explicit_hash = None
        summary = {}
    encoded = json.dumps(
        dataset if dataset is not None else [],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    summary["sha256"] = str(explicit_hash or hashlib.sha256(encoded.encode("utf-8")).hexdigest())
    summary["entries"] = int(entries or 0)
    if explicit_hash:
        summary["fingerprint_source"] = "source"
    return summary


def _open_report_directory(tenant: Tenant) -> Path:
    return Path(settings.BASE_DIR) / ".cache" / "eval-reports" / str(tenant.id)


def _open_report_path(tenant: Tenant, report_id: str) -> Path:
    # Report IDs are generated UUIDs; basename normalization keeps legacy
    # lookup/delete requests from turning this helper into a path traversal.
    safe_id = Path(str(report_id)).name
    return _open_report_directory(tenant) / f"{safe_id}.json"


def _report_url(report_id: str) -> str:
    return reverse("rag-eval-report", kwargs={"run_id": str(report_id)})


def _verification_status(verified: bool, requested: str | None = None) -> str:
    value = str(requested or "").lower()
    if value in {"verified", "degraded", "unverified", "failed"}:
        return value
    return "verified" if bool(verified) else "unverified"


def _metadata(
    *,
    tenant: Tenant,
    report_id: str,
    task_run_id: str | None,
    evaluation_type: str,
    evaluator: str,
    verified: bool,
    dataset,
    configuration: dict | None,
    requested_configuration: dict | None,
    effective_pipeline: dict | None,
    verification_status: str | None,
    created_at,
) -> dict:
    report_id = str(report_id)
    task_run_id = str(task_run_id) if task_run_id else None
    requested = requested_configuration if requested_configuration is not None else (configuration or {})
    dataset_summary = _dataset_summary(dataset)
    status = _verification_status(verified, verification_status)
    metadata = {
        "report_id": report_id,
        "task_run_id": task_run_id,
        # ``run_id`` is retained for old clients.  New clients must use
        # report_id for downloads and task_run_id for status polling.
        "run_id": task_run_id or report_id,
        "evaluation_type": evaluation_type,
        "evaluator": evaluator,
        "verified": status == "verified",
        "verification_status": status,
        "freshness_status": "unknown",
        "dataset": dataset_summary,
        "requested_configuration": _sanitize(requested),
        "effective_pipeline": _sanitize(effective_pipeline or {}),
        "provenance": {
            "git_commit": _git_commit(),
            "created_at": created_at.isoformat(),
            "configuration": _sanitize(requested),
        },
        "report_url": _report_url(report_id),
        "available": True,
    }
    return metadata


def _metadata_created_at(report: dict):
    value = (report.get("provenance") or {}).get("created_at") or report.get("created_at")
    try:
        return timezone.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return timezone.datetime.min.replace(tzinfo=timezone.utc)


def _current_dataset_fingerprint(tenant: Tenant, report: dict) -> str | None:
    """Resolve the current source fingerprint without using age as freshness."""
    dataset = report.get("dataset") if isinstance(report.get("dataset"), dict) else {}
    stored = str(dataset.get("sha256") or "")
    if not stored or not dataset.get("fingerprint_source"):
        return None
    dataset_id = str(dataset.get("id") or "")
    version = str(dataset.get("version") or "arxiv-v1")
    if dataset_id.startswith("open_rag_benchmark") or dataset_id in {"open_rag_benchmark", "open_rag_benchmark_full"}:
        try:
            from .eval_dataset_registry import get_dataset_spec

            return str(get_dataset_spec(dataset_id, version).sha256)
        except Exception:
            return None
    if dataset_id:
        resource = GenericResource.objects.filter(
            id=dataset_id,
            tenant=tenant,
            resource_type__in=("rag_eval_datasets", "rag_eval_testsets"),
            deleted_at__isnull=True,
        ).first()
        if resource:
            data = resource.data or {}
            expected_documents = dataset.get("documents") or []
            if expected_documents:
                from .models import Knowledge

                expected = sorted(
                    (
                        str(row.get("knowledge_id") or row.get("id") or ""),
                        str(row.get("file_hash") or row.get("version") or "").strip().lower(),
                    ) if isinstance(row, dict) else (str(row[0]), str(row[1]).strip().lower())
                    for row in expected_documents
                    if (isinstance(row, dict) and (row.get("knowledge_id") or row.get("id")))
                    or (isinstance(row, (list, tuple)) and len(row) == 2)
                )
                current = sorted(
                    (str(item.id), str(item.file_hash or "").strip().lower())
                    for item in Knowledge.objects.filter(
                        id__in=[row[0] for row in expected], tenant=tenant, deleted_at__isnull=True
                    )
                )
                if current != expected:
                    return "__document_fingerprint_drift__"
            return str(data.get("dataset_hash") or "") or None
    return None


def _with_freshness(tenant: Tenant, report: dict) -> dict:
    item = dict(report or {})
    if not item.get("report_id"):
        item["report_id"] = item.get("run_id")
    if not item.get("task_run_id"):
        item["task_run_id"] = item.get("run_id") if item.get("report_id") != item.get("run_id") else None
    item["report_url"] = item.get("report_url") or _report_url(item.get("report_id"))
    item["available"] = bool(item.get("available", True))
    current = _current_dataset_fingerprint(tenant, item)
    stored = str((item.get("dataset") or {}).get("sha256") or "")
    if current and stored:
        item["freshness_status"] = "current" if current == stored else "stale"
    else:
        item["freshness_status"] = str(item.get("freshness_status") or "unknown")
    item["verification_status"] = _verification_status(
        bool(item.get("verified")), item.get("verification_status")
    )
    item["verified"] = item["verification_status"] == "verified"
    return item


def _task_matches_report(task, report_id: str, task_run_id: str | None) -> bool:
    payload = task.payload if isinstance(task.payload, dict) else {}
    result = task.result if isinstance(task.result, dict) else {}
    report = result.get("report") if isinstance(result.get("report"), dict) else {}
    payload_report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
    ids = {
        str(report.get("id") or report.get("report_id") or ""),
        str(result.get("report_id") or ""),
        str(payload.get("report_id") or ""),
        str(payload_report.get("id") or payload_report.get("report_id") or ""),
    }
    task_id = str(task_run_id or "")
    return str(report_id) in ids or (task_id and str(task.id) == task_id)


def _attach_task_report_pointer(tenant: Tenant, task_run_id: str | None, metadata: dict) -> None:
    if not task_run_id:
        return
    from .models import TaskRecord

    task = TaskRecord.objects.filter(id=str(task_run_id)).first()
    if task is None:
        return
    payload = task.payload if isinstance(task.payload, dict) else {}
    if payload.get("tenant_id") and str(payload.get("tenant_id")) != str(tenant.id):
        return
    result = dict(task.result) if isinstance(task.result, dict) else {}
    result["report_id"] = metadata.get("report_id")
    result["report_url"] = metadata.get("report_url")
    result["report"] = {
        "id": metadata.get("report_id"),
        "report_id": metadata.get("report_id"),
        "task_run_id": str(task_run_id),
        "url": metadata.get("report_url"),
        "available": True,
    }
    task.result = result
    task.save(update_fields=["result", "updated_at"])


def _invalidate_task_report_pointer(tenant: Tenant, report_id: str, task_run_id: str | None) -> None:
    """Keep audit TaskRecords but make a deleted report unavailable."""
    from .models import TaskRecord

    for task in TaskRecord.objects.all().only("id", "payload", "result"):
        payload = task.payload if isinstance(task.payload, dict) else {}
        if payload.get("tenant_id") and str(payload.get("tenant_id")) != str(tenant.id):
            continue
        if not _task_matches_report(task, report_id, task_run_id):
            continue
        result = dict(task.result) if isinstance(task.result, dict) else {}
        pointer = dict(result.get("report") or {})
        pointer.update({"id": str(report_id), "report_id": str(report_id), "url": None, "available": False})
        result["report"] = pointer
        result["report_id"] = str(report_id)
        task.result = result
        payload_changed = False
        payload = dict(task.payload) if isinstance(task.payload, dict) else {}
        if str(payload.get("report_id") or "") == str(report_id):
            payload["report_available"] = False
            payload_changed = True
        if isinstance(payload.get("report"), dict) and str(payload["report"].get("id") or payload["report"].get("report_id") or "") == str(report_id):
            payload["report"] = {**payload["report"], "url": None, "available": False}
            payload_changed = True
        task.payload = payload
        task.save(update_fields=["result", "payload", "updated_at"] if payload_changed else ["result", "updated_at"])


def _iter_report_entries(tenant: Tenant) -> Iterable[tuple[str, str, object, dict]]:
    for item in GenericResource.objects.filter(
        tenant=tenant,
        resource_type=REPORT_RESOURCE_TYPE,
        deleted_at__isnull=True,
    ).only("id", "data", "created_at"):
        data = dict(item.data or {})
        report_id = str(data.get("report_id") or item.id)
        yield "database", report_id, item, data
    directory = _open_report_directory(tenant)
    if not directory.is_dir():
        return
    for path in directory.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        report_id = str(data.get("report_id") or data.get("run_id") or path.stem)
        yield "file", report_id, path, data


def _prune_reports(tenant: Tenant) -> None:
    """Enforce one tenant-wide retention limit across both storage backends."""
    entries = list(_iter_report_entries(tenant))
    entries.sort(key=lambda item: _metadata_created_at(item[3]), reverse=True)
    for kind, report_id, item, data in entries[MAX_REPORTS_PER_TENANT:]:
        try:
            if kind == "database":
                item.delete()
            else:
                item.unlink(missing_ok=True)
            _invalidate_task_report_pointer(tenant, report_id, data.get("task_run_id"))
        except OSError:
            continue


def save_open_evaluation_report(
    *,
    tenant: Tenant,
    evaluation_type: str,
    evaluator: str,
    verified: bool,
    dataset,
    result: dict,
    configuration: dict | None = None,
    run_id: str | None = None,
    task_run_id: str | None = None,
    requested_configuration: dict | None = None,
    effective_pipeline: dict | None = None,
    verification_status: str | None = None,
) -> dict:
    """Store a public benchmark report outside tenant database resources."""
    task_run_id = task_run_id or run_id
    report_id = uuid.uuid4().hex
    created_at = timezone.now()
    metadata = _metadata(
        tenant=tenant,
        report_id=report_id,
        task_run_id=task_run_id,
        evaluation_type=evaluation_type,
        evaluator=evaluator,
        verified=verified,
        dataset=dataset,
        configuration=configuration,
        requested_configuration=requested_configuration,
        effective_pipeline=effective_pipeline,
        verification_status=verification_status,
        created_at=created_at,
    )
    target = _open_report_path(tenant, report_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.part")
    temporary.write_text(
        json.dumps({**metadata, "result": _sanitize(result)}, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(target)
    _attach_task_report_pointer(tenant, task_run_id, metadata)
    _prune_reports(tenant)
    fresh_metadata = _with_freshness(tenant, metadata)
    if fresh_metadata.get("freshness_status") != metadata.get("freshness_status") and target.is_file():
        try:
            stored = json.loads(target.read_text(encoding="utf-8"))
            stored.update({"freshness_status": fresh_metadata.get("freshness_status")})
            temporary = target.with_suffix(".json.part")
            temporary.write_text(json.dumps(stored, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            temporary.replace(target)
        except (OSError, ValueError):
            pass
    return fresh_metadata


def save_evaluation_report(
    *,
    tenant: Tenant,
    evaluation_type: str,
    evaluator: str,
    verified: bool,
    dataset,
    result: dict,
    configuration: dict | None = None,
    task_run_id: str | None = None,
    run_id: str | None = None,
    requested_configuration: dict | None = None,
    effective_pipeline: dict | None = None,
    verification_status: str | None = None,
) -> dict:
    """Persist one completed or unverified run and return public metadata."""
    task_run_id = task_run_id or run_id
    item = GenericResource.objects.create(
        tenant=tenant,
        resource_type=REPORT_RESOURCE_TYPE,
        name=f"{evaluation_type} evaluation",
        status=_verification_status(verified, verification_status),
        data={},
    )
    created_at = item.created_at or timezone.now()
    metadata = _metadata(
        tenant=tenant,
        report_id=item.id,
        task_run_id=task_run_id,
        evaluation_type=evaluation_type,
        evaluator=evaluator,
        verified=verified,
        dataset=dataset,
        configuration=configuration,
        requested_configuration=requested_configuration,
        effective_pipeline=effective_pipeline,
        verification_status=verification_status,
        created_at=created_at,
    )
    item.data = {**metadata, "result": _sanitize(result)}
    item.save(update_fields=["data", "status", "updated_at"])
    _attach_task_report_pointer(tenant, task_run_id, metadata)
    _prune_reports(tenant)
    fresh_metadata = _with_freshness(tenant, metadata)
    if fresh_metadata.get("freshness_status") != metadata.get("freshness_status"):
        item.refresh_from_db(fields=["data"])
        item.data = {**(item.data or {}), "freshness_status": fresh_metadata.get("freshness_status")}
        item.save(update_fields=["data", "updated_at"])
    return fresh_metadata


def _find_file_report(tenant: Tenant, report_id: str):
    path = _open_report_path(tenant, report_id)
    if path.is_file():
        return path, None
    # Old file reports were named by run_id and did not carry report_id.
    directory = _open_report_directory(tenant)
    if directory.is_dir():
        for candidate in directory.glob("*.json"):
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("report_id"):
                continue
            if str(data.get("run_id") or "") == str(report_id):
                return candidate, data
    return None, None


def report_exists(tenant: Tenant, report_id: str) -> bool:
    return get_evaluation_report(tenant, report_id) is not None


def get_evaluation_report(tenant: Tenant, report_id: str) -> dict | None:
    report_id = str(report_id)
    item = GenericResource.objects.filter(
        id=report_id,
        tenant=tenant,
        resource_type=REPORT_RESOURCE_TYPE,
        deleted_at__isnull=True,
    ).first()
    if item:
        report = dict(item.data or {})
        report.setdefault("report_id", item.id)
        report.setdefault("available", True)
        return _with_freshness(tenant, report)
    path, cached = _find_file_report(tenant, report_id)
    if path is None:
        return None
    try:
        report = cached or json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    report = dict(report or {})
    report.setdefault("report_id", report.get("run_id") or path.stem)
    report.setdefault("available", True)
    return _with_freshness(tenant, report)


def delete_evaluation_report(tenant: Tenant, report_id: str) -> bool:
    """Delete a report for this tenant; foreign and missing IDs look identical."""
    report_id = str(report_id)
    with _REPORT_DELETE_LOCK:
        report = get_evaluation_report(tenant, report_id)
        if report is None:
            return False
        task_run_id = report.get("task_run_id")
        item = GenericResource.objects.filter(
            id=report_id,
            tenant=tenant,
            resource_type=REPORT_RESOURCE_TYPE,
            deleted_at__isnull=True,
        ).first()
        if item:
            item.delete()
        path, _cached = _find_file_report(tenant, report_id)
        if path is not None:
            path.unlink(missing_ok=True)
        _invalidate_task_report_pointer(tenant, report_id, task_run_id)
        return True


def _history_item(tenant: Tenant, report: dict) -> dict:
    item = _with_freshness(tenant, report)
    created_at = (item.get("provenance") or {}).get("created_at")
    return {
        key: item.get(key)
        for key in (
            "report_id", "task_run_id", "run_id", "evaluation_type", "evaluator",
            "dataset", "requested_configuration", "effective_pipeline",
            "verification_status", "freshness_status", "verified", "provenance",
            "report_url", "available",
        )
    } | {"created_at": created_at}


def recent_evaluation_reports(tenant: Tenant) -> list[dict]:
    """Return one tenant-wide, consistently shaped report history."""
    reports = []
    for _kind, _report_id, _item, data in _iter_report_entries(tenant):
        normalized = dict(data)
        normalized.setdefault("report_id", _report_id)
        reports.append(_history_item(tenant, normalized))
    reports.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return reports[:MAX_REPORTS_PER_TENANT]


# Kept as a small compatibility helper for imports in older callers.
def _trim_reports(tenant: Tenant) -> None:
    _prune_reports(tenant)
