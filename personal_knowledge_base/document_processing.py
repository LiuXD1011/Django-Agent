import csv
import hashlib
import io
import json
import mimetypes
import re
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path

from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from .graph_rag import (
    GraphNamespace,
    build_graph_for_chunks,
    delete_knowledge_graph,
    effective_extract_config,
    graph_enabled,
    graph_repository,
)
from .chunking.config import ChunkingConfig, UNSUPPORTED_MEDIA_FILE_TYPES
from .chunking.service import split_document
from .chunking.types import ChunkDiagnostics, ChunkingResult
from .document_parsing import ImageBlock, TextBlock, parse_document
from .model_providers import embedding, embedding_signature, extract_metadata, generate_questions, role_completion
from .multimodal import cleanup_knowledge_images, process_document_images
from .models import Chunk, Knowledge
from .search import delete_chunk_index, ensure_search_tables, index_chunk
from .wiki_ingest import enqueue_wiki_ingest


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
    config = asdict(ChunkingConfig.from_mapping(config))
    chunk_size = config["chunk_size"]
    overlap = config["chunk_overlap"]
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


def normalized_chunking_config(knowledge_base_config: Mapping | None, process_config: Mapping | None) -> dict:
    merged = dict(knowledge_base_config or {})
    process_config = process_config or {}
    if not isinstance(process_config, Mapping):
        raise ValueError("process configuration must be a mapping")

    override = process_config.get("chunking_config")
    if override is None:
        override = process_config.get("chunkingConfig")
    if override is not None:
        if not isinstance(override, Mapping):
            raise ValueError("process chunking configuration must be a mapping")
        merged.update(override)
    return asdict(ChunkingConfig.from_mapping(merged))


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
    ordered = sorted(
        (
            chunk
            for chunk in chunks
            if chunk.is_enabled and chunk.chunk_type in {"text", "image_ocr", "image_caption"}
        ),
        key=lambda item: item.chunk_index,
    )
    for idx, chunk in enumerate(ordered):
        chunk.pre_chunk_id = ordered[idx - 1].id if idx else ""
        chunk.next_chunk_id = ordered[idx + 1].id if idx + 1 < len(ordered) else ""
        chunk.save(update_fields=["pre_chunk_id", "next_chunk_id", "updated_at"])


def create_chunks(knowledge: Knowledge, content: str, process_config: dict | None = None, *, index=True, clear_existing=True):
    chunking_config = normalized_chunking_config(knowledge.knowledge_base.chunking_config, process_config)
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


STRUCTURAL_CHUNKING_VERSION = "parent-child-v1"


def semantic_chunking_inputs(knowledge: Knowledge, config: ChunkingConfig) -> dict:
    if config.strategy != "semantic":
        return {}
    model_id = knowledge.embedding_model_id
    return {
        "semantic_embed": lambda texts: embedding(knowledge.tenant, texts, model_id=model_id),
        "semantic_model_signature": embedding_signature(knowledge.tenant, model_id),
    }


def validate_context_parent_indices(result) -> None:
    parent_count = len(result.parents)
    for draft in result.children:
        index = draft.context_parent_index
        if index is None:
            continue
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < parent_count:
            raise ValueError(f"invalid context parent index: {index}")


def persist_chunking_result(knowledge: Knowledge, result) -> list[Chunk]:
    validate_context_parent_indices(result)
    parent_chunks = []
    for index, draft in enumerate(result.parents):
        metadata = {"title": knowledge.title, **dict(draft.metadata or {})}
        parent_chunks.append(
            Chunk(
                tenant=knowledge.tenant,
                knowledge_base=knowledge.knowledge_base,
                knowledge=knowledge,
                content=draft.content,
                context_header=draft.context_header,
                chunk_index=index,
                chunk_type="parent_text",
                is_enabled=False,
                start_at=draft.start_at,
                end_at=draft.end_at,
                chunking_version=STRUCTURAL_CHUNKING_VERSION,
                metadata=metadata,
                content_hash=hashlib.sha256(draft.content.encode("utf-8")).hexdigest(),
            )
        )
    children = []
    with transaction.atomic():
        Chunk.objects.bulk_create(parent_chunks)
        for child_index, draft in enumerate(result.children, start=len(parent_chunks)):
            parent_id = None
            metadata = {"title": knowledge.title, **dict(draft.metadata or {})}
            if draft.context_parent_index is not None:
                parent = parent_chunks[draft.context_parent_index]
                parent_id = parent.id
                metadata = {**dict(parent.metadata or {}), **metadata}
            children.append(
                Chunk(
                    tenant=knowledge.tenant,
                    knowledge_base=knowledge.knowledge_base,
                    knowledge=knowledge,
                    content=draft.content,
                    context_header=draft.context_header,
                    context_parent_id=parent_id,
                    chunk_index=child_index,
                    chunk_type="text",
                    start_at=draft.start_at,
                    end_at=draft.end_at,
                    chunking_version=STRUCTURAL_CHUNKING_VERSION,
                    metadata=metadata,
                    content_hash=hashlib.sha256(draft.content.encode("utf-8")).hexdigest(),
                )
            )
        Chunk.objects.bulk_create(children)
    return [*parent_chunks, *children]


def create_text_chunks(knowledge: Knowledge, parsed, process_config: dict | None = None):
    chunking_config = normalized_chunking_config(knowledge.knowledge_base.chunking_config, process_config)
    for chunk in Chunk.objects.filter(knowledge=knowledge):
        delete_chunk_index(chunk.id, chunk.seq_id)
    Chunk.objects.filter(knowledge=knowledge).delete()
    chunks = []
    chunk_index = 0
    configured_size = chunking_config["chunk_size"]
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
            previous.end_at = previous.start_at + len(previous.content)
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


def process_graph(knowledge: Knowledge, chunks: list[Chunk], progress_callback=None):
    process_config = (knowledge.metadata or {}).get("process_config") or {}
    if not graph_enabled(knowledge.knowledge_base, process_config):
        return []
    if not graph_repository.available:
        return []
    delete_knowledge_graph(knowledge)
    extract_config = effective_extract_config(knowledge.knowledge_base, process_config)
    graphs = build_graph_for_chunks(chunks, extract_config, tenant=knowledge.tenant, progress_callback=progress_callback)
    if graphs:
        graph_repository.add_graph(
            GraphNamespace(knowledge_base_id=knowledge.knowledge_base_id, knowledge_id=knowledge.id),
            graphs,
        )
    return graphs


def process_knowledge(knowledge_id: str):
    from .span_tracker import SpanTracker

    knowledge = Knowledge.objects.select_related("knowledge_base", "tenant").get(
        id=knowledge_id,
        deleted_at__isnull=True,
    )
    if knowledge.parse_status == "cancelled":
        raise InterruptedError("knowledge processing cancelled")
    knowledge.parse_status = "processing"
    knowledge.save(update_fields=["parse_status", "updated_at"])

    tracker = SpanTracker(knowledge_id)
    root_span = tracker.open_attempt(attempt=1)

    post_span = None
    graph_span = None
    wiki_span = None

    def ensure_active():
        status = Knowledge.objects.filter(id=knowledge_id).values_list("parse_status", flat=True).first()
        if status == "cancelled":
            raise InterruptedError("knowledge processing cancelled")
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
        chunking_config = normalized_chunking_config(knowledge.knowledge_base.chunking_config, process_config)
        config = ChunkingConfig.from_mapping(chunking_config)
        if parsed.text_blocks:
            chunking_result = split_document(
                parsed,
                config,
                title=knowledge.title,
                **semantic_chunking_inputs(knowledge, config),
            )
        else:
            chunking_result = ChunkingResult(
                parents=[],
                children=[],
                diagnostics=ChunkDiagnostics(
                    requested_strategy=config.strategy,
                    selected_strategy=config.strategy,
                    size_statistics={"parents": {"count": 0}, "children": {"count": 0}},
                ),
            )
        validate_context_parent_indices(chunking_result)
        ensure_search_tables()
        with transaction.atomic():
            cleanup_knowledge_images(knowledge)
            for chunk in Chunk.objects.filter(knowledge=knowledge):
                delete_chunk_index(chunk.id, chunk.seq_id, ensure_tables=False)
            Chunk.objects.filter(knowledge=knowledge).delete()
            chunks = persist_chunking_result(knowledge, chunking_result)
        if chunk_span:
            tracker.end_span(
                chunk_span.span_id,
                output_data={"chunk_count": len(chunks), "diagnostics": chunking_result.diagnostics.as_dict()},
            )

        warnings = [warning.as_dict() for warning in parsed.warnings]
        graphs = []

        # Stage 3: multimodal（图片 OCR + Caption）
        multi_span = tracker.begin_stage("multimodal")
        try:
            text_children = [chunk for chunk in chunks if chunk.chunk_type == "text"]
            image_chunks, image_warnings = process_document_images(knowledge, parsed.images, text_children)
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
        ensure_active()
        _link_chunks(chunks)
        embed_span = tracker.begin_stage("embedding")
        indexed = 0
        for chunk in sorted(chunks, key=lambda item: item.chunk_index):
            if chunk.is_enabled and chunk.chunk_type in {"text", "image_ocr", "image_caption"}:
                index_chunk(chunk)
                indexed += 1
        if embed_span:
            tracker.end_span(embed_span.span_id, output_data={"indexed": indexed})

        searchable_chunks = [
            chunk for chunk in chunks if chunk.is_enabled and chunk.chunk_type in {"text", "image_ocr", "image_caption"}
        ]
        searchable_content = "\n\n".join(chunk.content for chunk in searchable_chunks)
        content = searchable_content or content
        graph_span = tracker.begin_stage("graph", input_data={"chunk_count": len(chunks)})
        graph_progress_state = {"phase": "entities", "completed_batches": 0, "total_batches": 0, "failed_batches": 0, "processed_chunks": 0}
        try:
            def graph_progress(phase, completed, total, processed, failed=0):
                ensure_active()
                graph_progress_state.update({"phase": phase, "completed_batches": completed, "total_batches": total, "failed_batches": failed, "processed_chunks": processed})
                if graph_span:
                    tracker.update_span(graph_span.span_id, graph_progress_state)
            graphs = process_graph(knowledge, searchable_chunks, progress_callback=graph_progress)
            if graph_progress_state["failed_batches"]:
                warnings.append({"stage": "graph", "message": f"{graph_progress_state['failed_batches']} graph batches degraded"})
            if graph_span:
                tracker.end_span(graph_span.span_id, graph_progress_state)
        except Exception as exc:
            if isinstance(exc, InterruptedError):
                raise
            warnings.append({"stage": "graph", "message": str(exc)})
            if graph_span:
                tracker.fail_span(graph_span.span_id, error_message=str(exc))

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
                max_tokens=400,
                enable_thinking=False,
                total_timeout=90,
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
        if post_span:
            tracker.end_span(post_span.span_id, output_data={"summary_length": len(summary or ""), "questions_count": len(questions or [])})
            post_span = None
        ensure_active()
        wiki_span = tracker.begin_stage("wiki")
        try:
            wiki_progress_state = {"completed_batches": 0, "total_batches": 0, "failed_batches": 0, "processed_pages": 0}
            def wiki_progress(completed, total, processed, failed=0):
                ensure_active()
                wiki_progress_state.update({"completed_batches": completed, "total_batches": total, "failed_batches": failed, "processed_pages": processed})
                if wiki_span:
                    tracker.update_span(wiki_span.span_id, wiki_progress_state)
            wiki_result = enqueue_wiki_ingest(knowledge, progress_callback=wiki_progress)
            if wiki_span:
                wiki_progress_state["processed_pages"] = (wiki_result or {}).get("pages", wiki_progress_state["processed_pages"])
                tracker.end_span(wiki_span.span_id, wiki_progress_state)
        except Exception as exc:
            if isinstance(exc, InterruptedError):
                raise
            wiki_result = {"pages": 0, "links": 0}
            warnings.append({"stage": "wiki", "message": str(exc)})
            if wiki_span:
                tracker.fail_span(wiki_span.span_id, error_message=str(exc))
        if wiki_progress_state["failed_batches"]:
            warnings.append({"stage": "wiki", "message": f"{wiki_progress_state['failed_batches']} wiki batches degraded"})
        metadata = knowledge.metadata or {}
        metadata.update(
            {
                "summary": summary,
                "generated_questions": questions,
                "extracted_metadata": extracted,
                "content_length": len(content),
                "image_count": len(parsed.images),
                "chunking_diagnostics": chunking_result.diagnostics.as_dict(),
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
        ensure_active()
        knowledge.parse_status = "completed"
        knowledge.summary_status = "completed"
        knowledge.processed_at = timezone.now()
        knowledge.error_message = ""
        knowledge.save(update_fields=["metadata", "description", "parse_status", "summary_status", "processed_at", "error_message", "updated_at"])

        # 完成根 span
        tracker.finalize_attempt(attempt=1)

    except Exception as exc:
        knowledge.parse_status = "cancelled" if isinstance(exc, InterruptedError) else "failed"
        knowledge.error_message = str(exc)
        knowledge.save(update_fields=["parse_status", "error_message", "updated_at"])
        # 标记失败
        if post_span:
            tracker.fail_span(post_span.span_id, error_message=str(exc))
        if root_span:
            tracker.fail_span(root_span.span_id, error_message=str(exc))
        raise
