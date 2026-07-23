import hashlib
import math
from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any

from personal_knowledge_base.models import SemanticChunkCache

from .validator import minimum_chunk_size


SEMANTIC_ALGORITHM_VERSION = "semantic-boundaries-v2"


class SemanticSplitError(ValueError):
    pass


@dataclass(slots=True)
class SemanticSplitResult:
    boundary_indices: list[int]
    window_size: int
    percentile: float
    cache_hit: bool = False


def _content_hash(units) -> str:
    value = "\x1e".join(
        f"{int(bool(unit.boundary_before))}\x1f{unit.content}"
        for unit in units
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _windows(units, window_size: int) -> list[tuple[int, int, str]]:
    windows = []
    segment_start = 0
    for index, unit in enumerate(units):
        if index and unit.boundary_before:
            windows.extend(_segment_windows(units, segment_start, index, window_size))
            segment_start = index
    windows.extend(_segment_windows(units, segment_start, len(units), window_size))
    return windows


def _segment_windows(units, start: int, end: int, window_size: int) -> list[tuple[int, int, str]]:
    return [
        (
            start,
            index,
            "\n".join(unit.content for unit in units[index:min(index + window_size, end)]),
        )
        for index in range(start, end)
    ]


def _expected_dimension(model_signature: str) -> int:
    try:
        dimension = int(str(model_signature).rsplit(":", 1)[1])
    except (IndexError, TypeError, ValueError) as exc:
        raise SemanticSplitError("invalid_model_signature_dimension") from exc
    if dimension <= 0:
        raise SemanticSplitError("invalid_model_signature_dimension")
    return dimension


def _validate_vectors(vectors: Any, expected_count: int, expected_dimension: int) -> list[list[float]]:
    if not isinstance(vectors, (list, tuple)) or len(vectors) != expected_count:
        raise SemanticSplitError("invalid_vector_count")

    normalized = []
    for vector in vectors:
        if not isinstance(vector, (list, tuple)) or not vector:
            raise SemanticSplitError("invalid_vector_dimension")
        try:
            converted = [float(value) for value in vector]
        except (TypeError, ValueError) as exc:
            raise SemanticSplitError("invalid_vector_dimension") from exc
        if len(converted) != expected_dimension:
            raise SemanticSplitError("invalid_vector_dimension")
        if not all(math.isfinite(value) for value in converted):
            raise SemanticSplitError("invalid_vector_non_finite")
        if not math.sqrt(sum(value * value for value in converted)):
            raise SemanticSplitError("invalid_vector_zero_norm")
        normalized.append(converted)
    return normalized


def _cosine_distance(left: list[float], right: list[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        raise SemanticSplitError("invalid_vector_zero_norm")
    similarity = sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)
    return 1.0 - max(-1.0, min(1.0, similarity))


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _cache_lookup(
    *,
    content_hash: str,
    model_signature: str,
    window_size: int,
    percentile: float,
    inputs: list[str],
    expected_dimension: int,
):
    try:
        cached = SemanticChunkCache.objects.filter(
            content_hash=content_hash,
            model_signature=model_signature,
            algorithm_version=SEMANTIC_ALGORITHM_VERSION,
            window_size=window_size,
            percentile=percentile,
        ).first()
    except Exception as exc:
        raise SemanticSplitError("cache_read_error") from exc
    if cached is None:
        return None
    if cached.window_inputs != inputs:
        raise SemanticSplitError("cache_input_mismatch")
    return _validate_vectors(cached.vectors, len(inputs), expected_dimension)


def _cache_store(
    *,
    content_hash: str,
    model_signature: str,
    window_size: int,
    percentile: float,
    inputs: list[str],
    vectors: list[list[float]],
    expected_dimension: int,
) -> tuple[list[list[float]], bool]:
    try:
        cached, created = SemanticChunkCache.objects.get_or_create(
            content_hash=content_hash,
            model_signature=model_signature,
            algorithm_version=SEMANTIC_ALGORITHM_VERSION,
            window_size=window_size,
            percentile=percentile,
            defaults={"window_inputs": inputs, "vectors": vectors},
        )
    except Exception as exc:
        raise SemanticSplitError("cache_write_error") from exc
    if cached.window_inputs != inputs:
        raise SemanticSplitError("cache_input_mismatch")
    return _validate_vectors(cached.vectors, len(inputs), expected_dimension), not created


def _memory_cache_key(
    *,
    content_hash: str,
    model_signature: str,
    window_size: int,
    percentile: float,
) -> tuple:
    return (
        content_hash,
        model_signature,
        SEMANTIC_ALGORITHM_VERSION,
        window_size,
        percentile,
    )


def _memory_cache_lookup(
    cache: MutableMapping,
    *,
    key: tuple,
    inputs: list[str],
    expected_dimension: int,
):
    cached = cache.get(key)
    if cached is None:
        return None
    if cached["window_inputs"] != inputs:
        raise SemanticSplitError("cache_input_mismatch")
    return _validate_vectors(cached["vectors"], len(inputs), expected_dimension)


def _memory_cache_store(
    cache: MutableMapping,
    *,
    key: tuple,
    inputs: list[str],
    vectors: list[list[float]],
    expected_dimension: int,
) -> list[list[float]]:
    validated = _validate_vectors(vectors, len(inputs), expected_dimension)
    cache[key] = {
        "window_inputs": list(inputs),
        "vectors": [list(vector) for vector in validated],
    }
    return validated


def _unit_span_size(units, start: int, end: int) -> int:
    return sum(len(unit.content.strip()) for unit in units[start:end])


def _consolidate_boundaries(units, candidates: set[int], target_size: int) -> list[int]:
    hard_boundaries = sorted(
        index for index, unit in enumerate(units) if index and unit.boundary_before
    )
    threshold = minimum_chunk_size(target_size)
    retained = set(hard_boundaries)
    segment_starts = [0, *hard_boundaries]
    segment_ends = [*hard_boundaries, len(units)]

    for segment_start, segment_end in zip(segment_starts, segment_ends):
        semantic_boundaries = sorted(
            index for index in candidates if segment_start < index < segment_end
        )
        segment_retained = []
        chunk_start = segment_start
        for boundary in semantic_boundaries:
            if _unit_span_size(units, chunk_start, boundary) >= threshold:
                segment_retained.append(boundary)
                chunk_start = boundary
        if segment_retained and _unit_span_size(units, segment_retained[-1], segment_end) < threshold:
            segment_retained.pop()
        retained.update(segment_retained)
    return sorted(retained)


def split_semantic_units(
    units,
    config,
    *,
    embed,
    model_signature,
    semantic_cache: MutableMapping | None = None,
) -> SemanticSplitResult:
    """Select atomic-unit split boundaries using cached sentence-window embeddings."""
    if not callable(embed):
        raise SemanticSplitError("missing_embedding_callable")
    if not str(model_signature or "").strip():
        raise SemanticSplitError("missing_model_signature")

    expected_dimension = _expected_dimension(model_signature)
    window_size = config.semantic_window_size
    percentile = config.semantic_breakpoint_percentile
    windows = _windows(units, window_size)
    inputs = [text for _segment_start, _start, text in windows]
    content_hash = _content_hash(units)
    cache_key = _memory_cache_key(
        content_hash=content_hash,
        model_signature=model_signature,
        window_size=window_size,
        percentile=percentile,
    )
    if semantic_cache is None:
        vectors = _cache_lookup(
            content_hash=content_hash,
            model_signature=model_signature,
            window_size=window_size,
            percentile=percentile,
            inputs=inputs,
            expected_dimension=expected_dimension,
        )
    else:
        vectors = _memory_cache_lookup(
            semantic_cache,
            key=cache_key,
            inputs=inputs,
            expected_dimension=expected_dimension,
        )
    cache_hit = vectors is not None
    if vectors is None:
        try:
            vectors = _validate_vectors(embed(inputs), len(inputs), expected_dimension)
        except SemanticSplitError:
            raise
        except TimeoutError as exc:
            raise SemanticSplitError("embedding_timeout") from exc
        except Exception as exc:
            raise SemanticSplitError("embedding_error") from exc
        if semantic_cache is None:
            vectors, concurrent_cache_hit = _cache_store(
                content_hash=content_hash,
                model_signature=model_signature,
                window_size=window_size,
                percentile=percentile,
                inputs=inputs,
                vectors=vectors,
                expected_dimension=expected_dimension,
            )
            cache_hit = concurrent_cache_hit
        else:
            vectors = _memory_cache_store(
                semantic_cache,
                key=cache_key,
                inputs=inputs,
                vectors=vectors,
                expected_dimension=expected_dimension,
            )

    distances = []
    for index in range(1, len(windows)):
        previous_segment, _previous_start, _previous_text = windows[index - 1]
        segment, start, _text = windows[index]
        if previous_segment == segment:
            distances.append((start, _cosine_distance(vectors[index - 1], vectors[index])))

    threshold = _percentile([distance for _start, distance in distances], percentile) if distances else None
    candidates = {
        start for start, distance in distances if threshold is not None and distance >= threshold
    }
    target_size = config.parent_chunk_size if config.enable_parent_child else config.chunk_size
    boundaries = _consolidate_boundaries(units, candidates, target_size)
    return SemanticSplitResult(
        boundary_indices=boundaries,
        window_size=window_size,
        percentile=percentile,
        cache_hit=cache_hit,
    )
