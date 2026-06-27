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
from .model_providers import describe_image, extract_metadata, generate_questions, role_completion, transcribe_audio
from .models import Chunk, Knowledge
from .search import delete_chunk_index, index_chunk
from .wiki_ingest import enqueue_wiki_ingest


def detect_file_type(name: str) -> str:
    suffix = Path(name or "").suffix.lower().lstrip(".")
    if suffix:
        return suffix
    mime, _ = mimetypes.guess_type(name or "")
    return (mime or "text").split("/")[-1]


def extract_text_from_bytes(name: str, data: bytes) -> str:
    suffix = detect_file_type(name)
    if suffix in {"txt", "md", "markdown", "html", "htm", "json", "csv", "log"}:
        text = data.decode("utf-8", errors="ignore")
        if suffix == "json":
            try:
                return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
            except Exception:
                return text
        if suffix == "csv":
            try:
                rows = csv.reader(io.StringIO(text))
                return "\n".join(" | ".join(row) for row in rows)
            except Exception:
                return text
        return strip_html(text) if suffix in {"html", "htm"} else text
    if suffix == "pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            return data.decode("utf-8", errors="ignore")
    if suffix == "docx":
        try:
            import docx

            doc = docx.Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception:
            return data.decode("utf-8", errors="ignore")
    return data.decode("utf-8", errors="ignore")


def enrich_media_text(knowledge: Knowledge, data: bytes, content: str) -> str:
    suffix = detect_file_type(knowledge.file_name or knowledge.title)
    image_types = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "svg"}
    audio_video_types = {"mp3", "wav", "m4a", "aac", "ogg", "flac", "mp4", "mov", "avi", "mkv", "webm"}
    additions = []
    if suffix in image_types and knowledge.file_path:
        url = default_storage.url(knowledge.file_path)
        description = describe_image(url, knowledge.file_name or knowledge.title, tenant=knowledge.tenant)
        if description:
            additions.append(f"图片识别描述：{description}")
    if suffix in audio_video_types:
        transcript = transcribe_audio(knowledge.file_name or knowledge.title, data, tenant=knowledge.tenant)
        if transcript:
            additions.append(f"音视频转写：{transcript}")
    text = "\n\n".join([part for part in [content, *additions] if part])
    return text


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
        content = text[start:end].strip()
        if content:
            pieces.append((start, end, content))
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    if not pieces and text.strip():
        pieces.append((0, len(text), text.strip()))
    return pieces


def create_chunks(knowledge: Knowledge, content: str, process_config: dict | None = None):
    process_config = process_config or {}
    chunking_config = dict(knowledge.knowledge_base.chunking_config or {})
    override = process_config.get("chunking_config") or process_config.get("chunkingConfig")
    if isinstance(override, dict):
        chunking_config.update(override)
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
    for idx, chunk in enumerate(chunks):
        if idx:
            chunk.pre_chunk_id = chunks[idx - 1].id
        if idx + 1 < len(chunks):
            chunk.next_chunk_id = chunks[idx + 1].id
        chunk.save(update_fields=["pre_chunk_id", "next_chunk_id", "updated_at"])
        index_chunk(chunk)
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

    try:
        if knowledge.type != "file":
            raise ValueError("only file knowledge can be processed")

        # Stage 1: docreader（文件读取 + 文本提取）
        doc_span = tracker.begin_stage("docreader", input_data={"file_name": knowledge.file_name, "file_size": knowledge.file_size})
        with default_storage.open(knowledge.file_path, "rb") as handle:
            data = handle.read()
        content = extract_text_from_bytes(knowledge.file_name or knowledge.title, data)
        content = enrich_media_text(knowledge, data, content)
        if doc_span:
            tracker.end_span(doc_span.span_id, output_data={"content_length": len(content)})

        process_config = (knowledge.metadata or {}).get("process_config") or {}

        # Stage 2: chunking（分块）
        chunk_span = tracker.begin_stage("chunking", input_data={"chunk_size": process_config.get("chunk_size", 512)})
        chunks = create_chunks(knowledge, content, process_config)
        if chunk_span:
            tracker.end_span(chunk_span.span_id, output_data={"chunk_count": len(chunks)})

        # Stage 3: embedding（向量索引）— 在 create_chunks 中已完成
        embed_span = tracker.begin_stage("embedding")
        if embed_span:
            tracker.end_span(embed_span.span_id, output_data={"indexed": True})

        warnings = []
        graphs = []

        # Stage 4: multimodal（图提取）
        multi_span = tracker.begin_stage("multimodal")
        try:
            graphs = process_graph(knowledge, chunks)
            if multi_span:
                tracker.end_span(multi_span.span_id, output_data={"node_count": sum(len(g.get("node", [])) for g in graphs), "relation_count": sum(len(g.get("relation", [])) for g in graphs)})
        except Exception as exc:
            warnings.append({"stage": "graph", "message": str(exc)})
            if multi_span:
                tracker.fail_span(multi_span.span_id, error_message=str(exc))

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
