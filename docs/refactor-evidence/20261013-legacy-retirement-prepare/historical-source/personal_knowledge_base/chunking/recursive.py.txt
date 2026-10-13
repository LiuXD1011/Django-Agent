import re
from collections.abc import Callable, Iterable

from .types import ChunkDraft


_PROTECTED_PATTERNS = (
    re.compile(r"```[^\n]*\n.*?```", re.DOTALL),
    re.compile(r"~~~[^\n]*\n.*?~~~", re.DOTALL),
    re.compile(r"\$\$.*?\$\$", re.DOTALL),
    re.compile(r"(?<!\$)\$(?!\$)(?:\\.|[^\n$])+?\$(?!\$)"),
    re.compile(r"!?\[[^\]\n]*\]\([^\n)]+\)"),
)
_BOUNDARY_PATTERNS = (
    re.compile(r"\n\s*\n"),
    re.compile(r"\n"),
    re.compile(r"(?<=[.!?。！？；;])\s+"),
    re.compile(r"\s+"),
)


class UnsplittableTokenLimit(ValueError):
    pass


def protected_ranges(text: str, *, offset: int = 0) -> list[tuple[int, int]]:
    ranges = [
        (offset + match.start(), offset + match.end())
        for pattern in _PROTECTED_PATTERNS
        for match in pattern.finditer(text)
    ]
    return _merge_ranges(ranges)


def _merge_ranges(ranges: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged = []
    for start, end in sorted(ranges):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _containing_range(position: int, ranges: list[tuple[int, int]]) -> tuple[int, int] | None:
    return next((item for item in ranges if item[0] < position < item[1]), None)


def _preferred_boundary(source: str, start: int, desired_end: int) -> int:
    minimum = start + max(1, (desired_end - start) // 2)
    for pattern in _BOUNDARY_PATTERNS:
        candidates = [match.end() for match in pattern.finditer(source, minimum, desired_end)]
        if candidates:
            return candidates[-1]
    return desired_end


def _previous_boundary(
    source: str,
    start: int,
    end: int,
    ranges: list[tuple[int, int]],
) -> int:
    for pattern in reversed(_BOUNDARY_PATTERNS):
        for match in reversed(list(pattern.finditer(source, start + 1, end))):
            if not _containing_range(match.start(), ranges):
                return match.start()
    fallback = end - 1
    protected = _containing_range(fallback, ranges)
    return protected[0] if protected else fallback


def _range_ending_at(
    position: int,
    ranges: list[tuple[int, int]],
) -> tuple[int, int] | None:
    return next((item for item in ranges if item[0] < position <= item[1]), None)


def _fit_token_limit(
    source: str,
    start: int,
    end: int,
    ranges: list[tuple[int, int]],
    token_counter: Callable[[str], int],
    token_limit: int,
) -> int:
    while end > start and token_counter(source[start:end]) > token_limit:
        protected = _range_ending_at(end, ranges)
        candidate = protected[0] if protected else _previous_boundary(source, start, end, ranges)
        if candidate <= start:
            raise UnsplittableTokenLimit("protected content exceeds token_limit")
        end = candidate
    if end <= start:
        raise UnsplittableTokenLimit("content exceeds token_limit")
    return end


def split_text_range(
    source: str,
    start: int,
    end: int,
    *,
    chunk_size: int,
    overlap: int,
    context_header: str,
    token_counter: Callable[[str], int],
    token_limit: int = 0,
    extra_protected_ranges: Iterable[tuple[int, int]] = (),
    metadata: dict | None = None,
) -> list[ChunkDraft]:
    ranges = _merge_ranges(
        [
            *protected_ranges(source[start:end], offset=start),
            *[item for item in extra_protected_ranges if item[1] > start and item[0] < end],
        ]
    )
    drafts = []
    cursor, terminal = start, end
    while cursor < terminal:
        desired_end = min(cursor + chunk_size, terminal)
        protected = _containing_range(desired_end, ranges)
        if protected:
            desired_end = min(protected[1], terminal)
        elif desired_end < terminal:
            desired_end = _preferred_boundary(source, cursor, desired_end)
            protected = _containing_range(desired_end, ranges)
            if protected:
                desired_end = min(protected[1], terminal)

        if token_limit:
            desired_end = _fit_token_limit(
                source,
                cursor,
                desired_end,
                ranges,
                token_counter,
                token_limit,
            )
        chunk_start, chunk_end = cursor, desired_end
        if chunk_end <= chunk_start:
            cursor = max(cursor + 1, desired_end)
            continue
        drafts.append(
            ChunkDraft(
                content=source[chunk_start:chunk_end],
                context_header=context_header,
                start_at=chunk_start,
                end_at=chunk_end,
                metadata=dict(metadata or {}),
            )
        )
        if chunk_end >= terminal:
            break
        next_cursor = max(chunk_start + 1, chunk_end - overlap)
        containing = _containing_range(next_cursor, ranges)
        if containing:
            next_cursor = containing[1]
        cursor = next_cursor
    return drafts


def split_recursive_units(
    units,
    *,
    source: str,
    chunk_size: int,
    overlap: int,
    title: str,
    token_counter: Callable[[str], int],
    token_limit: int = 0,
) -> list[ChunkDraft]:
    if not units:
        return []
    groups = []
    for unit in units:
        if groups and getattr(unit, "boundary_before", False):
            groups.append([])
        if not groups:
            groups.append([])
        groups[-1].append(unit)

    drafts = []
    for group in groups:
        start = min(unit.start for unit in group)
        end = max(unit.end for unit in group)
        protected = [
            (unit.start, unit.end)
            for unit in group
            if getattr(unit, "protected", False)
        ]
        group_drafts = split_text_range(
            source,
            start,
            end,
            chunk_size=chunk_size,
            overlap=overlap,
            context_header=title,
            token_counter=token_counter,
            token_limit=token_limit,
            extra_protected_ranges=protected,
            metadata={"strategy": "recursive"},
        )
        for draft in group_drafts:
            draft.metadata["_protected_ranges"] = [
                item
                for item in protected
                if draft.start_at <= item[0] and item[1] <= draft.end_at
            ]
        drafts.extend(group_drafts)
    return drafts
