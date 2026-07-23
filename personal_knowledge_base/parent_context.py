from __future__ import annotations

from dataclasses import dataclass

from .models import Chunk


@dataclass(frozen=True)
class _RenderedSegment:
    rendered_start: int
    rendered_end: int
    source_start: int
    source_end: int
    child_id: str | None = None


def _strategy_for(child: Chunk, parent: Chunk) -> str:
    for metadata in (child.metadata or {}, parent.metadata or {}):
        if metadata.get("selected_strategy"):
            return str(metadata["selected_strategy"])
    diagnostics = (child.knowledge.metadata or {}).get("chunking_diagnostics") or {}
    return str(diagnostics.get("selected_strategy") or "")


def _render_parent(parent: Chunk, siblings: list[Chunk]) -> tuple[str, list[_RenderedSegment], list[str]]:
    raw = parent.content or ""
    parent_start = parent.start_at
    parent_end = parent.end_at if parent.end_at > parent_start else parent_start + len(raw)
    edits = []
    for sibling in siblings:
        start = sibling.start_at - parent_start
        end = sibling.end_at - parent_start
        if start < 0 or end < start or end > len(raw) or sibling.end_at > parent_end:
            continue
        if raw[start:end] != sibling.content:
            edits.append((start, end, sibling.chunk_index, sibling.id, sibling))
    edits.sort(key=lambda item: (item[0], item[1], item[2], item[3]))

    parts: list[str] = []
    segments: list[_RenderedSegment] = []
    applied_ids: list[str] = []
    source_cursor = 0
    rendered_cursor = 0

    def append_segment(text: str, source_start: int, source_end: int, child_id: str | None = None):
        nonlocal rendered_cursor
        if not text:
            return
        parts.append(text)
        segments.append(
            _RenderedSegment(
                rendered_start=rendered_cursor,
                rendered_end=rendered_cursor + len(text),
                source_start=parent_start + source_start,
                source_end=parent_start + source_end,
                child_id=child_id,
            )
        )
        rendered_cursor += len(text)

    for start, end, _chunk_index, child_id, sibling in edits:
        if start > source_cursor:
            append_segment(raw[source_cursor:start], source_cursor, start)
        append_segment(sibling.content, start, end, child_id)
        applied_ids.append(child_id)
        source_cursor = max(source_cursor, end)
    if source_cursor < len(raw):
        append_segment(raw[source_cursor:], source_cursor, len(raw))
    return "".join(parts), segments, applied_ids


def _rendered_span(child: Chunk, segments: list[_RenderedSegment]) -> tuple[int, int]:
    direct = [segment for segment in segments if segment.child_id == child.id]
    if direct:
        return min(segment.rendered_start for segment in direct), max(segment.rendered_end for segment in direct)
    rendered_ranges = []
    for segment in segments:
        overlap_start = max(segment.source_start, child.start_at)
        overlap_end = min(segment.source_end, child.end_at)
        if overlap_end <= overlap_start:
            continue
        if (
            segment.child_id is None
            and segment.rendered_end - segment.rendered_start == segment.source_end - segment.source_start
        ):
            rendered_ranges.append(
                (
                    segment.rendered_start + overlap_start - segment.source_start,
                    segment.rendered_start + overlap_end - segment.source_start,
                )
            )
        else:
            rendered_ranges.append((segment.rendered_start, segment.rendered_end))
    if not rendered_ranges:
        return 0, 0
    return min(start for start, _end in rendered_ranges), max(end for _start, end in rendered_ranges)


def _window_for_evidence(total: int, cap: int, evidence_spans: list[tuple[int, int]]) -> tuple[int, int]:
    cap = max(0, cap)
    if total <= cap:
        return 0, total
    if cap == 0:
        return 0, 0
    visible = [(start, end) for start, end in evidence_spans if end > start]
    if not visible:
        return 0, cap
    union_start = min(start for start, _end in visible)
    union_end = max(end for _start, end in visible)
    if union_end - union_start <= cap:
        start = union_start - (cap - (union_end - union_start)) // 2
    else:
        primary_start, primary_end = visible[0]
        if primary_end - primary_start >= cap:
            start = primary_start
        else:
            start = primary_start - (cap - (primary_end - primary_start)) // 2
    start = min(max(0, start), total - cap)
    return start, start + cap


def _context_window(parent: Chunk, segments: list[_RenderedSegment], start: int, end: int, cap: int, total: int) -> dict:
    visible_segments = [
        segment for segment in segments if segment.rendered_start < end and segment.rendered_end > start
    ]
    source_ranges = []
    for segment in visible_segments:
        if (
            segment.child_id is None
            and segment.rendered_end - segment.rendered_start == segment.source_end - segment.source_start
        ):
            source_ranges.append(
                (
                    segment.source_start + max(start, segment.rendered_start) - segment.rendered_start,
                    segment.source_start + min(end, segment.rendered_end) - segment.rendered_start,
                )
            )
        else:
            source_ranges.append((segment.source_start, segment.source_end))
    source_start = min((item[0] for item in source_ranges), default=parent.start_at)
    source_end = max((item[1] for item in source_ranges), default=parent.start_at)
    return {
        "parent_start_at": parent.start_at,
        "parent_end_at": parent.end_at,
        "source_start_at": source_start,
        "source_end_at": source_end,
        "rendered_start_at": start,
        "rendered_end_at": end,
        "clipped": start > 0 or end < total,
        "max_context_chars": cap,
    }


def _matched_range(child: Chunk, span: tuple[int, int], window_start: int, window_end: int) -> dict:
    rendered_start, rendered_end = span
    visible_start = max(rendered_start, window_start)
    visible_end = min(rendered_end, window_end)
    visible = visible_end > visible_start
    return {
        "child_id": child.id,
        "start_at": child.start_at,
        "end_at": child.end_at,
        "rendered_start_at": rendered_start,
        "rendered_end_at": rendered_end,
        "context_start_at": visible_start - window_start if visible else None,
        "context_end_at": visible_end - window_start if visible else None,
        "visible": visible,
        "clipped": not visible or visible_start > rendered_start or visible_end < rendered_end,
    }


def _fallback(item: dict, child: Chunk, reason: str, cap: int) -> dict:
    row = dict(item)
    cap = max(0, cap)
    visible_length = min(len(child.content), cap)
    row["content"] = child.content[:visible_length]
    row["context_fallback"] = reason
    row["matched_child_ids"] = [child.id]
    row["matched_ranges"] = [
        {
            "child_id": child.id,
            "start_at": child.start_at,
            "end_at": child.end_at,
            "rendered_start_at": 0,
            "rendered_end_at": len(child.content),
            "context_start_at": 0,
            "context_end_at": visible_length if visible_length else None,
            "visible": visible_length > 0,
            "clipped": visible_length < len(child.content),
        }
    ]
    row.setdefault("selected_strategy", _strategy_for(child, child))
    row["context_window"] = {
        "parent_start_at": child.start_at,
        "parent_end_at": child.end_at,
        "source_start_at": child.start_at,
        "source_end_at": child.end_at if visible_length else child.start_at,
        "rendered_start_at": 0,
        "rendered_end_at": visible_length,
        "clipped": visible_length < len(child.content),
        "max_context_chars": cap,
    }
    return row


def resolve_parent_context(results, *, tenant_id, max_context_chars) -> list[dict]:
    """Collapse reranked text children into tenant-scoped, edit-aware parent context."""
    rows = list(results or [])
    cap = max(0, int(max_context_chars))
    candidate_ids = [
        str(item.get("chunk_id") or item.get("id"))
        for item in rows
        if item.get("retrieval_path") == "document"
        and item.get("chunk_type") == "text"
        and not item.get("parent_chunk_id")
        and (item.get("chunk_id") or item.get("id"))
    ]
    children = {
        child.id: child
        for child in Chunk.objects.filter(
            id__in=candidate_ids,
            tenant_id=tenant_id,
            chunk_type="text",
            deleted_at__isnull=True,
        ).select_related("knowledge", "knowledge_base")
    }
    parent_ids = {child.context_parent_id for child in children.values() if child.context_parent_id}
    parents = {
        parent.id: parent
        for parent in Chunk.objects.filter(
            id__in=parent_ids,
            tenant_id=tenant_id,
            deleted_at__isnull=True,
        ).select_related("knowledge")
    }
    siblings_by_parent: dict[str, list[Chunk]] = {}
    if parent_ids:
        siblings = Chunk.objects.filter(
            context_parent_id__in=parent_ids,
            tenant_id=tenant_id,
            chunk_type="text",
            is_enabled=True,
            deleted_at__isnull=True,
        ).order_by("start_at", "end_at", "chunk_index", "id")
        for sibling in siblings:
            siblings_by_parent.setdefault(sibling.context_parent_id, []).append(sibling)

    output: list[dict | None] = []
    groups: dict[str, dict] = {}
    for item in rows:
        if item.get("parent_chunk_id"):
            output.append(item)
            continue
        chunk_id = str(item.get("chunk_id") or item.get("id") or "")
        child = children.get(chunk_id)
        if not child or not child.context_parent_id:
            output.append(item)
            continue
        parent = parents.get(child.context_parent_id)
        if parent is None:
            output.append(_fallback(item, child, "missing_parent", cap))
            continue
        if parent.chunk_type != "parent_text":
            output.append(_fallback(item, child, "invalid_parent_type", cap))
            continue
        if parent.knowledge_id != child.knowledge_id or parent.knowledge_base_id != child.knowledge_base_id:
            output.append(_fallback(item, child, "parent_scope_mismatch", cap))
            continue

        group = groups.get(parent.id)
        if group is None:
            group = {"parent": parent, "base": dict(item), "children": [], "index": len(output)}
            groups[parent.id] = group
            output.append(None)
        if child.id not in {matched.id for matched in group["children"]}:
            group["children"].append(child)
        group["base"]["score"] = max(group["base"].get("score", 0), item.get("score", 0))

    for group in groups.values():
        parent = group["parent"]
        matched_children = group["children"]
        siblings = [
            sibling
            for sibling in siblings_by_parent.get(parent.id, [])
            if sibling.knowledge_id == parent.knowledge_id and sibling.knowledge_base_id == parent.knowledge_base_id
        ]
        rendered, segments, applied_ids = _render_parent(parent, siblings)
        spans = [_rendered_span(child, segments) for child in matched_children]
        window_start, window_end = _window_for_evidence(len(rendered), cap, spans)
        row = group["base"]
        row["content"] = rendered[window_start:window_end]
        row["parent_chunk_id"] = parent.id
        row["matched_child_ids"] = [child.id for child in matched_children]
        row["matched_ranges"] = [
            _matched_range(child, span, window_start, window_end)
            for child, span in zip(matched_children, spans)
        ]
        row["selected_strategy"] = _strategy_for(matched_children[0], parent)
        row["applied_edit_child_ids"] = applied_ids
        row["context_window"] = _context_window(
            parent, segments, window_start, window_end, cap, len(rendered)
        )
        output[group["index"]] = row
    return [item for item in output if item is not None]
