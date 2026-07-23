import hashlib
import math
from dataclasses import dataclass
from typing import Any

from personal_knowledge_base.models import SemanticChunkCache


SEMANTIC_ALGORITHM_VERSION = "semantic-boundaries-v1"


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
        (start, index, "\n".join(unit.content for unit in units[index:min(index + window_size, end)]))
        for index in range(start, end, window_size)
    ]


def _validate_vectors(vectors: Any, expected_count: int) -> list[list[float]]:
    if not isinstance(vectors, (list, tuple)) or len(vectors) != expected_count:
        raise SemanticSplitError("invalid_vector_count")

    normalized = []
    dimension = None
    for vector in vectors:
        if not isinstance(vector, (list, tuple)) or not vector:
            raise SemanticSplitError("invalid_vector_dimension")
        try:
            converted = [float(value) for value in vector]
        except (TypeError, ValueError) as exc:
            raise SemanticSplitError("invalid_vector_dimension") from exc
        if not all(math.isfinite(value) for value in converted):
            raise SemanticSplitError("invalid_vector_non_finite")
        if dimension is None:
            dimension = len(converted)
        elif len(converted) != dimension:
            raise SemanticSplitError("invalid_vector_dimension")
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


def _cache_lookup(*, content_hash: str, model_signature: str, window_size: int, percentile: float, inputs: list[str]):
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
    return _validate_vectors(cached.vectors, len(inputs))


def _cache_store(*, content_hash: str, model_signature: str, window_size: int, percentile: float, inputs: list[str], vectors: list[list[float]]):
    try:
        SemanticChunkCache.objects.create(
            content_hash=content_hash,
            model_signature=model_signature,
            algorithm_version=SEMANTIC_ALGORITHM_VERSION,
            window_size=window_size,
            percentile=percentile,
            window_inputs=inputs,
            vectors=vectors,
        )
    except Exception as exc:
        raise SemanticSplitError("cache_write_error") from exc


def split_semantic_units(units, config, *, embed, model_signature) -> SemanticSplitResult:
    """Select atomic-unit split boundaries using cached sentence-window embeddings."""
    if not callable(embed):
        raise SemanticSplitError("missing_embedding_callable")
    if not str(model_signature or "").strip():
        raise SemanticSplitError("missing_model_signature")

    window_size = config.semantic_window_size
    percentile = config.semantic_breakpoint_percentile
    windows = _windows(units, window_size)
    inputs = [text for _segment_start, _start, text in windows]
    content_hash = _content_hash(units)
    vectors = _cache_lookup(
        content_hash=content_hash,
        model_signature=model_signature,
        window_size=window_size,
        percentile=percentile,
        inputs=inputs,
    )
    cache_hit = vectors is not None
    if vectors is None:
        try:
            vectors = _validate_vectors(embed(inputs), len(inputs))
        except SemanticSplitError:
            raise
        except TimeoutError as exc:
            raise SemanticSplitError("embedding_timeout") from exc
        except Exception as exc:
            raise SemanticSplitError("embedding_error") from exc
        _cache_store(
            content_hash=content_hash,
            model_signature=model_signature,
            window_size=window_size,
            percentile=percentile,
            inputs=inputs,
            vectors=vectors,
        )

    distances = []
    for index in range(1, len(windows)):
        previous_segment, _previous_start, _previous_text = windows[index - 1]
        segment, start, _text = windows[index]
        if previous_segment == segment:
            distances.append((start, _cosine_distance(vectors[index - 1], vectors[index])))

    threshold = _percentile([distance for _start, distance in distances], percentile) if distances else None
    hard_boundaries = {index for index, unit in enumerate(units) if index and unit.boundary_before}
    boundaries = hard_boundaries | {
        start for start, distance in distances if threshold is not None and distance >= threshold
    }
    return SemanticSplitResult(
        boundary_indices=sorted(boundaries),
        window_size=window_size,
        percentile=percentile,
        cache_hit=cache_hit,
    )
