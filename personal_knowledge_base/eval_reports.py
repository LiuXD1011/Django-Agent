"""Tenant-scoped, downloadable provenance records for evaluation runs."""

import hashlib
import json
import subprocess

from django.urls import reverse
from django.utils import timezone

from .models import GenericResource, Tenant


MAX_REPORTS_PER_TENANT = 50
_SENSITIVE_PARTS = ("api_key", "token", "password", "secret", "credential", "authorization")
_CONTENT_KEYS = {"answer", "content", "context", "contexts", "ground_truth", "source", "file_path"}


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
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if normalized_key in _CONTENT_KEYS:
                continue
            sanitized[str(key)] = "******" if any(part in normalized_key for part in _SENSITIVE_PARTS) else _sanitize(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    return value


def _dataset_summary(dataset) -> dict:
    encoded = json.dumps(dataset if dataset is not None else [], ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "entries": len(dataset) if isinstance(dataset, list) else 0,
    }


def _trim_reports(tenant: Tenant) -> None:
    stale_ids = list(
        GenericResource.objects.filter(
            tenant=tenant,
            resource_type="rag_eval_runs",
            deleted_at__isnull=True,
        )
        .order_by("-created_at", "-id")
        .values_list("id", flat=True)[MAX_REPORTS_PER_TENANT:]
    )
    if stale_ids:
        GenericResource.objects.filter(id__in=stale_ids).delete()


def save_evaluation_report(
    *,
    tenant: Tenant,
    evaluation_type: str,
    evaluator: str,
    verified: bool,
    dataset,
    result: dict,
    configuration: dict | None = None,
) -> dict:
    """Persist one completed or unverified run and return public metadata."""
    item = GenericResource.objects.create(
        tenant=tenant,
        resource_type="rag_eval_runs",
        name=f"{evaluation_type} evaluation",
        status="verified" if verified else "unverified",
        data={},
    )
    created_at = item.created_at or timezone.now()
    metadata = {
        "run_id": item.id,
        "evaluation_type": evaluation_type,
        "evaluator": evaluator,
        "verified": bool(verified),
        "dataset": _dataset_summary(dataset),
        "provenance": {
            "git_commit": _git_commit(),
            "created_at": created_at.isoformat(),
            "configuration": _sanitize(configuration or {}),
        },
        "report_url": reverse("rag-eval-report", kwargs={"run_id": item.id}),
    }
    item.data = {**metadata, "result": _sanitize(result)}
    item.save(update_fields=["data", "updated_at"])
    _trim_reports(tenant)
    return metadata


def get_evaluation_report(tenant: Tenant, run_id: str) -> dict | None:
    item = GenericResource.objects.filter(
        id=run_id,
        tenant=tenant,
        resource_type="rag_eval_runs",
        deleted_at__isnull=True,
    ).first()
    return dict(item.data or {}) if item else None


def recent_evaluation_reports(tenant: Tenant) -> list[dict]:
    items = GenericResource.objects.filter(
        tenant=tenant,
        resource_type="rag_eval_runs",
        deleted_at__isnull=True,
    ).order_by("-created_at", "-id")[:MAX_REPORTS_PER_TENANT]
    return [
        {
            key: item.data.get(key)
            for key in ("run_id", "evaluation_type", "evaluator", "verified", "dataset", "provenance", "report_url")
        }
        for item in items
    ]
