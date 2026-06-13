import hashlib
import json
import math
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from django.conf import settings
from django.db import connection, transaction
from openai import OpenAI
from sqlite_vec import serialize_float32

from .models import KBChunk, KBDocument
from .sqlite_search import ensure_search_tables, vector_dim


TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".jsonl",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".css",
    ".sql",
    ".xml",
    ".yaml",
    ".yml",
    ".log",
}
HTML_SUFFIXES = {".html", ".htm"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | HTML_SUFFIXES | {".pdf", ".docx", ".pptx"}


class UnsupportedDocumentError(Exception):
    pass


class DocumentParseError(Exception):
    pass


@dataclass
class Entry:
    raw: str
    content: str
    compiled: str
    title: str
    source: str
    metadata: dict = field(default_factory=dict)


@dataclass
class SearchHit:
    score: float
    chunk: KBChunk
    query: str = ""
    source_scores: dict = field(default_factory=dict)
    rerank_score: float | None = None

    def __iter__(self):
        yield self.score
        yield self.chunk


def short_hash(text):
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


def clean_text(text):
    text = (text or "").replace("\x00", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def compact_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _json_safe(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def normalize_metadata(metadata):
    return {str(key): _json_safe(value) for key, value in (metadata or {}).items()}


def split_text(text, chunk_size=800, overlap=120):
    text = clean_text(text)
    if not text:
        return []
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""],
        length_function=len,
    )
    return [chunk for chunk in (clean_text(part) for part in splitter.split_text(text)) if chunk]


def fallback_embedding(text, dim=96):
    values = [0.0] * dim
    for token in re.findall(r"[\w\u4e00-\u9fff]+", (text or "").lower()):
        idx = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % dim
        values[idx] += 1.0
    return normalize_vector(values)


def target_dim():
    return vector_dim()


def fit_vector(vector):
    dim = target_dim()
    if len(vector) == dim:
        return vector
    if len(vector) > dim:
        return vector[:dim]
    return vector + [0.0] * (dim - len(vector))


def normalize_vector(vector):
    values = [float(v) for v in fit_vector(vector)]
    norm = math.sqrt(sum(v * v for v in values))
    if not norm:
        return values
    return [v / norm for v in values]


def embed_text(text):
    if not settings.EMBEDDING_API_KEY:
        return fallback_embedding(text, dim=target_dim())
    try:
        client = OpenAI(api_key=settings.EMBEDDING_API_KEY, base_url=settings.EMBEDDING_BASE_URL)
        resp = client.embeddings.create(model=settings.EMBEDDING_MODEL, input=text or "")
        return normalize_vector(resp.data[0].embedding)
    except Exception:
        return fallback_embedding(text, dim=target_dim())


def _documents_to_entries(documents, title, source):
    entries = []
    for index, document in enumerate(documents):
        content = clean_text(getattr(document, "page_content", ""))
        if not content:
            continue
        metadata = normalize_metadata(getattr(document, "metadata", {}) or {})
        entry_title = metadata.get("title") or metadata.get("source") or title or source
        compiled = f"# {entry_title}\n{content}"
        metadata.update({"entry_index": index, "title": entry_title, "source": source})
        entries.append(
            Entry(
                raw=content,
                content=content,
                compiled=compiled,
                title=str(entry_title),
                source=source,
                metadata=metadata,
            )
        )
    if not entries:
        raise DocumentParseError("未解析出可入库文本。")
    return entries


def entries_from_text(text, title, source):
    content = clean_text(text)
    if not content:
        raise DocumentParseError("未解析出可入库文本。")
    return [
        Entry(
            raw=content,
            content=content,
            compiled=f"# {title}\n{content}",
            title=title,
            source=source,
            metadata={"title": title, "source": source},
        )
    ]


def parse_url_entries(url):
    try:
        from langchain_community.document_loaders import WebBaseLoader

        documents = WebBaseLoader(url).load()
    except Exception as exc:
        raise DocumentParseError(f"URL 解析失败：{exc}") from exc

    title = url
    for document in documents:
        metadata = getattr(document, "metadata", {}) or {}
        if metadata.get("title"):
            title = metadata["title"]
            break
    return title, _documents_to_entries(documents, title, url)


def parse_url(url):
    title, entries = parse_url_entries(url)
    return title, "\n\n".join(entry.content for entry in entries)


def _loader_for_suffix(suffix, file_path):
    if suffix in TEXT_SUFFIXES:
        from langchain_community.document_loaders import TextLoader

        return TextLoader(file_path, encoding="utf-8", autodetect_encoding=True)
    if suffix in HTML_SUFFIXES:
        from langchain_community.document_loaders import BSHTMLLoader

        return BSHTMLLoader(file_path)
    if suffix == ".pdf":
        from langchain_community.document_loaders import PyMuPDFLoader

        return PyMuPDFLoader(file_path)
    if suffix == ".docx":
        from langchain_community.document_loaders import Docx2txtLoader

        return Docx2txtLoader(file_path)
    if suffix == ".pptx":
        from langchain_community.document_loaders import UnstructuredPowerPointLoader

        return UnstructuredPowerPointLoader(file_path, mode="elements")
    raise UnsupportedDocumentError(f"暂不支持 {suffix or '无扩展名'} 格式。")


def parse_user_file_entries(user_file):
    stored = user_file.stored_file
    if not stored or not stored.file:
        raise DocumentParseError("文件内容不存在。")

    suffix = Path(stored.original_name or user_file.name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedDocumentError(f"暂不支持 {suffix or '无扩展名'} 格式。")

    try:
        with stored.file.open("rb") as stored_file:
            file_bytes = stored_file.read()
    except Exception as exc:
        raise DocumentParseError(f"读取文件失败：{exc}") from exc

    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
            tmp.write(file_bytes)
            tmp.flush()
            loader = _loader_for_suffix(suffix, tmp.name)
            documents = loader.load()
    except UnsupportedDocumentError:
        raise
    except Exception as exc:
        raise DocumentParseError(f"解析失败：{exc}") from exc

    title = user_file.name
    source = user_file.name
    entries = _documents_to_entries(documents, title, source)
    for entry in entries:
        entry.metadata.update(
            {
                "user_file_id": user_file.id,
                "filename": user_file.name,
                "suffix": suffix,
                "mime_type": user_file.mime_type,
            }
        )
    return title, entries


def parse_user_file(user_file):
    title, entries = parse_user_file_entries(user_file)
    return title, "\n\n".join(entry.content for entry in entries)


def quote_fts_query(query):
    escaped = compact_text(query).replace('"', '""')
    return f'"{escaped}"'


def delete_chunk_indexes(chunk_id):
    ensure_search_tables()
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM knowledge_kbchunk_vec WHERE chunk_id = %s", [chunk_id])
        cursor.execute("DELETE FROM knowledge_kbchunk_fts WHERE rowid = %s", [chunk_id])


def upsert_chunk_indexes(chunk, vector):
    ensure_search_tables()
    serialized_vector = serialize_float32(normalize_vector(vector))
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM knowledge_kbchunk_vec WHERE chunk_id = %s", [chunk.id])
        cursor.execute(
            "INSERT INTO knowledge_kbchunk_vec(chunk_id, kb_id, embedding) VALUES (%s, %s, %s)",
            [chunk.id, chunk.kb_id, serialized_vector],
        )
        cursor.execute("DELETE FROM knowledge_kbchunk_fts WHERE rowid = %s", [chunk.id])
        cursor.execute(
            "INSERT INTO knowledge_kbchunk_fts(rowid, content) VALUES (%s, %s)",
            [chunk.id, chunk.content],
        )


def vector_candidates(kb, query_vector, limit):
    ensure_search_tables()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT chunk_id, distance
            FROM knowledge_kbchunk_vec
            WHERE embedding MATCH %s AND kb_id = %s AND k = %s
            ORDER BY distance
            """,
            [serialize_float32(normalize_vector(query_vector)), kb.id, max(1, int(limit))],
        )
        return [(int(chunk_id), float(distance)) for chunk_id, distance in cursor.fetchall()]


def fts_candidates(kb, query, limit):
    if len(compact_text(query)) < 3:
        return []
    ensure_search_tables()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT knowledge_kbchunk_fts.rowid, bm25(knowledge_kbchunk_fts) AS rank
            FROM knowledge_kbchunk_fts
            JOIN knowledge_kbchunk AS chunk ON chunk.id = knowledge_kbchunk_fts.rowid
            WHERE knowledge_kbchunk_fts MATCH %s AND chunk.kb_id = %s
            ORDER BY rank
            LIMIT %s
            """,
            [quote_fts_query(query), kb.id, max(1, int(limit))],
        )
        return [(int(chunk_id), float(rank)) for chunk_id, rank in cursor.fetchall()]


def refresh_kb_doc_count(kb):
    kb.doc_count = kb.documents.filter(status=KBDocument.STATUS_READY).count()
    kb.save(update_fields=["doc_count", "updated_at"])


def delete_existing_file_documents(kb, user_file):
    KBDocument.objects.filter(kb=kb, user_file=user_file).delete()
    refresh_kb_doc_count(kb)


def chunk_entries(entries, chunk_size=800, overlap=120):
    chunk_payloads = []
    for entry_index, entry in enumerate(entries):
        for chunk_index, content in enumerate(split_text(entry.compiled, chunk_size=chunk_size, overlap=overlap)):
            metadata = dict(entry.metadata)
            metadata.update(
                {
                    "entry_index": entry_index,
                    "entry_chunk_index": chunk_index,
                    "title": entry.title,
                    "source": entry.source,
                }
            )
            chunk_payloads.append((content, metadata))
    return chunk_payloads


def mark_document_failed(doc, status, message):
    KBChunk.objects.filter(document=doc).delete()
    doc.status = status
    doc.error_message = str(message)[:2000]
    doc.chunk_count = 0
    doc.save(update_fields=["status", "error_message", "chunk_count", "updated_at"])
    refresh_kb_doc_count(doc.kb)
    return doc


def create_status_document(kb, source_type, source, title, status, message, user_file=None, content_hash=""):
    if source_type == KBDocument.SOURCE_FILE and user_file:
        delete_existing_file_documents(kb, user_file)
    doc = KBDocument.objects.create(
        kb=kb,
        source_type=source_type,
        source=source,
        user_file=user_file,
        title=(title or source)[:512],
        content_hash=(content_hash or "")[:64],
        status=status,
        error_message=str(message)[:2000],
        chunk_count=0,
    )
    refresh_kb_doc_count(kb)
    return doc


def ingest_entries(kb, source_type, source, title, entries, user_file=None, content_hash="", chunk_size=800, overlap=120):
    ensure_search_tables()
    if source_type == KBDocument.SOURCE_FILE and user_file:
        delete_existing_file_documents(kb, user_file)

    doc = KBDocument.objects.create(
        kb=kb,
        source_type=source_type,
        source=source,
        user_file=user_file,
        title=(title or source)[:512],
        content_hash=(content_hash or short_hash("\n".join(entry.compiled for entry in entries)))[:64],
        status=KBDocument.STATUS_PROCESSING,
    )
    chunk_payloads = chunk_entries(entries, chunk_size=chunk_size, overlap=overlap)
    if not chunk_payloads:
        return mark_document_failed(doc, KBDocument.STATUS_FAILED, "未解析出可入库文本。")

    try:
        with transaction.atomic():
            for index, (content, metadata) in enumerate(chunk_payloads):
                vector = embed_text(content)
                chunk = KBChunk.objects.create(
                    document=doc,
                    kb=kb,
                    chunk_index=index,
                    content=content,
                    metadata=metadata,
                )
                upsert_chunk_indexes(chunk, vector)
            doc.chunk_count = len(chunk_payloads)
            doc.status = KBDocument.STATUS_READY
            doc.error_message = ""
            doc.save(update_fields=["chunk_count", "status", "error_message", "updated_at"])
    except Exception as exc:
        return mark_document_failed(doc, KBDocument.STATUS_FAILED, f"索引写入失败：{exc}")

    refresh_kb_doc_count(kb)
    return doc


def ingest_text(kb, source_type, source, title, text, user_file=None, chunk_size=800, overlap=120):
    try:
        entries = entries_from_text(text, title or source, source)
    except DocumentParseError as exc:
        return create_status_document(
            kb,
            source_type,
            source,
            title or source,
            KBDocument.STATUS_FAILED,
            exc,
            user_file=user_file,
            content_hash=short_hash(text),
        )
    return ingest_entries(
        kb,
        source_type,
        source,
        title or source,
        entries,
        user_file=user_file,
        content_hash=short_hash(text),
        chunk_size=chunk_size,
        overlap=overlap,
    )


def ingest_url(kb, url):
    try:
        title, entries = parse_url_entries(url)
    except DocumentParseError as exc:
        return create_status_document(kb, KBDocument.SOURCE_URL, url, url, KBDocument.STATUS_FAILED, exc)
    return ingest_entries(kb, KBDocument.SOURCE_URL, url, title, entries)


def ingest_user_file(kb, user_file):
    try:
        title, entries = parse_user_file_entries(user_file)
    except UnsupportedDocumentError as exc:
        return create_status_document(
            kb,
            KBDocument.SOURCE_FILE,
            user_file.name,
            user_file.name,
            KBDocument.STATUS_UNSUPPORTED,
            exc,
            user_file=user_file,
            content_hash=(user_file.stored_file.content_hash if user_file.stored_file else ""),
        )
    except DocumentParseError as exc:
        return create_status_document(
            kb,
            KBDocument.SOURCE_FILE,
            user_file.name,
            user_file.name,
            KBDocument.STATUS_FAILED,
            exc,
            user_file=user_file,
            content_hash=(user_file.stored_file.content_hash if user_file.stored_file else ""),
        )
    return ingest_entries(
        kb,
        KBDocument.SOURCE_FILE,
        user_file.name,
        title,
        entries,
        user_file=user_file,
        content_hash=(user_file.stored_file.content_hash if user_file.stored_file else ""),
    )


def _extract_json_queries(text):
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    candidates = [raw]
    match = re.search(r"(\{.*\}|\[.*\])", raw, flags=re.DOTALL)
    if match:
        candidates.append(match.group(1))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            parsed = parsed.get("queries") or parsed.get("query") or []
        if isinstance(parsed, str):
            parsed = [parsed]
        if isinstance(parsed, list):
            return [compact_text(item) for item in parsed if compact_text(str(item))]
    return []


def _format_chat_history(chat_history):
    if not chat_history:
        return ""
    lines = []
    for message in list(chat_history)[-6:]:
        role = getattr(message, "role", "")
        content = compact_text(getattr(message, "content", ""))
        if content:
            lines.append(f"{role or 'message'}: {content}")
    return "\n".join(lines)


def rewrite_rag_queries(query, chat_history=None):
    query = compact_text(query)
    if not query:
        return []
    if not settings.LLM_API_KEY:
        return [query]
    try:
        client = OpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)
        history = _format_chat_history(chat_history)
        resp = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是 RAG 检索 query 改写器。根据用户问题和少量对话历史，"
                        "生成 1 到 3 个适合知识库语义检索的中文查询。只返回 JSON："
                        "{\"queries\":[\"...\"]}。"
                    ),
                },
                {"role": "user", "content": f"对话历史：\n{history or '无'}\n\n用户问题：{query}"},
            ],
            temperature=0,
        )
        content = resp.choices[0].message.content or ""
        rewritten = _extract_json_queries(content)
    except Exception:
        rewritten = []
    queries = []
    for item in rewritten or [query]:
        item = compact_text(item)
        if item and item not in queries:
            queries.append(item)
        if len(queries) >= 3:
            break
    return queries or [query]


def _candidate_hits(kb, query, top_k, chat_history=None):
    queries = rewrite_rag_queries(query, chat_history=chat_history)
    result_limit = max(1, int(top_k))
    candidate_limit = result_limit * 4
    scores = {}
    source_scores = {}

    for rewritten_query in queries:
        qvec = embed_text(rewritten_query)
        for rank, (chunk_id, distance) in enumerate(vector_candidates(kb, qvec, candidate_limit), 1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + (1.0 / rank)
            source_scores.setdefault(chunk_id, {})["vector"] = {
                "query": rewritten_query,
                "rank": rank,
                "distance": distance,
            }
        for rank, (chunk_id, fts_rank) in enumerate(fts_candidates(kb, rewritten_query, candidate_limit), 1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + (0.5 / rank)
            source_scores.setdefault(chunk_id, {})["fts"] = {
                "query": rewritten_query,
                "rank": rank,
                "rank_score": fts_rank,
            }

    if not scores:
        return []

    max_candidates = min(100, result_limit * 8)
    ordered_ids = [
        chunk_id
        for chunk_id, _score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:max_candidates]
    ]
    chunks = {
        chunk.id: chunk
        for chunk in KBChunk.objects.filter(id__in=ordered_ids).select_related("document", "kb")
    }
    return [
        SearchHit(
            score=scores[chunk_id],
            chunk=chunks[chunk_id],
            query=(source_scores.get(chunk_id, {}).get("vector") or source_scores.get(chunk_id, {}).get("fts") or {}).get(
                "query", query
            ),
            source_scores=source_scores.get(chunk_id, {}),
        )
        for chunk_id in ordered_ids
        if chunk_id in chunks
    ]


def rerank_hits(query, hits, top_k):
    result_limit = max(1, int(top_k))
    if not hits:
        return []
    api_key = getattr(settings, "RERANK_API_KEY", "") or getattr(settings, "EMBEDDING_API_KEY", "")
    if not api_key:
        return hits[:result_limit]

    try:
        payload = {
            "model": settings.RERANK_MODEL,
            "input": {
                "query": {"text": compact_text(query)},
                "documents": [{"text": hit.chunk.content} for hit in hits],
            },
            "parameters": {
                "return_documents": False,
                "top_n": result_limit,
            },
        }
        with httpx.Client(timeout=30) as client:
            response = client.post(
                settings.RERANK_BASE_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
        results = response.json().get("output", {}).get("results", [])
        reranked = []
        for item in results:
            index = int(item["index"])
            if 0 <= index < len(hits):
                hit = hits[index]
                hit.rerank_score = float(item.get("relevance_score", 0.0))
                reranked.append(hit)
        if reranked:
            return reranked[:result_limit]
    except Exception:
        pass
    return hits[:result_limit]


def search(kb, query, top_k=6, chat_history=None):
    hits = _candidate_hits(kb, query, top_k=top_k, chat_history=chat_history)
    return rerank_hits(query, hits, top_k=top_k)


def _hit_parts(hit):
    if isinstance(hit, SearchHit):
        return hit.score, hit.chunk, hit.rerank_score
    score, chunk = hit
    return score, chunk, None


def references_context(hits):
    lines = []
    for index, hit in enumerate(hits, 1):
        score, chunk, rerank_score = _hit_parts(hit)
        score_text = f"{score:.4f}"
        if rerank_score is not None:
            score_text += f", rerank={rerank_score:.4f}"
        lines.append(
            "\n".join(
                [
                    f"[{index}] title: {chunk.document.title}",
                    f"source: {chunk.document.source}",
                    f"chunk_id: {chunk.id}",
                    f"score: {score_text}",
                    "content:",
                    chunk.content,
                ]
            )
        )
    return "\n\n".join(lines)


def build_answer(query, hits, wiki_hits=None):
    if not hits and not wiki_hits:
        return "知识库中暂无足够信息来回答该问题。"
    if wiki_hits:
        from . import wiki_services

        context = wiki_services.combined_references_context(wiki_hits, hits)
    else:
        context = references_context(hits)
    if not settings.LLM_API_KEY:
        return f"未配置 LLM_API_KEY，已返回最相关片段。\n\n问题：{query}\n\n{context[:1800]}"
    try:
        client = OpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)
        resp = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是个人知识库问答助手。优先基于 Wiki references 理解结构化结论，"
                        "再用原文 chunk references 追溯细节。只基于提供的 references 回答；"
                        "如果 references 不足以支持结论，就明确说明资料不足。"
                        "回答要简洁、中文、可追溯。"
                    ),
                },
                {"role": "user", "content": f"用户问题：{query}\n\nreferences:\n{context}"},
            ],
            temperature=0.2,
        )
        return resp.choices[0].message.content or ""
    except Exception as exc:
        return f"模型调用失败，以下是相关片段：\n\n{context[:1800]}\n\n错误：{exc}"


def refs_payload(hits):
    refs = []
    for hit in hits:
        score, chunk, rerank_score = _hit_parts(hit)
        refs.append(
            {
                "type": "chunk",
                "kb_id": chunk.kb.kb_id,
                "document_id": chunk.document_id,
                "chunk_id": chunk.id,
                "title": chunk.document.title,
                "source": chunk.document.source,
                "status": chunk.document.status,
                "score": round(float(score), 4),
                "rerank_score": None if rerank_score is None else round(float(rerank_score), 4),
            }
        )
    return refs


def document_status_label(status):
    return {
        "not_ingested": "未入库",
        KBDocument.STATUS_PROCESSING: "入库中",
        KBDocument.STATUS_READY: "已入库",
        KBDocument.STATUS_FAILED: "解析失败",
        KBDocument.STATUS_UNSUPPORTED: "不支持",
    }.get(status, status or "未入库")


def document_status_map(kb, files):
    file_ids = [file.id for file in files if not file.is_folder]
    latest_docs = {}
    if file_ids:
        docs = KBDocument.objects.filter(kb=kb, user_file_id__in=file_ids).order_by("user_file_id", "-updated_at")
        for doc in docs:
            latest_docs.setdefault(doc.user_file_id, doc)

    status_by_file = {}
    for file in files:
        doc = latest_docs.get(file.id)
        if doc:
            status = doc.status
            status_by_file[file.id] = {
                "status": status,
                "label": document_status_label(status),
                "message": doc.error_message,
                "chunk_count": doc.chunk_count,
                "document": doc,
            }
        else:
            status_by_file[file.id] = {
                "status": "not_ingested",
                "label": document_status_label("not_ingested"),
                "message": "",
                "chunk_count": 0,
                "document": None,
            }
    return status_by_file


def decorate_file_statuses(kb, files):
    items = list(files)
    if not kb:
        return items
    status_by_file = document_status_map(kb, items)
    for item in items:
        info = status_by_file.get(item.id, {})
        item.kb_status = info.get("status", "not_ingested")
        item.kb_status_label = info.get("label", document_status_label("not_ingested"))
        item.kb_status_message = info.get("message", "")
        item.kb_chunk_count = info.get("chunk_count", 0)
    return items
