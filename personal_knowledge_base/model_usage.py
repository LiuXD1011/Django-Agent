from __future__ import annotations

from datetime import timedelta
from typing import Iterable

from django.db.models import Count, Sum
from django.utils import timezone

from .model_types import model_type_aliases
from .models import ModelUsage, Tenant


def estimate_tokens(value) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return max(1, len(value) // 4) if value else 0
    if isinstance(value, dict):
        return estimate_tokens(" ".join(str(v) for v in value.values()))
    if isinstance(value, Iterable):
        return sum(estimate_tokens(item) for item in value)
    return estimate_tokens(str(value))


def usage_from_response(data: dict | None) -> dict:
    usage = (data or {}).get("usage") or {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    total = int(usage.get("total_tokens") or prompt + completion)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cached_tokens": int(prompt_details.get("cached_tokens") or usage.get("cached_tokens") or 0),
    }


def record_model_usage(
    tenant: Tenant | None,
    *,
    model_id: str = "",
    model_name: str = "",
    model_type: str = "",
    provider: str = "",
    scenario: str = "",
    success: bool = True,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    cached_tokens: int = 0,
    duration_ms: int = 0,
    error_message: str = "",
    metadata: dict | None = None,
):
    try:
        total_tokens = int(total_tokens or prompt_tokens + completion_tokens)
        ModelUsage.objects.create(
            tenant=tenant,
            model_id=model_id or "",
            model_name=model_name or "",
            model_type=model_type or "",
            provider=provider or "",
            scenario=scenario or model_type or "",
            success=bool(success),
            prompt_tokens=max(int(prompt_tokens or 0), 0),
            completion_tokens=max(int(completion_tokens or 0), 0),
            total_tokens=max(total_tokens, 0),
            cached_tokens=max(int(cached_tokens or 0), 0),
            duration_ms=max(int(duration_ms or 0), 0),
            error_message=(error_message or "")[:500],
            metadata=metadata or {},
        )
    except Exception:
        pass


def model_usage_summary(tenant: Tenant, params: dict) -> dict:
    days = _range_days(params.get("range") or params.get("days"))
    since = timezone.now() - timedelta(days=days)
    qs = ModelUsage.objects.filter(tenant=tenant, created_at__gte=since, deleted_at__isnull=True)
    model_type = params.get("model_type") or params.get("type")
    model_id = params.get("model_id")
    if model_type:
        qs = qs.filter(model_type__in=model_type_aliases(model_type))
    if model_id:
        qs = qs.filter(model_id=model_id)

    totals = qs.aggregate(
        calls=Sum("request_count"),
        records=Count("id"),
        prompt_tokens=Sum("prompt_tokens"),
        completion_tokens=Sum("completion_tokens"),
        total_tokens=Sum("total_tokens"),
        cached_tokens=Sum("cached_tokens"),
        duration_ms=Sum("duration_ms"),
    )
    success_calls = qs.filter(success=True).aggregate(calls=Sum("request_count"))["calls"] or 0
    failed_calls = qs.filter(success=False).aggregate(calls=Sum("request_count"))["calls"] or 0
    total_calls = totals["calls"] or 0

    return {
        "range_days": days,
        "since": since.isoformat(),
        "total": {
            "calls": total_calls,
            "records": totals["records"] or 0,
            "success": success_calls,
            "failed": failed_calls,
            "success_rate": round(success_calls / total_calls, 4) if total_calls else 0,
            "prompt_tokens": totals["prompt_tokens"] or 0,
            "completion_tokens": totals["completion_tokens"] or 0,
            "total_tokens": totals["total_tokens"] or 0,
            "cached_tokens": totals["cached_tokens"] or 0,
            "duration_ms": totals["duration_ms"] or 0,
        },
        "by_type": _group(qs, "model_type"),
        "by_model": _group(qs, "model_id", extra=["model_name", "provider", "model_type"]),
        "by_scenario": _group(qs, "scenario"),
        "daily": _daily(qs, days),
    }


def _range_days(value) -> int:
    text = str(value or "7").lower().strip()
    if text.endswith("d"):
        text = text[:-1]
    try:
        days = int(text)
    except Exception:
        days = 7
    return min(max(days, 1), 90)


def _group(qs, field: str, extra: list[str] | None = None) -> list[dict]:
    values = [field, *(extra or [])]
    rows = (
        qs.values(*values)
        .annotate(
            calls=Sum("request_count"),
            prompt_tokens=Sum("prompt_tokens"),
            completion_tokens=Sum("completion_tokens"),
            total_tokens=Sum("total_tokens"),
            cached_tokens=Sum("cached_tokens"),
            failed=Count("id", filter=None),
        )
        .order_by("-total_tokens", "-calls")[:20]
    )
    result = []
    for row in rows:
        item = {key: row.get(key) for key in values}
        item.update(
            {
                "calls": row.get("calls") or 0,
                "prompt_tokens": row.get("prompt_tokens") or 0,
                "completion_tokens": row.get("completion_tokens") or 0,
                "total_tokens": row.get("total_tokens") or 0,
                "cached_tokens": row.get("cached_tokens") or 0,
            }
        )
        result.append(item)
    return result


def _daily(qs, days: int) -> list[dict]:
    today = timezone.localdate()
    rows = {}
    for item in qs.values("created_at", "request_count", "total_tokens"):
        day = timezone.localtime(item["created_at"]).date().isoformat()
        bucket = rows.setdefault(day, {"date": day, "calls": 0, "total_tokens": 0})
        bucket["calls"] += item["request_count"] or 0
        bucket["total_tokens"] += item["total_tokens"] or 0
    return [
        rows.get((today - timedelta(days=offset)).isoformat(), {"date": (today - timedelta(days=offset)).isoformat(), "calls": 0, "total_tokens": 0})
        for offset in range(days - 1, -1, -1)
    ]
