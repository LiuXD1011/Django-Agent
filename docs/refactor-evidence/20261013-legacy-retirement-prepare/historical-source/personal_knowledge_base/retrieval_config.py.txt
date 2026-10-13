"""Tenant-scoped retrieval settings and rank threshold helpers."""

import math


DEFAULT_RETRIEVAL_CONFIG = {
    "embedding_top_k": 10,
    "vector_threshold": 0.15,
    "keyword_threshold": 0.3,
    "rerank_enabled": True,
    "rerank_top_k": 5,
    "rerank_threshold": 0.3,
}


def _bounded_int(value, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(minimum, min(parsed, maximum))


def _bounded_float(value, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return max(0.0, min(parsed, 1.0))


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return default


def normalize_retrieval_config(value) -> dict:
    """Return bounded retrieval settings, filling in the UI's defaults."""
    raw = value if isinstance(value, dict) else {}
    return {
        "embedding_top_k": _bounded_int(raw.get("embedding_top_k"), DEFAULT_RETRIEVAL_CONFIG["embedding_top_k"], 1, 50),
        "vector_threshold": _bounded_float(raw.get("vector_threshold"), DEFAULT_RETRIEVAL_CONFIG["vector_threshold"]),
        "keyword_threshold": _bounded_float(raw.get("keyword_threshold"), DEFAULT_RETRIEVAL_CONFIG["keyword_threshold"]),
        "rerank_enabled": _as_bool(raw.get("rerank_enabled"), DEFAULT_RETRIEVAL_CONFIG["rerank_enabled"]),
        "rerank_top_k": _bounded_int(raw.get("rerank_top_k"), DEFAULT_RETRIEVAL_CONFIG["rerank_top_k"], 1, 50),
        "rerank_threshold": _bounded_float(raw.get("rerank_threshold"), DEFAULT_RETRIEVAL_CONFIG["rerank_threshold"]),
    }


def get_tenant_retrieval_config(tenant) -> dict:
    return normalize_retrieval_config(getattr(tenant, "retrieval_config", None))


def filter_ranked_by_threshold(items, threshold: float) -> list:
    """Keep candidates whose normalized within-stage rank meets ``threshold``.

    Rank 1 receives score 1.0; the last candidate receives 1 / candidate_count.
    A threshold of 0 keeps the full list.
    """
    ranked = list(items or [])
    if not ranked:
        return ranked
    minimum = _bounded_float(threshold, 0.0)
    if minimum <= 0:
        return ranked
    count = len(ranked)
    return [item for rank, item in enumerate(ranked, start=1) if (count - rank + 1) / count >= minimum]
