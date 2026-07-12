import csv
import hashlib
import io
import json
import mimetypes
import re
from pathlib import Path

from django.core.files.storage import default_storage
from django.utils import timezone

from .graph_rag import (
    GraphNamespace,
    build_graph_for_chunks,
    delete_knowledge_graph,
    effective_extract_config,
    graph_enabled,
    graph_repository,
)
from .document_parsing import ImageBlock, TextBlock, parse_document
from .model_providers import extract_metadata, generate_questions, role_completion
from .multimodal import cleanup_knowledge_images, process_document_images
from .models import Chunk, Knowledge
from .search import delete_chunk_index, index_chunk
from .wiki_ingest import enqueue_wiki_ingest


UNSUPPORTED_MEDIA_FILE_TYPES = frozenset({"mp3", "wav", "m4a", "aac", "ogg", "flac", "mp4", "mov", "avi", "mkv", "webm"})


def detect_file_type(name: str) -> str:
    suffix = Path(name or "").suffix.lower().lstrip(".")
    if suffix:
        return suffix
    mime, _ = mimetypes.guess_type(name or "")
    return (mime or "text").split("/")[-1]


def is_unsupported_media_file(name: str) -> bool:
    return detect_file_type(name) in UNSUPPORTED_MEDIA_FILE_TYPES


def extract_text_from_bytes(name: str, data: bytes) -> str:
    parsed = parse_document(name, data)
    return "\n\n".join(block.text for block in sorted(parsed.text_blocks, key=lambda item: item.block_index))


def enrich_image_text(knowledge: Knowledge, content: str) -> str:
    return content


def strip_html(text: str) -> str:
    text = re.sub(r"<(script|style).*?</\1>", "", text, flags=re.I | re.S)
    return re.sub(r"<[^>]+>", " ", text)


def split_text(text: str, config: dict | None = None) -> list[tuple[int, int, str]]:
    config = config or {}
    chunk_size = int(config.get("chunk_size") or config.get("child_chunk_size") or 512)
    overlap = int(config.get("chunk_overlap") or 50)
    chunk_size = max(128, chunk_size)
    overlap = min(max(0, overlap), chunk_size // 2)
    pieces = []
    start = 0
    text = text or ""
    while start < len(text):
        end = min(len(text), start + chunk_size)
        boundary = max(text.rfind("\n\n", start, end), text.rfind("\n", start, end), text.rfind("。", start, end))
        if boundary > start + chunk_size // 3:
            end = boundary + 1
        # Do not create a second chunk whose useful payload is only a tiny tail
        # plus the configured overlap. A modestly oversized final chunk is much
        # more useful for retrieval than a near-duplicate short chunk.
        minimum_tail = max(overlap, min(128, chunk_size // 4))
        if end < len(text) and len(text) - end < minimum_tail:
            end = len(text)
        content = text[start:end].strip()
        if content:
            pieces.append((start, end, content))
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    if not pieces and text.strip():
        pieces.append((0, len(text), text.strip()))
    return pieces


def _text_segments(parsed) -> list[tuple[str, TextBlock, TextBlock]]:
    """Merge adjacent layout text while preserving page and image boundaries."""
    segments = []
    current = []

    def flush():
        if not current:
            return
        text = "\n".join(block.text.strip() for block in current if block.text.strip()).strip()
        if text:
            segments.append((text, current[0], current[-1]))
        current.clear()

    for block in parsed.ordered_blocks:
        if isinstance(block, ImageBlock):
            flush()
            continue
        if not isinstance(block, TextBlock) or not block.text.strip():
            continue
        if current and block.page_index != current[-1].page_index:
            flush()
        current.append(block)
    flush()
    return segments


def _link_chunks(chunks: list[Chunk]):
    ordered = sorted(chunks, key=lambda item: item.chunk_index)
    for idx, chunk in enumerate(ordered):
        chunk.pre_chunk_id = ordered[idx - 1].id if idx else ""
        chunk.next_chunk_id = ordered[idx + 1].id if idx + 1 < len(ordered) else ""
        chunk.save(update_fields=["pre_chunk_id", "next_chunk_id", "updated_at"])


def create_chunks(knowledge: Knowledge, content: str, process_config: dict | None = None, *, index=True, clear_existing=True):
    process_config = process_config or {}
    chunking_config = dict(knowledge.knowledge_base.chunking_config or {})
    override = process_config.get("chunking_config") or process_config.get("chunkingConfig")
    if isinstance(override, dict):
        chunking_config.update(override)
    if clear_existing:
        for chunk in Chunk.objects.filter(knowledge=knowledge):
            delete_chunk_index(chunk.id, chunk.seq_id)
        Chunk.objects.filter(knowledge=knowledge).delete()
    chunks = []
    for idx, (start, end, text) in enumerate(split_text(content, chunking_config)):
        chunk = Chunk.objects.create(
            tenant=knowledge.tenant,
            knowledge_base=knowledge.knowledge_base,
            knowledge=knowledge,
            content=text,
            chunk_index=idx,
            start_at=start,
            end_at=end,
            metadata={"title": knowledge.title},
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )
        chunks.append(chunk)
    _link_chunks(chunks)
    if index:
        for chunk in chunks:
            index_chunk(chunk)
    return chunks


def create_text_chunks(knowledge: Knowledge, parsed, process_config: dict | None = None):
    process_config = process_config or {}
    chunking_config = dict(knowledge.knowledge_base.chunking_config or {})
    override = process_config.get("chunking_config") or process_config.get("chunkingConfig")
    if isinstance(override, dict):
        chunking_config.update(override)
    for chunk in Chunk.objects.filter(knowledge=knowledge):
        delete_chunk_index(chunk.id, chunk.seq_id)
    Chunk.objects.filter(knowledge=knowledge).delete()
    chunks = []
    chunk_index = 0
    configured_size = max(128, int(chunking_config.get("chunk_size") or chunking_config.get("child_chunk_size") or 512))
    minimum_pdf_segment = min(128, configured_size // 4)
    is_pdf = detect_file_type(knowledge.file_name or knowledge.title) == "pdf"
    for segment, first_block, last_block in _text_segments(parsed):
        if (
            is_pdf
            and len(segment) < minimum_pdf_segment
            and chunks
            and first_block.page_index is not None
            and (chunks[-1].metadata or {}).get("page_index") == first_block.page_index
        ):
            previous = chunks[-1]
            previous.content = f"{previous.content}\n{segment}"
            previous.end_at = len(previous.content)
            previous_metadata = dict(previous.metadata or {})
            previous_metadata["source_block_end"] = last_block.block_index
            previous.metadata = previous_metadata
            previous.content_hash = hashlib.sha256(previous.content.encode("utf-8")).hexdigest()
            previous.save(update_fields=["content", "end_at", "metadata", "content_hash", "updated_at"])
            continue
        metadata = {
            "title": knowledge.title,
            "block_index": last_block.block_index,
            "source_block_start": first_block.block_index,
            "source_block_end": last_block.block_index,
            "page_index": first_block.page_index,
        }
        if first_block is last_block:
            metadata.update(first_block.metadata)
        for start, end, text in split_text(segment, chunking_config):
            chunks.append(
                Chunk.objects.create(
                    tenant=knowledge.tenant,
                    knowledge_base=knowledge.knowledge_base,
                    knowledge=knowledge,
                    content=text,
                    chunk_index=chunk_index,
                    start_at=start,
                    end_at=end,
                    metadata=metadata,
                    content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
            )
            chunk_index += 1
    _link_chunks(chunks)
    return chunks


def process_graph(knowledge: Knowledge, chunks: list[Chunk]):
    process_config = (knowledge.metadata or {}).get("process_config") or {}
    if not graph_enabled(knowledge.knowledge_base, process_config):
        return []
    if not graph_repository.available:
        return []
    delete_knowledge_graph(knowledge)
    extract_config = effective_extract_config(knowledge.knowledge_base, process_config)
    graphs = build_graph_for_chunks(chunks, extract_config, tenant=knowledge.tenant)
    if graphs:
        graph_repository.add_graph(
            GraphNamespace(knowledge_base_id=knowledge.knowledge_base_id, knowledge_id=knowledge.id),
            graphs,
        )
    return graphs


def process_knowledge(knowledge_id: str):
    from .span_tracker import SpanTracker

    knowledge = Knowledge.objects.select_related("knowledge_base", "tenant").get(id=knowledge_id)
    knowledge.parse_status = "processing"
    knowledge.save(update_fields=["parse_status", "updated_at"])

    tracker = SpanTracker(knowledge_id)
    root_span = tracker.open_attempt(attempt=1)

    post_span = None
    try:
        if knowledge.type != "file":
            raise ValueError("only file knowledge can be processed")

        # Stage 1: docreader（文件读取 + 文本提取）
        doc_span = tracker.begin_stage("docreader", input_data={"file_name": knowledge.file_name, "file_size": knowledge.file_size})
        with default_storage.open(knowledge.file_path, "rb") as handle:
            data = handle.read()
        process_config = (knowledge.metadata or {}).get("process_config") or {}
        parser_engine = str(process_config.get("parser_engine") or "builtin")
        parsed = parse_document(knowledge.file_name or knowledge.title, data, engine=parser_engine)
        content = "\n\n".join(block.text for block in sorted(parsed.text_blocks, key=lambda item: item.block_index))
        if doc_span:
            tracker.end_span(doc_span.span_id, output_data={"content_length": len(content), "image_count": len(parsed.images), "warning_count": len(parsed.warnings)})

        # Stage 2: chunking（分块）
        chunk_span = tracker.begin_stage("chunking", input_data={"chunk_size": process_config.get("chunk_size", 512)})
        cleanup_knowledge_images(knowledge)
        chunks = create_text_chunks(knowledge, parsed, process_config)
        if chunk_span:
            tracker.end_span(chunk_span.span_id, output_data={"chunk_count": len(chunks)})

        warnings = [warning.as_dict() for warning in parsed.warnings]
        graphs = []

        # Stage 3: multimodal（图片 OCR + Caption）
        multi_span = tracker.begin_stage("multimodal")
        try:
            image_chunks, image_warnings = process_document_images(knowledge, parsed.images, chunks)
            chunks.extend(image_chunks)
            warnings.extend(image_warnings)
            if detect_file_type(knowledge.file_name or knowledge.title) in {"jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff", "webp", "svg"} and not any(chunk.chunk_type in {"image_ocr", "image_caption"} for chunk in image_chunks):
                raise ValueError("standalone image produced no searchable OCR or caption")
            if multi_span:
                tracker.end_span(multi_span.span_id, output_data={"image_count": len(parsed.images), "image_chunk_count": len(image_chunks)})
        except Exception as exc:
            warnings.append({"stage": "multimodal", "message": str(exc)})
            if multi_span:
                tracker.fail_span(multi_span.span_id, error_message=str(exc))
            if detect_file_type(knowledge.file_name or knowledge.title) in {"jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff", "webp", "svg"}:
                raise

        # Stage 4: embedding（正文与图片统一索引）
        _link_chunks(chunks)
        embed_span = tracker.begin_stage("embedding")
        indexed = 0
        for chunk in sorted(chunks, key=lambda item: item.chunk_index):
            if chunk.is_enabled and chunk.chunk_type != "image_container":
                index_chunk(chunk)
                indexed += 1
        if embed_span:
            tracker.end_span(embed_span.span_id, output_data={"indexed": indexed})

        searchable_content = "\n\n".join(chunk.content for chunk in chunks if chunk.is_enabled)
        content = searchable_content or content
        try:
            graphs = process_graph(knowledge, [chunk for chunk in chunks if chunk.is_enabled])
        except Exception as exc:
            warnings.append({"stage": "graph", "message": str(exc)})

        # Stage 5: postprocess（摘要、问题、元数据、Wiki）
        post_span = tracker.begin_stage("postprocess")
        try:
            summary = role_completion(
                "summary",
                f"请为以下知识内容生成一段不超过 120 字的中文摘要。\n\n标题：{knowledge.title}\n\n内容：{content[:8000]}",
                content[:120].strip(),
                160,
                tenant=knowledge.tenant,
                scenario="summary",
            )
        except Exception as exc:
            summary = content[:120].strip()
            warnings.append({"stage": "summary", "message": str(exc)})
        try:
            questions = generate_questions(content, 5, tenant=knowledge.tenant)
        except Exception as exc:
            questions = []
            warnings.append({"stage": "questions", "message": str(exc)})
        try:
            extracted = extract_metadata(content, tenant=knowledge.tenant)
        except Exception as exc:
            extracted = {}
            warnings.append({"stage": "metadata", "message": str(exc)})
        try:
            wiki_result = enqueue_wiki_ingest(knowledge)
        except Exception as exc:
            wiki_result = {"pages": 0, "links": 0}
            warnings.append({"stage": "wiki", "message": str(exc)})
        metadata = knowledge.metadata or {}
        metadata.update(
            {
                "summary": summary,
                "generated_questions": questions,
                "extracted_metadata": extracted,
                "content_length": len(content),
                "image_count": len(parsed.images),
                "graph": {
                    "enabled": bool(graphs),
                    "node_count": sum(len(graph.get("node", [])) for graph in graphs),
                    "relation_count": sum(len(graph.get("relation", [])) for graph in graphs),
                },
                "wiki": wiki_result,
            }
        )
        if warnings:
            metadata["processing_warnings"] = warnings
        else:
            metadata.pop("processing_warnings", None)
        knowledge.metadata = metadata
        # 将摘要写入 description 字段，供 RAG 文档头部使用
        if summary and not knowledge.description:
            knowledge.description = summary[:300]
        knowledge.parse_status = "completed"
        knowledge.summary_status = "completed"
        knowledge.processed_at = timezone.now()
        knowledge.error_message = ""
        knowledge.save(update_fields=["metadata", "description", "parse_status", "summary_status", "processed_at", "error_message", "updated_at"])

        # 完成 postprocess span
        if post_span:
            tracker.end_span(post_span.span_id, output_data={"summary_length": len(summary or ""), "questions_count": len(questions or []), "wiki_pages": (wiki_result or {}).get("pages", 0)})
        # 完成根 span
        tracker.finalize_attempt(attempt=1)

    except Exception as exc:
        knowledge.parse_status = "failed"
        knowledge.error_message = str(exc)
        knowledge.save(update_fields=["parse_status", "error_message", "updated_at"])
        # 标记失败
        if post_span:
            tracker.fail_span(post_span.span_id, error_message=str(exc))
        if root_span:
            tracker.fail_span(root_span.span_id, error_message=str(exc))
        raise
