import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from personal_knowledge_base.document_parsing.types import ParsedDocument, TextBlock

from .recursive import protected_ranges, split_text_range
from .types import ChunkDraft
from .validator import minimum_chunk_size


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
    boundary_before: bool = False


def _block_metadata(block: TextBlock) -> dict:
    metadata = dict(block.metadata)
    if block.page_index is not None:
        metadata["page_index"] = block.page_index
    if block.source_start is not None:
        metadata["source_start"] = block.source_start
    if block.source_end is not None:
        metadata["source_end"] = block.source_end
    return metadata


def _unit(
    source: str,
    start: int,
    end: int,
    block: TextBlock,
    *,
    block_type=None,
    metadata=None,
    boundary_before=False,
):
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
        boundary_before=boundary_before,
    )


def _markdown_units(
    source: str,
    base: int,
    text: str,
    block: TextBlock,
    *,
    boundary_before: bool = False,
) -> list[AtomicUnit]:
    matches = list(_MARKDOWN_HEADING_RE.finditer(text))
    if not matches or block.block_type == "heading":
        item = _unit(source, base, base + len(text), block, boundary_before=boundary_before)
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
    if units:
        units[0].boundary_before = boundary_before
    return units


def build_atomic_units(parsed: ParsedDocument) -> tuple[str, list[AtomicUnit]]:
    source_parts = []
    units = []
    offset = 0
    previous_block_index = None
    image_indices = sorted(image.block_index for image in parsed.images)
    for block in sorted(parsed.text_blocks, key=lambda item: item.block_index):
        text = block.text
        if text == "":
            continue
        if source_parts:
            source_parts.append("\n\n")
            offset += 2
        source_parts.append(text)
        lower_bound = previous_block_index if previous_block_index is not None else -1
        media_boundary = any(lower_bound < image_index < block.block_index for image_index in image_indices)
        units.extend(
            _markdown_units(
                "".join(source_parts),
                offset,
                text,
                block,
                boundary_before=media_boundary,
            )
        )
        offset += len(text)
        previous_block_index = block.block_index
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
                "page_index": unit.metadata.get("page_index"),
                "bbox": unit.metadata.get("bbox"),
                "block_type": unit.block_type,
                "heading_level": unit.metadata.get("heading_level"),
                "structure_confidence": unit.metadata.get("structure_confidence"),
            }
            for unit in group
        ],
        "_protected_ranges": sorted(set(protected)),
    }


def draft_metadata_for_range(
    units: list[AtomicUnit],
    start: int,
    end: int,
    strategy: str,
) -> dict:
    covered = [unit for unit in units if unit.start < end and unit.end > start]
    return _draft_metadata(covered, strategy)


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
            if unit.boundary_before:
                flush()
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


def _whitespace_gap(source: str, start: int, end: int) -> bool:
    return start >= end or not source[start:end].strip()


def _merged_draft_metadata(left: dict, right: dict) -> dict:
    return {
        "strategy": left.get("strategy"),
        "block_indices": sorted({*left.get("block_indices", []), *right.get("block_indices", [])}),
        "source_refs": sorted(
            [*left.get("source_refs", []), *right.get("source_refs", [])],
            key=lambda ref: (ref.get("block_index") is None, ref.get("block_index") or 0),
        ),
        "_protected_ranges": sorted(set([*left.get("_protected_ranges", []), *right.get("_protected_ranges", [])])),
    }


def _same_flow(left: dict, right: dict) -> bool:
    """两个 draft 之间不存在图片/跨页等硬边界时返回 True。

    block_index 出现缺号说明中间夹着图片块；page_index 变化说明跨页。
    这两类边界是版面语义边界，微块合并不得跨越。
    """
    left_blocks = left.get("block_indices") or []
    right_blocks = right.get("block_indices") or []
    if left_blocks and right_blocks and min(right_blocks) > max(left_blocks) + 1:
        return False
    left_pages = [ref.get("page_index") for ref in left.get("source_refs", []) if ref.get("page_index") is not None]
    right_pages = [ref.get("page_index") for ref in right.get("source_refs", []) if ref.get("page_index") is not None]
    if left_pages and right_pages and left_pages[-1] != right_pages[0]:
        return False
    return True


def coalesce_tiny_drafts(
    drafts: list[ChunkDraft],
    *,
    source: str,
    chunk_size: int,
    token_counter: Callable[[str], int],
    token_limit: int = 0,
) -> list[ChunkDraft]:
    """把低于最小块尺寸的相邻 draft 并入邻居，防止碎片 chunk 进入全文/向量索引。

    结构化分块（heading 等）会把"仅含标题的空节"切成独立小 draft。这里优先向前合并
    （小段通常是节标题，正文在其后），放不下再并入前一个；两端都无法合并时保留原样，
    由 validator 的 tiny 统计兜底。合并保持 source 区间连续，满足覆盖性校验；
    图片与跨页等硬边界两侧不合并（见 _same_flow）。
    """
    if not drafts:
        return drafts
    floor = minimum_chunk_size(chunk_size)

    def fits(draft: ChunkDraft) -> bool:
        if draft.end_at - draft.start_at > chunk_size:
            return False
        return not token_limit or token_counter(draft.content) <= token_limit

    def absorb(left: ChunkDraft, right: ChunkDraft, context_header: str | None = None) -> ChunkDraft:
        return ChunkDraft(
            content=source[left.start_at : right.end_at],
            context_header=context_header or left.context_header,
            start_at=left.start_at,
            end_at=right.end_at,
            chunk_type=left.chunk_type,
            context_parent_index=left.context_parent_index,
            metadata=_merged_draft_metadata(left.metadata, right.metadata),
        )

    merged: list[ChunkDraft] = []
    index = 0
    while index < len(drafts):
        draft = drafts[index]
        index += 1
        while len(draft.content.strip()) < floor:
            nxt = drafts[index] if index < len(drafts) else None
            if (
                nxt is not None
                and draft.end_at <= nxt.start_at
                and _whitespace_gap(source, draft.end_at, nxt.start_at)
                and _same_flow(draft.metadata, nxt.metadata)
                and (candidate := absorb(draft, nxt, nxt.context_header)) and fits(candidate)
            ):
                draft = candidate
                index += 1
                continue
            prev = merged[-1] if merged else None
            if (
                prev is not None
                and prev.end_at <= draft.start_at
                and _whitespace_gap(source, prev.end_at, draft.start_at)
                and _same_flow(prev.metadata, draft.metadata)
                and (candidate := absorb(prev, draft)) and fits(candidate)
            ):
                merged[-1] = candidate
                draft = None
                break
            merged.append(draft)
            draft = None
            break
        if draft is not None:
            merged.append(draft)
    return merged


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
