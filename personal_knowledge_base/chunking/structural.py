import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from personal_knowledge_base.document_parsing.types import ParsedDocument, TextBlock

from .recursive import protected_ranges, split_text_range
from .types import ChunkDraft


_MARKDOWN_HEADING_RE = re.compile(r"(?m)^(#{1,6})[ \t]+(.+?)[ \t]*$")
_PROTECTED_BLOCK_TYPES = {"table", "code", "formula", "link", "image_reference"}
_LAYOUT_BLOCK_TYPES = {"paragraph", "text_box"}


@dataclass(slots=True)
class AtomicUnit:
    content: str
    start: int
    end: int
    block_index: int
    block_type: str
    metadata: dict = field(default_factory=dict)
    protected: bool = False


def _block_metadata(block: TextBlock) -> dict:
    metadata = dict(block.metadata)
    if block.page_index is not None:
        metadata["page_index"] = block.page_index
    if block.source_start is not None:
        metadata["source_start"] = block.source_start
    if block.source_end is not None:
        metadata["source_end"] = block.source_end
    return metadata


def _unit(source: str, start: int, end: int, block: TextBlock, *, block_type=None, metadata=None):
    if start >= end:
        return None
    unit_type = block_type or block.block_type
    value = source[start:end]
    return AtomicUnit(
        content=value,
        start=start,
        end=end,
        block_index=block.block_index,
        block_type=unit_type,
        metadata=dict(metadata) if metadata is not None else _block_metadata(block),
        protected=unit_type in _PROTECTED_BLOCK_TYPES or bool(
            protected_ranges(value) == [(0, len(value))]
        ),
    )


def _markdown_units(source: str, base: int, text: str, block: TextBlock) -> list[AtomicUnit]:
    matches = list(_MARKDOWN_HEADING_RE.finditer(text))
    if not matches or block.block_type == "heading":
        item = _unit(source, base, base + len(text), block)
        return [item] if item else []

    units = []
    cursor = 0
    for index, match in enumerate(matches):
        before = _unit(source, base + cursor, base + match.start(), block, block_type="paragraph")
        if before:
            units.append(before)
        heading_metadata = {**_block_metadata(block), "heading_level": len(match.group(1))}
        heading = _unit(
            source,
            base + match.start(),
            base + match.end(),
            block,
            block_type="heading",
            metadata=heading_metadata,
        )
        if heading:
            units.append(heading)
        cursor = match.end()
        if index + 1 < len(matches):
            body = _unit(
                source,
                base + cursor,
                base + matches[index + 1].start(),
                block,
                block_type="paragraph",
            )
            if body:
                units.append(body)
            cursor = matches[index + 1].start()
    tail = _unit(source, base + cursor, base + len(text), block, block_type="paragraph")
    if tail:
        units.append(tail)
    return units


def build_atomic_units(parsed: ParsedDocument) -> tuple[str, list[AtomicUnit]]:
    source_parts = []
    units = []
    offset = 0
    for block in sorted(parsed.text_blocks, key=lambda item: item.block_index):
        text = block.text
        if text == "":
            continue
        if source_parts:
            source_parts.append("\n\n")
            offset += 2
        source_parts.append(text)
        units.extend(_markdown_units("".join(source_parts), offset, text, block))
        offset += len(text)
    return "".join(source_parts), units


def select_auto_strategy(units: list[AtomicUnit]) -> str:
    if any(unit.block_type == "heading" for unit in units):
        return "heading"
    if any(unit.block_type == "record" for unit in units):
        return "record"
    if any(
        unit.block_type in _LAYOUT_BLOCK_TYPES
        or unit.metadata.get("slide_number") is not None
        or unit.metadata.get("paragraph_index") is not None
        or unit.metadata.get("page_number") is not None
        or unit.metadata.get("page_index") is not None
        for unit in units
    ) or any(getattr(unit, "page_index", None) is not None for unit in units):
        return "layout"
    return "recursive"


def _context(*parts) -> str:
    return " > ".join(str(part).strip() for part in parts if str(part or "").strip())


def _draft_metadata(group: list[AtomicUnit], strategy: str) -> dict:
    protected = [(unit.start, unit.end) for unit in group if unit.protected]
    for unit in group:
        protected.extend(protected_ranges(unit.content, offset=unit.start))
    return {
        "strategy": strategy,
        "block_indices": sorted({unit.block_index for unit in group}),
        "source_refs": [
            {
                "block_index": unit.block_index,
                "source_start": unit.metadata.get("source_start"),
                "source_end": unit.metadata.get("source_end"),
            }
            for unit in group
        ],
        "_protected_ranges": sorted(set(protected)),
    }


def _pack_units(
    groups: Iterable[tuple[str, list[AtomicUnit]]],
    *,
    source: str,
    chunk_size: int,
    overlap: int,
    strategy: str,
    token_counter: Callable[[str], int],
    token_limit: int,
) -> list[ChunkDraft]:
    drafts = []
    for context_header, units in groups:
        pending = []

        def flush():
            if not pending:
                return
            start, end = pending[0].start, pending[-1].end
            drafts.append(
                ChunkDraft(
                    content=source[start:end],
                    context_header=context_header,
                    start_at=start,
                    end_at=end,
                    metadata=_draft_metadata(pending, strategy),
                )
            )
            pending.clear()

        for unit in units:
            if unit.end - unit.start > chunk_size and not unit.protected:
                flush()
                drafts.extend(
                    split_text_range(
                        source,
                        unit.start,
                        unit.end,
                        chunk_size=chunk_size,
                        overlap=overlap,
                        context_header=context_header,
                        token_counter=token_counter,
                        token_limit=token_limit,
                        extra_protected_ranges=protected_ranges(unit.content, offset=unit.start),
                        metadata=_draft_metadata([unit], strategy),
                    )
                )
                continue

            candidate_start = pending[0].start if pending else unit.start
            candidate = source[candidate_start:unit.end]
            exceeds_chars = bool(pending) and len(candidate) > chunk_size
            exceeds_tokens = bool(token_limit and pending and token_counter(candidate) > token_limit)
            if exceeds_chars or exceeds_tokens:
                flush()
            pending.append(unit)
        flush()
    return drafts


def _heading_text(unit: AtomicUnit) -> str:
    match = _MARKDOWN_HEADING_RE.fullmatch(unit.content)
    return (match.group(2) if match else unit.content).strip()


def split_heading_units(
    units: list[AtomicUnit],
    *,
    source: str,
    chunk_size: int,
    overlap: int,
    title: str,
    token_counter: Callable[[str], int],
    token_limit: int = 0,
) -> list[ChunkDraft]:
    groups = []
    headings = []
    current = []
    current_context = title
    for unit in units:
        if unit.block_type == "heading":
            if current:
                groups.append((current_context, current))
            level = int(unit.metadata.get("heading_level", 1))
            headings = headings[: max(0, level - 1)]
            headings.append(_heading_text(unit))
            current_context = _context(title, *headings)
            current = [unit]
        else:
            current.append(unit)
    if current:
        groups.append((current_context, current))
    return _pack_units(
        groups,
        source=source,
        chunk_size=chunk_size,
        overlap=overlap,
        strategy="heading",
        token_counter=token_counter,
        token_limit=token_limit,
    )


def _layout_key(unit: AtomicUnit):
    slide = unit.metadata.get("slide_number")
    if slide is not None:
        return ("Slide", int(slide))
    page = unit.metadata.get("page_number")
    if page is not None:
        return ("Page", int(page))
    if unit.metadata.get("page_index") is not None:
        return ("Page", int(unit.metadata["page_index"]) + 1)
    return ("Document", 0)


def split_layout_units(
    units: list[AtomicUnit],
    *,
    source: str,
    chunk_size: int,
    overlap: int,
    title: str,
    token_counter: Callable[[str], int],
    token_limit: int = 0,
) -> list[ChunkDraft]:
    grouped = []
    for unit in units:
        key = _layout_key(unit)
        if grouped and grouped[-1][0] == key:
            grouped[-1][1].append(unit)
        else:
            grouped.append((key, [unit]))
    groups = [
        (_context(title, f"{key[0]} {key[1]}" if key[1] else ""), members)
        for key, members in grouped
    ]
    return _pack_units(
        groups,
        source=source,
        chunk_size=chunk_size,
        overlap=overlap,
        strategy="layout",
        token_counter=token_counter,
        token_limit=token_limit,
    )


def split_record_units(
    units: list[AtomicUnit],
    *,
    source: str,
    chunk_size: int,
    overlap: int,
    title: str,
    token_counter: Callable[[str], int],
    token_limit: int = 0,
) -> list[ChunkDraft]:
    grouped = []
    for unit in units:
        sheet = unit.metadata.get("sheet_name") or unit.metadata.get("record_group") or "Records"
        headers = tuple(str(value) for value in unit.metadata.get("headers", []) if str(value).strip())
        key = (sheet, headers)
        if grouped and grouped[-1][0] == key:
            grouped[-1][1].append(unit)
        else:
            grouped.append((key, [unit]))
    groups = [
        (_context(title, sheet, " | ".join(headers)), members)
        for (sheet, headers), members in grouped
    ]
    return _pack_units(
        groups,
        source=source,
        chunk_size=chunk_size,
        overlap=overlap,
        strategy="record",
        token_counter=token_counter,
        token_limit=token_limit,
    )
