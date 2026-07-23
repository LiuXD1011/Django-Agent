import base64
import csv
import io
import json
import re
from pathlib import Path

from .images import ImageTooSmallError, InvalidImageError, guess_image_mime, inspect_image
from .legacy_office import LegacyOfficeParseError, convert_legacy_office
from .remote_images import UnsafeRemoteImageError, download_remote_image
from .spreadsheet import parse_xls, parse_xlsx
from .types import ImageBlock, ParsedDocument, ParseWarning, TextBlock


IMAGE_TYPES = {"jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff", "webp", "svg"}
TEXT_TYPES = {"txt", "log", "py"}
MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)", re.I)
DATA_IMAGE_RE = re.compile(r"^data:(image/[^;,]+);base64,(.+)$", re.I | re.S)


def _image_block(data: bytes, mime_type: str, source_type: str, source_ref: str, block_index: int, page_index=None, metadata=None):
    width, height, detected_mime = inspect_image(data, mime_type)
    return ImageBlock(data, detected_mime, width, height, source_type, source_ref, block_index, page_index, metadata or {})


def _warning(document: ParsedDocument, code: str, message: str, block_index=None, source_ref=""):
    document.warnings.append(ParseWarning(code, message, block_index, source_ref))


def parse_text(name: str, data: bytes) -> ParsedDocument:
    suffix = Path(name).suffix.lower().lstrip(".")
    text = data.decode("utf-8", errors="ignore")
    if suffix == "json":
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except Exception:
            pass
    elif suffix == "csv":
        try:
            text = "\n".join(" | ".join(row) for row in csv.reader(io.StringIO(text)))
        except Exception:
            pass
    elif suffix in {"html", "htm"}:
        text = re.sub(r"<(script|style).*?</\1>", "", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
    return ParsedDocument(text_blocks=[TextBlock(text, 0)] if text.strip() else [])


def parse_image(name: str, data: bytes) -> ParsedDocument:
    document = ParsedDocument()
    mime_type = "image/svg+xml" if name.lower().endswith(".svg") else guess_image_mime(name)
    try:
        document.images.append(_image_block(data, mime_type, "standalone", name, 0))
    except InvalidImageError as exc:
        _warning(document, "invalid_or_small_image", str(exc), 0, name)
    return document


def parse_markdown(name: str, data: bytes) -> ParsedDocument:
    document = ParsedDocument()
    text = data.decode("utf-8", errors="ignore")
    cursor = 0
    block_index = 0
    for match in MARKDOWN_IMAGE_RE.finditer(text):
        before = text[cursor:match.start()].strip()
        if before:
            document.text_blocks.append(TextBlock(before, block_index))
            block_index += 1
        alt, target = match.group(1), match.group(2).strip().strip("<>")
        try:
            data_match = DATA_IMAGE_RE.match(target)
            if data_match:
                image_data = base64.b64decode(data_match.group(2), validate=True)
                document.images.append(_image_block(image_data, data_match.group(1), "markdown_data", alt or "data-uri", block_index))
            elif target.startswith(("http://", "https://")):
                image_data, mime_type, resolved = download_remote_image(target)
                document.images.append(_image_block(image_data, mime_type, "markdown_remote", resolved, block_index))
            else:
                document.text_blocks.append(TextBlock(match.group(0), block_index))
                _warning(document, "relative_image_unavailable", "relative Markdown image is not part of the upload", block_index, target)
        except (ValueError, InvalidImageError, UnsafeRemoteImageError, OSError) as exc:
            document.text_blocks.append(TextBlock(match.group(0), block_index))
            _warning(document, "image_fetch_failed", str(exc), block_index, target)
        block_index += 1
        cursor = match.end()
    tail = text[cursor:].strip()
    if tail:
        document.text_blocks.append(TextBlock(tail, block_index))
    return document


def parse_pdf(name: str, data: bytes) -> ParsedDocument:
    import fitz

    document = ParsedDocument()
    pdf = fitz.open(stream=data, filetype="pdf")
    block_index = 0
    try:
        for page_index, page in enumerate(pdf):
            page_text = page.get_text("text").strip()
            has_visual = bool(page.get_images(full=True) or page.get_drawings())
            if len(page_text) < 20 and has_visual:
                rendered = page.get_pixmap(dpi=150, alpha=False).tobytes("jpeg")
                document.images.append(_image_block(rendered, "image/jpeg", "scanned_pdf", f"page:{page_index + 1}", block_index, page_index))
                block_index += 1
                continue
            items = []
            for raw in page.get_text("dict").get("blocks", []):
                bbox = raw.get("bbox") or (0, 0, 0, 0)
                if raw.get("type") == 0:
                    value = "\n".join(
                        "".join(span.get("text", "") for span in line.get("spans", []))
                        for line in raw.get("lines", [])
                    ).strip()
                    if value:
                        items.append((bbox[1], bbox[0], "text", value, "", bbox))
                elif raw.get("type") == 1 and raw.get("image"):
                    items.append((bbox[1], bbox[0], "image", raw["image"], raw.get("ext", "png"), bbox))
            for _, _, kind, value, ext, bbox in sorted(items, key=lambda item: (item[0], item[1])):
                if kind == "text":
                    document.text_blocks.append(TextBlock(value, block_index, page_index, {"bbox": list(bbox)}))
                else:
                    try:
                        document.images.append(_image_block(value, guess_image_mime(f"image.{ext}"), "pdf_embedded", f"page:{page_index + 1}", block_index, page_index, {"bbox": list(bbox)}))
                    except ImageTooSmallError as exc:
                        _warning(document, "small_image_skipped", str(exc), block_index, f"page:{page_index + 1}")
                    except InvalidImageError as exc:
                        _warning(document, "invalid_image", str(exc), block_index, f"page:{page_index + 1}")
                block_index += 1
            for drawing_index, drawing in enumerate(page.get_drawings()):
                rect = drawing.get("rect")
                if not rect or rect.width < 64 or rect.height < 64:
                    continue
                try:
                    pixmap = page.get_pixmap(clip=rect, dpi=150, alpha=False)
                    rendered = pixmap.tobytes("png")
                    document.images.append(_image_block(rendered, "image/png", "pdf_vector", f"page:{page_index + 1}:drawing:{drawing_index}", block_index, page_index, {"bbox": [rect.x0, rect.y0, rect.x1, rect.y1]}))
                    block_index += 1
                except InvalidImageError:
                    continue
    finally:
        pdf.close()
    return document


def parse_docx(name: str, data: bytes) -> ParsedDocument:
    import docx
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    source = docx.Document(io.BytesIO(data))
    document = ParsedDocument()
    block_index = 0

    def append_image(blip, metadata):
        nonlocal block_index
        rel_id = blip.get(qn("r:embed"))
        part = source.part.related_parts.get(rel_id)
        if not part:
            return
        try:
            document.images.append(
                _image_block(part.blob, part.content_type, "docx", rel_id, block_index, metadata=metadata)
            )
        except InvalidImageError as exc:
            _warning(document, "invalid_or_small_image", str(exc), block_index, rel_id)
        block_index += 1

    def heading_level(paragraph):
        style = paragraph.style
        style_name = getattr(style, "name", "") or ""
        style_id = getattr(style, "style_id", "") or ""
        match = re.search(r"heading\s*([1-9])$", f"{style_name} {style_id}", re.I)
        if match:
            return int(match.group(1))
        paragraph_properties = paragraph._p.pPr
        outline = paragraph_properties.find(qn("w:outlineLvl")) if paragraph_properties is not None else None
        if outline is not None:
            return int(outline.get(qn("w:val"))) + 1
        return None

    def append_paragraph(paragraph, body_index):
        nonlocal block_index
        level = heading_level(paragraph)
        style_name = getattr(paragraph.style, "name", "") or ""
        metadata = {"paragraph_index": body_index, "style_name": style_name}
        block_type = "heading" if level is not None else "paragraph"
        if level is not None:
            metadata["heading_level"] = level

        text_parts = []
        inline_position = 0

        def flush_text():
            nonlocal block_index, inline_position
            value = "".join(text_parts).strip()
            text_parts.clear()
            if not value:
                return
            fragment_metadata = {**metadata, "inline_position": inline_position}
            document.text_blocks.append(
                TextBlock(
                    value,
                    block_index,
                    metadata=fragment_metadata,
                    block_type=block_type,
                    source_start=body_index,
                    source_end=body_index,
                )
            )
            block_index += 1
            inline_position += 1

        for node in paragraph._p.iter():
            if node.tag == qn("w:t") and node.text:
                text_parts.append(node.text)
            elif node.tag == qn("w:tab"):
                text_parts.append("\t")
            elif node.tag in {qn("w:br"), qn("w:cr")}:
                text_parts.append("\n")
            elif node.tag == qn("a:blip"):
                flush_text()
                append_image(node, {**metadata, "inline_position": inline_position})
                inline_position += 1
        flush_text()

    table_index = 0
    for body_index, child in enumerate(source.element.body.iterchildren(), start=1):
        if child.tag == qn("w:p"):
            append_paragraph(Paragraph(child, source), body_index)
        elif child.tag == qn("w:tbl"):
            table = Table(child, source)
            table_index += 1
            rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
            cells = [
                {"row": row_number, "column": column_number, "text": text}
                for row_number, row in enumerate(rows, start=1)
                for column_number, text in enumerate(row, start=1)
            ]
            metadata = {
                "table_index": table_index,
                "rows": rows,
                "cells": cells,
                "row_count": len(rows),
                "column_count": max((len(row) for row in rows), default=0),
            }
            value = "\n".join(" | ".join(row) for row in rows)
            document.text_blocks.append(
                TextBlock(
                    value,
                    block_index,
                    metadata=metadata,
                    block_type="table",
                    source_start=body_index,
                    source_end=body_index,
                )
            )
            block_index += 1

            visited_cells = set()
            for row_number, row in enumerate(table.rows, start=1):
                for column_number, cell in enumerate(row.cells, start=1):
                    if cell._tc in visited_cells:
                        continue
                    visited_cells.add(cell._tc)
                    image_metadata = {
                        "table_index": table_index,
                        "table_cell": {"row": row_number, "column": column_number},
                    }
                    for blip in cell._tc.iter(qn("a:blip")):
                        append_image(blip, image_metadata)
    return document


def parse_pptx(name: str, data: bytes) -> ParsedDocument:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    source = Presentation(io.BytesIO(data))
    document = ParsedDocument()
    block_index = 0

    def ordered_shapes(shapes, parent_path=()):
        for index, shape in enumerate(shapes):
            shape_path = (*parent_path, index)
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                yield from ordered_shapes(shape.shapes, shape_path)
            else:
                yield shape_path, shape

    for page_index, slide in enumerate(source.slides):
        slide_number = page_index + 1
        for shape_path, shape in ordered_shapes(slide.shapes):
            shape_index = shape_path[0]
            metadata = {
                "slide_number": slide_number,
                "shape_index": shape_index,
                "shape_path": list(shape_path),
                "shape_name": shape.name,
            }
            if getattr(shape, "has_table", False):
                rows = [[cell.text.strip() for cell in row.cells] for row in shape.table.rows]
                metadata.update(
                    {
                        "rows": rows,
                        "cells": [
                            {"row": row_number, "column": column_number, "text": text}
                            for row_number, row in enumerate(rows, start=1)
                            for column_number, text in enumerate(row, start=1)
                        ],
                        "row_count": len(rows),
                        "column_count": max((len(row) for row in rows), default=0),
                    }
                )
                value = "\n".join(" | ".join(row) for row in rows)
                document.text_blocks.append(
                    TextBlock(
                        value,
                        block_index,
                        page_index,
                        metadata,
                        block_type="table",
                        source_start=slide_number,
                        source_end=slide_number,
                    )
                )
                block_index += 1
                continue

            text = getattr(shape, "text", "").strip() if getattr(shape, "has_text_frame", False) else ""
            if text:
                document.text_blocks.append(
                    TextBlock(
                        text,
                        block_index,
                        page_index,
                        metadata,
                        block_type="text_box",
                        source_start=slide_number,
                        source_end=slide_number,
                    )
                )
                block_index += 1
            if shape.shape_type != MSO_SHAPE_TYPE.PICTURE:
                continue
            extension = (shape.image.ext or "").lower()
            source_ref = f"slide:{slide_number}:shape:{'.'.join(str(part) for part in shape_path)}"
            if extension in {"wmf", "emf"}:
                _warning(document, "unsupported_vector_media", f".{extension} media is not supported", block_index, source_ref)
                block_index += 1
                continue
            try:
                document.images.append(
                    _image_block(
                        shape.image.blob,
                        guess_image_mime(f"image.{extension}"),
                        "pptx",
                        source_ref,
                        block_index,
                        page_index,
                        metadata,
                    )
                )
            except InvalidImageError as exc:
                _warning(document, "invalid_or_small_image", str(exc), block_index, source_ref)
            block_index += 1
    return document


def parse_legacy_office(name: str, data: bytes) -> ParsedDocument:
    converted_name, converted_data = convert_legacy_office(name, data)
    try:
        if converted_name.endswith(".docx"):
            return parse_docx(converted_name, converted_data)
        return parse_pptx(converted_name, converted_data)
    except Exception as exc:
        raise LegacyOfficeParseError(
            "legacy_office_converted_output_invalid",
            "legacy Office conversion output could not be parsed",
        ) from exc


def parse_document(name: str, data: bytes, engine: str = "builtin") -> ParsedDocument:
    if engine not in {"", "builtin", "plain"}:
        raise ValueError(f"unsupported parser engine: {engine}")
    suffix = Path(name or "").suffix.lower().lstrip(".")
    if suffix in IMAGE_TYPES:
        return parse_image(name, data)
    if suffix in {"md", "markdown"}:
        return parse_markdown(name, data)
    if suffix == "pdf":
        return parse_pdf(name, data)
    if suffix == "docx":
        return parse_docx(name, data)
    if suffix == "pptx":
        return parse_pptx(name, data)
    if suffix == "xlsx":
        return parse_xlsx(data)
    if suffix == "xls":
        return parse_xls(data)
    if suffix in {"doc", "ppt"}:
        return parse_legacy_office(name, data)
    return parse_text(name, data)
