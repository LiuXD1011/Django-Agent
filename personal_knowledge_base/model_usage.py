from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Iterable

from django.db.models import Count, Sum
from django.db.models.functions import TruncDay, TruncHour, TruncMinute
from django.utils import timezone

from .model_types import frontend_model_group, model_type_aliases
from .models import ModelUsage, Tenant


CACHE_MODEL_GROUPS = {
    "chat": "对话",
    "embedding": "Embedding",
    "rerank": "ReRank",
    "vlm": "视觉",
}
CACHE_MODEL_GROUP_ORDER = ("chat", "embedding", "rerank", "vlm")
INTERNAL_TEXT_MODEL_TYPES = {"summary", "title", "question", "extract"}


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
    if _skip_model_usage_record(model_type):
        return
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
    cache_qs = _frontend_model_usage_qs(qs)
    cache_totals = cache_qs.aggregate(
        prompt_tokens=Sum("prompt_tokens"),
        total_tokens=Sum("total_tokens"),
        cached_tokens=Sum("cached_tokens"),
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
        "cache": {
            "prompt_rate": _rate(cache_totals["cached_tokens"] or 0, cache_totals["prompt_tokens"] or 0),
            "total_rate": _rate(cache_totals["cached_tokens"] or 0, cache_totals["total_tokens"] or 0),
            "prompt_tokens": cache_totals["prompt_tokens"] or 0,
            "total_tokens": cache_totals["total_tokens"] or 0,
            "cached_tokens": cache_totals["cached_tokens"] or 0,
        },
        "by_type": _group(qs, "model_type"),
        "by_model": _group(qs, "model_id", extra=["model_name", "provider", "model_type"]),
        "by_scenario": _group(qs, "scenario"),
        "daily": _daily(qs, days),
        "cache_series": _cache_series(qs, days, params.get("granularity")),
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
                "cache_hit_rate": _rate(row.get("cached_tokens") or 0, row.get("prompt_tokens") or 0),
                "cache_total_rate": _rate(row.get("cached_tokens") or 0, row.get("total_tokens") or 0),
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


def _rate(numerator: int, denominator: int) -> float:
    if not denominator:
        return 0
    return round(float(numerator) / float(denominator), 4)


def _granularity(value) -> str:
    text = str(value or "day").lower().strip()
    return text if text in {"day", "hour", "15m"} else "day"


def _bucket_start(dt, granularity: str):
    local = timezone.localtime(dt)
    if granularity == "day":
        return timezone.make_aware(datetime.combine(local.date(), time.min), timezone.get_current_timezone())
    if granularity == "hour":
        return local.replace(minute=0, second=0, microsecond=0)
    minute = (local.minute // 15) * 15
    return local.replace(minute=minute, second=0, microsecond=0)


def _bucket_expr(granularity: str):
    if granularity == "day":
        return TruncDay("created_at", tzinfo=timezone.get_current_timezone())
    if granularity == "hour":
        return TruncHour("created_at", tzinfo=timezone.get_current_timezone())
    return TruncMinute("created_at", tzinfo=timezone.get_current_timezone())


def _bucket_label(dt, granularity: str) -> str:
    if granularity == "day":
        return timezone.localtime(dt).strftime("%m-%d")
    return timezone.localtime(dt).strftime("%m-%d %H:%M")


def _bucket_step(granularity: str) -> timedelta:
    if granularity == "day":
        return timedelta(days=1)
    if granularity == "hour":
        return timedelta(hours=1)
    return timedelta(minutes=15)


def _cache_series(qs, days: int, granularity_value) -> dict:
    granularity = _granularity(granularity_value)
    qs = _frontend_model_usage_qs(qs)
    now = timezone.now()
    if granularity == "day":
        start = timezone.make_aware(
            datetime.combine((timezone.localdate() - timedelta(days=days - 1)), time.min),
            timezone.get_current_timezone(),
        )
    else:
        start = _bucket_start(now - timedelta(days=days), granularity)
    end = _bucket_start(now, granularity)
    step = _bucket_step(granularity)

    buckets = []
    cursor = start
    while cursor <= end:
        buckets.append({"bucket": cursor.isoformat(), "label": _bucket_label(cursor, granularity)})
        cursor += step

    group_totals = {}
    for row in qs.values("model_type").annotate(
        prompt_tokens=Sum("prompt_tokens"),
        cached_tokens=Sum("cached_tokens"),
        total_tokens=Sum("total_tokens"),
    ):
        group = _cache_model_group(row.get("model_type"))
        if not group:
            continue
        current = group_totals.setdefault(group, {"prompt_tokens": 0, "cached_tokens": 0, "total_tokens": 0})
        current["prompt_tokens"] += row.get("prompt_tokens") or 0
        current["cached_tokens"] += row.get("cached_tokens") or 0
        current["total_tokens"] += row.get("total_tokens") or 0

    raw_bucket_rows = (
        qs.annotate(bucket=_bucket_expr(granularity))
        .values("bucket", "model_type")
        .annotate(
            prompt_tokens=Sum("prompt_tokens"),
            cached_tokens=Sum("cached_tokens"),
            total_tokens=Sum("total_tokens"),
        )
    )
    row_map = {}
    for row in raw_bucket_rows:
        if not row.get("bucket"):
            continue
        group = _cache_model_group(row.get("model_type"))
        if not group:
            continue
        key = (_series_key(group), _bucket_start(row["bucket"], granularity).isoformat())
        current = row_map.setdefault(key, {"prompt_tokens": 0, "cached_tokens": 0, "total_tokens": 0})
        current["prompt_tokens"] += row.get("prompt_tokens") or 0
        current["cached_tokens"] += row.get("cached_tokens") or 0
        current["total_tokens"] += row.get("total_tokens") or 0

    models = []
    for group in CACHE_MODEL_GROUP_ORDER:
        totals = group_totals.get(group)
        if not totals or not totals.get("prompt_tokens"):
            continue
        model_key = _series_key(group)
        points = []
        for bucket in buckets:
            row = row_map.get((model_key, bucket["bucket"]), {})
            prompt_tokens = row.get("prompt_tokens") or 0
            cached_tokens = row.get("cached_tokens") or 0
            total_tokens = row.get("total_tokens") or 0
            points.append({
                "bucket": bucket["bucket"],
                "label": bucket["label"],
                "prompt_tokens": prompt_tokens,
                "cached_tokens": cached_tokens,
                "total_tokens": total_tokens,
                "cache_hit_rate": _rate(cached_tokens, prompt_tokens),
                "cache_total_rate": _rate(cached_tokens, total_tokens),
            })
        prompt_tokens = totals.get("prompt_tokens") or 0
        cached_tokens = totals.get("cached_tokens") or 0
        total_tokens = totals.get("total_tokens") or 0
        models.append({
            "model_key": model_key,
            "model_id": model_key,
            "model_name": CACHE_MODEL_GROUPS[group],
            "provider": "",
            "model_type": group,
            "model_group": group,
            "prompt_tokens": prompt_tokens,
            "cached_tokens": cached_tokens,
            "total_tokens": total_tokens,
            "cache_hit_rate": _rate(cached_tokens, prompt_tokens),
            "cache_total_rate": _rate(cached_tokens, total_tokens),
            "points": points,
        })

    return {"granularity": granularity, "buckets": buckets, "models": models}


def _series_key(model_group: str) -> str:
    return f"group:{model_group or 'unknown'}"


def _frontend_model_usage_qs(qs):
    allowed_model_types = []
    for model_type in qs.values_list("model_type", flat=True).distinct():
        group = _cache_model_group(model_type)
        if group:
            allowed_model_types.append(model_type)
    return qs.filter(model_type__in=allowed_model_types)


def _cache_model_group(model_type) -> str:
    raw = str(model_type or "").strip()
    if raw.lower() in INTERNAL_TEXT_MODEL_TYPES:
        return ""
    group = frontend_model_group(raw)
    return group if group in CACHE_MODEL_GROUPS else ""


def _skip_model_usage_record(model_type) -> bool:
    return str(model_type or "").strip().lower() in INTERNAL_TEXT_MODEL_TYPES
