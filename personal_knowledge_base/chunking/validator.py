from collections.abc import Callable

from .types import ChunkDraft


class ChunkValidationError(ValueError):
    def __init__(self, issues: list[str], fallback_chain: list[dict] | None = None):
        self.issues = issues
        self.fallback_chain = list(fallback_chain or [])
        super().__init__("; ".join(issues))


def minimum_chunk_size(target_size: int) -> int:
    return max(8, min(64, target_size // 4))


def validate_drafts(
    drafts: list[ChunkDraft],
    source: str,
    *,
    target_size: int,
    token_counter: Callable[[str], int],
    token_limit: int = 0,
) -> list[str]:
    issues = []
    if not drafts:
        return ["empty_output"]

    previous_start = -1
    intervals = []
    for index, draft in enumerate(drafts):
        if not draft.content.strip():
            issues.append(f"empty_chunk:{index}")
        if not 0 <= draft.start_at < draft.end_at <= len(source):
            issues.append(f"invalid_source_range:{index}")
            continue
        if draft.start_at < previous_start:
            issues.append(f"unordered_source_range:{index}")
        previous_start = draft.start_at
        if source[draft.start_at:draft.end_at] != draft.content:
            issues.append(f"source_range_mismatch:{index}")
        if token_limit and token_counter(draft.content) > token_limit:
            issues.append(f"token_limit_exceeded:{index}")
        intervals.append((draft.start_at, draft.end_at))

    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    cursor = 0
    for start, end in merged:
        if any(not value.isspace() for value in source[cursor:start]):
            issues.append("incomplete_source_coverage")
            break
        cursor = max(cursor, end)
    else:
        if any(not value.isspace() for value in source[cursor:]):
            issues.append("incomplete_source_coverage")

    tiny_threshold = minimum_chunk_size(target_size)
    tiny_count = sum(len(draft.content.strip()) < tiny_threshold for draft in drafts)
    if len(drafts) >= 4 and tiny_count / len(drafts) > 0.5:
        issues.append("excessive_tiny_chunks")
    return list(dict.fromkeys(issues))


def validate_hierarchy(parents: list[ChunkDraft], children: list[ChunkDraft]) -> list[str]:
    issues = []
    if not parents:
        return issues
    for index, child in enumerate(children):
        parent_index = child.context_parent_index
        if parent_index is None or not 0 <= parent_index < len(parents):
            issues.append(f"invalid_parent_index:{index}")
            continue
        parent = parents[parent_index]
        if child.start_at < parent.start_at or child.end_at > parent.end_at:
            issues.append(f"child_outside_parent:{index}")
    return issues
