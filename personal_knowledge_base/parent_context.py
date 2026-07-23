from __future__ import annotations

from dataclasses import dataclass

from django.db.models import F

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


def _has_usable_source_range(child: Chunk, parent: Chunk) -> bool:
    raw = parent.content or ""
    parent_start = parent.start_at
    parent_end = parent.end_at if parent.end_at > parent_start else parent_start + len(raw)
    return bool(
        child.start_at >= parent_start
        and child.end_at > child.start_at
        and child.end_at <= parent_end
        and child.end_at - parent_start <= len(raw)
    )


def _ranges_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def _render_parent(parent: Chunk, siblings: list[Chunk]) -> tuple[str, list[_RenderedSegment], list[str]]:
    raw = parent.content or ""
    parent_start = parent.start_at
    edits = []
    for sibling in siblings:
        if not _has_usable_source_range(sibling, parent):
            continue
        start = sibling.start_at - parent_start
        end = sibling.end_at - parent_start
        if raw[start:end] != sibling.content:
            updated = sibling.updated_at.timestamp() if sibling.updated_at else 0.0
            edits.append((start, end, sibling.chunk_index, sibling.id, updated, sibling))

    # Conflict selection is against immutable parent offsets. The newest edited
    # child wins; equal timestamps use stable chunk/range/id ordering.
    edits.sort(key=lambda item: (-item[4], item[2], item[0], item[1], item[3]))
    accepted = []
    accepted_ranges: list[tuple[int, int]] = []
    for edit in edits:
        source_range = (edit[0], edit[1])
        if any(_ranges_overlap(source_range, other) for other in accepted_ranges):
            continue
        accepted.append(edit)
        accepted_ranges.append(source_range)
    accepted.sort(key=lambda item: (item[0], item[1], item[2], item[3]))

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

    for start, end, _chunk_index, child_id, _updated, sibling in accepted:
        if start > source_cursor:
            append_segment(raw[source_cursor:start], source_cursor, start)
        append_segment(sibling.content, start, end, child_id)
        applied_ids.append(child_id)
        source_cursor = end
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
    parent_end = parent.end_at if parent.end_at > parent.start_at else parent.start_at + len(parent.content or "")
    clipped = start > 0 or end < total
    return {
        "parent_start_at": parent.start_at,
        "parent_end_at": parent_end,
        "source_start_at": source_start,
        "source_end_at": source_end,
        "rendered_start_at": start,
        "rendered_end_at": end,
        "clipped": clipped,
        "clip_reason": "max_context_chars" if clipped else "",
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
    content = str(item.get("content", child.content) or "")
    visible_length = min(len(content), cap)
    row["content"] = content[:visible_length]
    row.pop("parent_chunk_id", None)
    row["context_fallback"] = reason
    row["context_content_source"] = "item_content"
    row["matched_child_ids"] = [child.id]
    row["matched_ranges"] = [
        {
            "child_id": child.id,
            "start_at": child.start_at,
            "end_at": child.end_at,
            "rendered_start_at": 0,
            "rendered_end_at": len(content),
            "context_start_at": 0,
            "context_end_at": visible_length if visible_length else None,
            "visible": visible_length > 0,
            "clipped": visible_length < len(content),
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
        "clipped": visible_length < len(content),
        "clip_reason": "max_context_chars" if visible_length < len(content) else "",
        "max_context_chars": cap,
    }
    return row


def _number(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _effective_score(item: dict) -> float:
    rerank_score = _number(item.get("rerank_score"))
    if rerank_score is not None:
        return rerank_score
    return _number(item.get("score")) or 0.0


def _best_rank(item: dict) -> int:
    ranks = []
    for key in ("rerank_rank", "keyword_rank", "vector_rank"):
        try:
            if item.get(key) is not None:
                ranks.append(int(item[key]))
        except (TypeError, ValueError):
            continue
    return min(ranks, default=10**9)


def _record_sort_key(record: dict) -> tuple:
    item = record["item"]
    child = record.get("child")
    return (
        -_effective_score(item),
        -(_number(item.get("score")) or 0.0),
        record["index"],
        _best_rank(item),
        getattr(child, "chunk_index", 10**9),
        getattr(child, "start_at", 10**9),
        getattr(child, "end_at", 10**9),
        str(item.get("chunk_id") or item.get("id") or ""),
    )


def _result_sort_key(record: dict) -> tuple:
    item = record["row"]
    return (
        -_effective_score(item),
        -(_number(item.get("score")) or 0.0),
        record["index"],
        str(item.get("chunk_id") or item.get("id") or ""),
    )


def _provenance(record: dict) -> dict:
    item = record["item"]
    child = record["child"]
    return {
        "child_id": child.id,
        "chunk_id": child.id,
        "id": child.id,
        "input_rank": record["index"] + 1,
        "score": item.get("score"),
        "rerank_score": item.get("rerank_score"),
        "rrf_score": item.get("rrf_score"),
        "keyword_rank": item.get("keyword_rank"),
        "vector_rank": item.get("vector_rank"),
        "match_sources": list(item.get("match_sources") or []),
    }


def _cap_item(item: dict, cap: int, chunk: Chunk | None = None) -> dict:
    row = dict(item)
    content = str(row.get("content") or "")
    cap = max(0, cap)
    old_window = dict(row.get("context_window") or {})
    if len(content) <= cap:
        if old_window:
            old_window["max_context_chars"] = cap
            row["context_window"] = old_window
            return row
        start, end = 0, len(content)
    else:
        evidence_spans = []
        for matched in row.get("matched_ranges") or []:
            start_at = matched.get("context_start_at")
            end_at = matched.get("context_end_at")
            if isinstance(start_at, int) and isinstance(end_at, int):
                evidence_spans.append((start_at, end_at))
        start, end = _window_for_evidence(len(content), cap, evidence_spans)
        row["content"] = content[start:end]

        adjusted_ranges = []
        for matched in row.get("matched_ranges") or []:
            adjusted = dict(matched)
            local_start = matched.get("context_start_at")
            local_end = matched.get("context_end_at")
            if isinstance(local_start, int) and isinstance(local_end, int):
                visible_start = max(local_start, start)
                visible_end = min(local_end, end)
                visible = visible_end > visible_start
                adjusted["context_start_at"] = visible_start - start if visible else None
                adjusted["context_end_at"] = visible_end - start if visible else None
                adjusted["visible"] = visible
                adjusted["clipped"] = bool(
                    matched.get("clipped")
                    or not visible
                    or visible_start > local_start
                    or visible_end < local_end
                )
            adjusted_ranges.append(adjusted)
        if "matched_ranges" in row:
            row["matched_ranges"] = adjusted_ranges

    if old_window:
        rendered_base = int(old_window.get("rendered_start_at") or 0)
        rendered_end = int(old_window.get("rendered_end_at") or rendered_base)
        source_base = old_window.get("source_start_at")
        source_end = old_window.get("source_end_at")
        if (
            isinstance(source_base, int)
            and isinstance(source_end, int)
            and source_end - source_base == rendered_end - rendered_base
        ):
            old_window["source_start_at"] = source_base + start
            old_window["source_end_at"] = source_base + end
        old_window["rendered_start_at"] = rendered_base + start
        old_window["rendered_end_at"] = rendered_base + end
        if "item_start_at" in old_window:
            item_base = int(old_window.get("item_start_at") or 0)
            old_window["item_start_at"] = item_base + start
            old_window["item_end_at"] = item_base + end
        old_window["clipped"] = bool(old_window.get("clipped") or start > 0 or end < len(content))
        old_window["max_context_chars"] = cap
        if old_window["clipped"]:
            old_window["clip_reason"] = "max_context_chars"
        row["context_window"] = old_window
        return row

    source_start = chunk.start_at if chunk else 0
    source_end = chunk.end_at if chunk else len(content)
    exact_source_length = source_end - source_start == len(content)
    row["context_window"] = {
        "parent_start_at": source_start,
        "parent_end_at": source_end,
        "source_start_at": source_start + start if exact_source_length else source_start,
        "source_end_at": source_start + end if exact_source_length else source_end,
        "rendered_start_at": start,
        "rendered_end_at": end,
        "item_start_at": start,
        "item_end_at": end,
        "clipped": start > 0 or end < len(content),
        "clip_reason": "max_context_chars" if start > 0 or end < len(content) else "",
        "max_context_chars": cap,
    }
    row["context_content_source"] = "item_content"
    return row


def _document_item_matches(item: dict, child: Chunk) -> bool:
    return bool(
        (not item.get("chunk_type") or item.get("chunk_type") == child.chunk_type)
        and (not item.get("knowledge_id") or str(item.get("knowledge_id")) == child.knowledge_id)
        and (
            not item.get("knowledge_base_id")
            or str(item.get("knowledge_base_id")) == child.knowledge_base_id
        )
    )


def resolve_parent_context(results, *, tenant_id, max_context_chars) -> list[dict]:
    """Collapse reranked text children into tenant-scoped, edit-aware parent context."""
    rows = list(results or [])
    cap = max(0, int(max_context_chars))
    candidate_ids = {
        str(item.get("chunk_id") or item.get("id"))
        for item in rows
        if item.get("retrieval_path") == "document"
        and (item.get("chunk_id") or item.get("id"))
    }
    children = {
        child.id: child
        for child in Chunk.objects.filter(
            id__in=candidate_ids,
            tenant_id=tenant_id,
            is_enabled=True,
            chunk_type__in=("text", "image_ocr", "image_caption"),
            deleted_at__isnull=True,
            knowledge__tenant_id=tenant_id,
            knowledge__deleted_at__isnull=True,
            knowledge__enable_status="enabled",
            knowledge_base__tenant_id=tenant_id,
            knowledge_base__deleted_at__isnull=True,
            knowledge__knowledge_base_id=F("knowledge_base_id"),
        ).select_related("knowledge", "knowledge_base")
    }
    parent_ids = {child.context_parent_id for child in children.values() if child.context_parent_id}
    parents = {
        parent.id: parent
        for parent in Chunk.objects.filter(
            id__in=parent_ids,
            tenant_id=tenant_id,
            deleted_at__isnull=True,
            knowledge__tenant_id=tenant_id,
            knowledge__deleted_at__isnull=True,
            knowledge__enable_status="enabled",
            knowledge_base__tenant_id=tenant_id,
            knowledge_base__deleted_at__isnull=True,
            knowledge__knowledge_base_id=F("knowledge_base_id"),
        ).select_related("knowledge", "knowledge_base")
    }
    siblings_by_parent: dict[str, list[Chunk]] = {}
    if parent_ids:
        siblings = Chunk.objects.filter(
            context_parent_id__in=parent_ids,
            tenant_id=tenant_id,
            chunk_type="text",
            is_enabled=True,
            deleted_at__isnull=True,
            knowledge__tenant_id=tenant_id,
            knowledge__deleted_at__isnull=True,
            knowledge__enable_status="enabled",
            knowledge_base__tenant_id=tenant_id,
            knowledge_base__deleted_at__isnull=True,
            knowledge__knowledge_base_id=F("knowledge_base_id"),
        ).order_by("start_at", "end_at", "chunk_index", "id")
        for sibling in siblings:
            siblings_by_parent.setdefault(sibling.context_parent_id, []).append(sibling)

    standalone: dict[tuple[str, str], dict] = {}
    groups: dict[str, dict] = {}

    def keep_standalone(key: tuple[str, str], record: dict) -> None:
        current = standalone.get(key)
        if current is None or _result_sort_key(record) < _result_sort_key(current):
            standalone[key] = record

    for index, item in enumerate(rows):
        chunk_id = str(item.get("chunk_id") or item.get("id") or "")
        if item.get("retrieval_path") != "document":
            key = (str(item.get("retrieval_path") or "other"), chunk_id or f"row-{index}")
            record = {"row": _cap_item(item, cap), "item": item, "index": index}
            keep_standalone(key, record)
            continue

        child = children.get(chunk_id)
        if not child or not _document_item_matches(item, child):
            continue
        if item.get("parent_chunk_id") and item.get("matched_child_ids"):
            record = {
                "row": _cap_item(item, cap, child),
                "item": item,
                "child": child,
                "index": index,
            }
            key = ("document", chunk_id)
            keep_standalone(key, record)
            continue
        if not child.context_parent_id:
            record = {
                "row": _cap_item(item, cap, child),
                "item": item,
                "child": child,
                "index": index,
            }
            key = ("document", chunk_id)
            keep_standalone(key, record)
            continue
        parent = parents.get(child.context_parent_id)
        if parent is None:
            record = {
                "row": _fallback(item, child, "missing_parent", cap),
                "item": item,
                "child": child,
                "index": index,
            }
            keep_standalone(("document", chunk_id), record)
            continue
        if parent.chunk_type != "parent_text":
            record = {
                "row": _fallback(item, child, "invalid_parent_type", cap),
                "item": item,
                "child": child,
                "index": index,
            }
            keep_standalone(("document", chunk_id), record)
            continue
        if parent.knowledge_id != child.knowledge_id or parent.knowledge_base_id != child.knowledge_base_id:
            record = {
                "row": _fallback(item, child, "parent_scope_mismatch", cap),
                "item": item,
                "child": child,
                "index": index,
            }
            keep_standalone(("document", chunk_id), record)
            continue
        if not _has_usable_source_range(child, parent):
            record = {
                "row": _fallback(item, child, "invalid_source_range", cap),
                "item": item,
                "child": child,
                "index": index,
            }
            keep_standalone(("document", chunk_id), record)
            continue

        group = groups.setdefault(parent.id, {"parent": parent, "records": {}})
        record = {"item": item, "child": child, "index": index}
        current = group["records"].get(child.id)
        if current is None or _record_sort_key(record) < _record_sort_key(current):
            group["records"][child.id] = record

    grouped_output = []
    for group in groups.values():
        parent = group["parent"]
        records = sorted(group["records"].values(), key=_record_sort_key)
        representative = records[0]
        matched_children = [record["child"] for record in records]
        siblings = [
            sibling
            for sibling in siblings_by_parent.get(parent.id, [])
            if sibling.knowledge_id == parent.knowledge_id and sibling.knowledge_base_id == parent.knowledge_base_id
        ]
        rendered, segments, applied_ids = _render_parent(parent, siblings)
        spans = [_rendered_span(child, segments) for child in matched_children]
        window_start, window_end = _window_for_evidence(len(rendered), cap, spans)
        row = dict(representative["item"])
        row["content"] = rendered[window_start:window_end]
        row["parent_chunk_id"] = parent.id
        row["matched_child_ids"] = [child.id for child in matched_children]
        row["matched_child_provenance"] = [_provenance(record) for record in records]
        row["matched_ranges"] = [
            _matched_range(child, span, window_start, window_end)
            for child, span in zip(matched_children, spans)
        ]
        row["selected_strategy"] = _strategy_for(representative["child"], parent)
        row["applied_edit_child_ids"] = applied_ids
        row["context_window"] = _context_window(
            parent, segments, window_start, window_end, cap, len(rendered)
        )
        grouped_output.append(
            {
                "row": row,
                "item": representative["item"],
                "index": representative["index"],
            }
        )
    return [record["row"] for record in sorted([*standalone.values(), *grouped_output], key=_result_sort_key)]
