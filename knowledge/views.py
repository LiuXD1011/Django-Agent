import hashlib
import json
import logging
import mimetypes
import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import FileResponse, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.csrf import csrf_exempt

from personal_knowledge_base.authentication import require_auth
from personal_knowledge_base.document_processing import detect_file_type, is_unsupported_media_file, process_knowledge
from personal_knowledge_base.document_processing import process_graph as rebuild_knowledge_graph
from personal_knowledge_base.graph_rag import (
    DEFAULT_EXTRACT_CONFIG,
    delete_kb_graph,
    delete_knowledge_graph,
    validate_extract_config,
)
from personal_knowledge_base.model_providers import safe_json
from personal_knowledge_base.models import (
    Chunk,
    Knowledge,
    KnowledgeBase,
    KnowledgeTag,
)
from personal_knowledge_base.responses import fail, ok
from personal_knowledge_base.search import delete_chunk_index, hybrid_search, index_chunk
from personal_knowledge_base.serializers import (
    DEFAULT_INDEXING_STRATEGY,
    chunk_dict,
    kb_dict,
    knowledge_dict,
    normalize_indexing_strategy,
    tag_dict,
)
from personal_knowledge_base.tasks import enqueue
from personal_knowledge_base.wiki_ingest import (
    cleanup_wiki_for_kb,
    cleanup_wiki_for_knowledge,
    enqueue_wiki_ingest,
    prepare_wiki_for_reparse,
    sync_manual_page_links,
)

logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

KNOWLEDGE_TYPE_VALUES = {"file"}
PROCESSING_STATUSES = {"pending", "processing", "finalizing"}
KB_TYPES = {"document"}


# ── Helper Functions ─────────────────────────────────────────────────────────

def parse_body(request):
    if request.content_type and request.content_type.startswith("multipart/"):
        return request.POST.dict()
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except Exception:
        return {}


def auth_context(request):
    try:
        return require_auth(request)
    except PermissionError:
        return None, None


def bounded_int(value, default, minimum=None, maximum=None):
    try:
        number = int(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        number = default
    if minimum is not None:
        number = max(number, minimum)
    if maximum is not None:
        number = min(number, maximum)
    return number


def paginate(qs, request):
    page_size = bounded_int(request.GET.get("page_size", request.GET.get("limit", 20)), 20, 1, 200)
    if "offset" in request.GET and "page" not in request.GET:
        offset = bounded_int(request.GET.get("offset"), 0, 0)
        page = offset // page_size + 1
    else:
        page = bounded_int(request.GET.get("page"), 1, 1)
        offset = (page - 1) * page_size
    total = qs.count()
    return qs[offset : offset + page_size], {"page": page, "page_size": page_size, "total": total}


def list_response(items, meta=None, aliases=None):
    payload = {"items": items, "data": items}
    for alias in aliases or []:
        payload[alias] = items
    if meta:
        payload.update(meta)
    return payload


def csv_values(value):
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        values = value
    else:
        values = str(value).split(",")
    return [str(item).strip() for item in values if str(item).strip()]


def normalize_ids(data):
    ids = data.get("ids") or data.get("knowledge_ids") or data.get("knowledgeIds") or []
    if isinstance(ids, str):
        ids = csv_values(ids)
    seen = set()
    result = []
    for item in ids:
        item = str(item).strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def extract_process_config(data, default=None):
    for key in ["process_config", "processConfig"]:
        if key in data:
            from personal_knowledge_base.model_providers import safe_json
            return safe_json(data.get(key))
    return default


def with_process_config(metadata, process_config, include_empty=False):
    metadata = dict(metadata or {})
    if process_config is None and not include_empty:
        return metadata
    config = process_config or {}
    metadata["process_config"] = config
    metadata["process_overrides"] = config
    return metadata


def normalize_kb_payload(data, existing=None, partial=False):
    from personal_knowledge_base.model_providers import safe_json

    kb_type = data.get("type", existing.type if existing else "document")
    if kb_type == "faq":
        return None, fail("FAQ knowledge bases are no longer supported", 400)
    if kb_type not in KB_TYPES and kb_type != "wiki":
        return None, fail("unsupported knowledge base type", 400)

    config = data.get("config") or data
    existing_strategy = existing.indexing_strategy if existing else None
    raw_strategy = config.get("indexing_strategy", existing_strategy if partial else DEFAULT_INDEXING_STRATEGY)
    strategy = normalize_indexing_strategy(raw_strategy, kb_type)
    if not any(strategy.values()):
        return None, fail("at least one indexing strategy must be enabled", 400)

    wiki_config = config.get("wiki_config", existing.wiki_config if existing else None)
    if strategy["wiki_enabled"] and wiki_config is None:
        wiki_config = {}
    extract_config = config.get("extract_config", existing.extract_config if existing else None)
    if strategy["graph_enabled"]:
        graph_config = extract_config if isinstance(extract_config, dict) and extract_config else DEFAULT_EXTRACT_CONFIG
        extract_config = {**DEFAULT_EXTRACT_CONFIG, **graph_config, "enabled": True}
    elif isinstance(extract_config, dict):
        extract_config = {**extract_config, "enabled": False}
    error = validate_extract_config(extract_config)
    if error:
        return None, fail(error, 400)

    payload = {
        "type": "document",
        "indexing_strategy": strategy,
        "wiki_config": wiki_config,
        "extract_config": extract_config,
    }
    return payload, None


def delete_knowledge_content(item, cleanup_wiki=True):
    if cleanup_wiki:
        try:
            cleanup_wiki_for_knowledge(item)
        except Exception:
            pass
    delete_knowledge_graph(item)
    for chunk in Chunk.objects.filter(knowledge=item):
        delete_chunk_index(chunk.id, chunk.seq_id)
    Chunk.objects.filter(knowledge=item).delete()


def apply_knowledge_filters(qs, params):
    keyword = params.get("keyword") or params.get("q") or params.get("query")
    if keyword:
        qs = qs.filter(
            Q(title__icontains=keyword)
            | Q(file_name__icontains=keyword)
            | Q(source__icontains=keyword)
            | Q(description__icontains=keyword)
            | Q(metadata__content__icontains=keyword)
        )

    tag_id = params.get("tag_id") or params.get("tagId")
    if tag_id:
        qs = qs.filter(tag_id=tag_id)

    parse_status = params.get("parse_status") or params.get("parseStatus")
    statuses = csv_values(parse_status)
    if len(statuses) == 1:
        qs = qs.filter(parse_status=statuses[0])
    elif statuses:
        qs = qs.filter(parse_status__in=statuses)

    file_values = csv_values(params.get("file_types") or params.get("file_type") or params.get("fileType"))
    if file_values:
        file_query = Q()
        for value in file_values:
            if value in KNOWLEDGE_TYPE_VALUES:
                file_query |= Q(type=value)
            else:
                file_query |= Q(file_type=value)
        qs = qs.filter(file_query)

    source = params.get("source") or params.get("channel")
    if source:
        if source in KNOWLEDGE_TYPE_VALUES:
            qs = qs.filter(type=source)
        else:
            qs = qs.filter(Q(channel=source) | Q(source=source))

    start_time = params.get("start_time") or params.get("startTime")
    end_time = params.get("end_time") or params.get("endTime")
    if start_time:
        qs = qs.filter(created_at__gte=start_time)
    if end_time:
        qs = qs.filter(created_at__lte=end_time)
    return qs


def bool_from_value(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on", "enabled"}


def default_chunk_config():
    return {"chunk_size": 512, "chunk_overlap": 50, "split_markers": ["\n\n", "\n", "。"], "keep_separator": True}


# ── Knowledge Base Views ─────────────────────────────────────────────────────

@csrf_exempt
def knowledge_bases(request, kb_id=None):
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    if kb_id:
        kb = get_object_or_404(KnowledgeBase, id=kb_id, deleted_at__isnull=True)
        if request.method == "GET":
            return ok(kb_dict(kb))
        if request.method == "DELETE":
            delete_kb_graph(kb)
            cleanup_wiki_for_kb(kb)
            kb.deleted_at = timezone.now()
            kb.save(update_fields=["deleted_at", "updated_at"])
            return ok({})
        data = parse_body(request)
        config = data.get("config") or data
        normalized, error = normalize_kb_payload(data, kb, partial=True)
        if error:
            return error
        for field in ["name", "description"]:
            if field in data:
                setattr(kb, field, data[field])
        for field in ["chunking_config", "image_processing_config"]:
            if field in config:
                setattr(kb, field, config[field])
        for field, value in normalized.items():
            setattr(kb, field, value)
        kb.save()
        return ok(kb_dict(kb))
    if request.method == "GET":
        qs = KnowledgeBase.objects.filter(tenant=tenant, deleted_at__isnull=True, is_temporary=False).order_by("-is_pinned", "-updated_at")
        creator = request.GET.get("creator")
        keyword = request.GET.get("keyword") or request.GET.get("q") or request.GET.get("query")
        kb_type = request.GET.get("type")
        if creator == "mine" and user:
            qs = qs.filter(creator_id=user.id)
        elif creator == "others" and user:
            qs = qs.exclude(creator_id=user.id)
        if keyword:
            qs = qs.filter(Q(name__icontains=keyword) | Q(description__icontains=keyword))
        if kb_type:
            if kb_type == "faq":
                qs = qs.none()
            elif kb_type == "wiki":
                qs = qs.filter(Q(type="wiki") | Q(indexing_strategy__wiki_enabled=True))
            else:
                qs = qs.filter(type=kb_type)
        page, meta = paginate(qs, request)
        items = [kb_dict(kb) for kb in page]
        for item in items:
            if user and item.get("creator_id") == user.id:
                item["creator_name"] = user.username
        return ok(list_response(items, meta, ["knowledge_bases"]))
    data = parse_body(request)
    normalized, error = normalize_kb_payload(data)
    if error:
        return error
    kb = KnowledgeBase.objects.create(
        tenant=tenant,
        name=data.get("name", "未命名知识库"),
        description=data.get("description", ""),
        type=normalized["type"],
        chunking_config=data.get("chunking_config") or default_chunk_config(),
        image_processing_config=data.get("image_processing_config") or {"enable_multimodal": False, "model_id": ""},
        embedding_model_id=data.get("embedding_model_id", ""),
        summary_model_id=data.get("summary_model_id", ""),
        storage_provider_config=data.get("storage_provider_config") or {"provider": "local"},
        vlm_config=data.get("vlm_config") or {},
        asr_config=data.get("asr_config"),
        extract_config=normalized["extract_config"],
        wiki_config=normalized["wiki_config"],
        indexing_strategy=normalized["indexing_strategy"],
        vector_store_id=data.get("vector_store_id") or "",
        creator_id=user.id if user else "",
    )
    return ok(kb_dict(kb), status=201)


@csrf_exempt
def kb_pin(request, kb_id):
    kb = get_object_or_404(KnowledgeBase, id=kb_id)
    if request.method == "DELETE":
        kb.is_pinned = False
    elif request.method in {"POST", "PUT"}:
        data = parse_body(request)
        kb.is_pinned = bool_from_value(data.get("is_pinned"), not kb.is_pinned)
    else:
        kb.is_pinned = not kb.is_pinned
    kb.pinned_at = timezone.now() if kb.is_pinned else None
    kb.save(update_fields=["is_pinned", "pinned_at", "updated_at"])
    return ok(kb_dict(kb))


@csrf_exempt
def kb_copy(request):
    user, tenant = auth_context(request)
    data = parse_body(request)
    src = get_object_or_404(KnowledgeBase, id=data.get("source_id"))
    clone = KnowledgeBase.objects.create(
        tenant=tenant,
        name=f"{src.name} copy",
        description=src.description,
        type=src.type,
        chunking_config=src.chunking_config,
        image_processing_config=src.image_processing_config,
        embedding_model_id=src.embedding_model_id,
        summary_model_id=src.summary_model_id,
        storage_provider_config=src.storage_provider_config,
        vlm_config=src.vlm_config,
        asr_config=src.asr_config,
        extract_config=src.extract_config,
        wiki_config=src.wiki_config,
        indexing_strategy=normalize_indexing_strategy(src.indexing_strategy, src.type),
        creator_id=user.id if user else "",
    )
    return ok({"knowledge_base": kb_dict(clone), "task_id": ""})


def kb_move_targets(request, kb_id):
    _, tenant = auth_context(request)
    source = get_object_or_404(KnowledgeBase, id=kb_id)
    qs = KnowledgeBase.objects.filter(tenant=tenant, type=source.type, deleted_at__isnull=True).exclude(id=kb_id)
    return ok({"items": [kb_dict(kb) for kb in qs]})


# ── Knowledge Views ──────────────────────────────────────────────────────────

@csrf_exempt
def knowledge_collection(request, kb_id):
    user, tenant = auth_context(request)
    kb = get_object_or_404(KnowledgeBase, id=kb_id)
    if request.method == "GET":
        qs = Knowledge.objects.filter(knowledge_base=kb, deleted_at__isnull=True).order_by("-updated_at")
        qs = apply_knowledge_filters(qs, request.GET)
        page, meta = paginate(qs, request)
        items = [knowledge_dict(item) for item in page]
        return ok(list_response(items, meta, ["knowledge"]))
    if request.method == "DELETE":
        for item in Knowledge.objects.filter(knowledge_base=kb):
            delete_knowledge_content(item)
        Knowledge.objects.filter(knowledge_base=kb).update(deleted_at=timezone.now())
        cleanup_wiki_for_kb(kb)
        return ok({})
    return fail("method not allowed", 405)


@csrf_exempt
def knowledge_file(request, kb_id):
    _, tenant = auth_context(request)
    kb = get_object_or_404(KnowledgeBase, id=kb_id)
    uploaded = request.FILES.get("file")
    if not uploaded:
        return fail("file is required", 400)
    file_type = detect_file_type(uploaded.name)
    if is_unsupported_media_file(uploaded.name):
        return fail("不支持音频或视频文件", 400, "unsupported_file_type", {"file_name": uploaded.name, "file_type": file_type})
    data = uploaded.read()
    file_hash = hashlib.sha256(data).hexdigest()
    existing = Knowledge.objects.filter(
        knowledge_base=kb,
        file_hash=file_hash,
        file_name=uploaded.name,
        deleted_at__isnull=True,
    ).order_by("-created_at").first()
    if existing:
        return ok({"knowledge": knowledge_dict(existing), "task_id": "", "deduplicated": True}, status=200)
    path = default_storage.save(f"tenant-{tenant.id}/{kb.id}/{uuid.uuid4()}-{uploaded.name}", ContentFile(data))

    import time as _time
    max_retries = 3
    item = None
    for attempt in range(max_retries):
        try:
            with transaction.atomic():
                existing = Knowledge.objects.select_for_update().filter(
                    knowledge_base=kb,
                    file_hash=file_hash,
                    file_name=uploaded.name,
                    deleted_at__isnull=True,
                ).order_by("-created_at").first()
                if existing:
                    default_storage.delete(path)
                    return ok({"knowledge": knowledge_dict(existing), "task_id": "", "deduplicated": True}, status=200)
                item = Knowledge.objects.create(
                    tenant=tenant,
                    knowledge_base=kb,
                    type="file",
                    title=request.POST.get("fileName") or uploaded.name,
                    source=uploaded.name,
                    parse_status="pending",
                    file_name=uploaded.name,
                    file_type=file_type,
                    file_size=len(data),
                    file_path=path,
                    file_hash=file_hash,
                    storage_size=len(data),
                    tag_id=request.POST.get("tag_id", ""),
                    metadata=with_process_config({}, safe_json(request.POST.get("process_config")), include_empty=True),
                )
            break
        except IntegrityError:
            default_storage.delete(path)
            existing = Knowledge.objects.filter(
                knowledge_base=kb,
                file_hash=file_hash,
                file_name=uploaded.name,
                deleted_at__isnull=True,
            ).order_by("-created_at").first()
            if existing:
                return ok({"knowledge": knowledge_dict(existing), "task_id": "", "deduplicated": True}, status=200)
            raise
        except Exception as exc:
            if "database is locked" in str(exc) and attempt < max_retries - 1:
                _time.sleep(2 * (attempt + 1))
                continue
            default_storage.delete(path)
            raise

    if item is None:
        default_storage.delete(path)
        return fail("upload failed after retries", 500)
    task = enqueue("process_knowledge", lambda: (process_knowledge(item.id), {"knowledge_id": item.id})[1], {"knowledge_id": item.id})
    return ok({"knowledge": knowledge_dict(item), "task_id": task.id}, status=201)


@csrf_exempt
def knowledge_detail(request, knowledge_id):
    item = get_object_or_404(Knowledge, id=knowledge_id)
    if request.method == "GET":
        return ok(knowledge_dict(item))
    if request.method == "DELETE":
        delete_knowledge_content(item)
        item.deleted_at = timezone.now()
        item.save(update_fields=["deleted_at", "updated_at"])
        return ok({"id": knowledge_id, "task_id": ""})
    data = parse_body(request)
    for field in ["title", "description", "enable_status", "tag_id"]:
        if field in data:
            setattr(item, field, data[field])
    item.save()
    return ok(knowledge_dict(item))


@csrf_exempt
def knowledge_reparse(request, knowledge_id):
    item = get_object_or_404(Knowledge, id=knowledge_id)
    data = parse_body(request)
    prepare_wiki_for_reparse(item)
    delete_knowledge_content(item, cleanup_wiki=False)
    process_config = extract_process_config(data)
    update_fields = ["parse_status", "updated_at"]
    if process_config is not None:
        item.metadata = with_process_config(item.metadata, process_config)
        update_fields.append("metadata")
    item.parse_status = "pending"
    item.save(update_fields=update_fields)
    task = enqueue("process_knowledge", lambda: (process_knowledge(item.id), {"knowledge_id": item.id})[1], {"knowledge_id": item.id})
    return ok({"knowledge": knowledge_dict(item), "task_id": task.id})


@csrf_exempt
def knowledge_cancel(request, knowledge_id):
    item = get_object_or_404(Knowledge, id=knowledge_id)
    item.parse_status = "cancelled"
    item.save(update_fields=["parse_status", "updated_at"])
    return ok(knowledge_dict(item))


@csrf_exempt
def knowledge_batch_delete(request, kb_id=None):
    data = parse_body(request)
    source_kb_id = kb_id or data.get("kb_id") or data.get("knowledge_base_id") or data.get("source_kb_id")
    ids = normalize_ids(data)
    count = 0
    qs = Knowledge.objects.filter(id__in=ids, deleted_at__isnull=True)
    if source_kb_id:
        qs = qs.filter(knowledge_base_id=source_kb_id)
    for item in qs:
        delete_knowledge_content(item)
        item.deleted_at = timezone.now()
        item.save(update_fields=["deleted_at", "updated_at"])
        count += 1
    return ok({"deleted": count, "deleted_count": count, "ids": ids, "kb_id": source_kb_id, "task_id": ""})


@csrf_exempt
def knowledge_move(request, kb_id=None):
    data = parse_body(request)
    ids = normalize_ids(data)
    source_kb_id = kb_id or data.get("source_kb_id") or data.get("kb_id")
    target_id = data.get("target_kb_id") or data.get("target_knowledge_base_id") or data.get("knowledge_base_id")
    target = get_object_or_404(KnowledgeBase, id=target_id)
    moved = 0
    qs = Knowledge.objects.filter(id__in=ids, deleted_at__isnull=True)
    if source_kb_id:
        qs = qs.filter(knowledge_base_id=source_kb_id)
    for item in qs:
        old_kb_id = item.knowledge_base_id
        cleanup_wiki_for_knowledge(item)
        delete_knowledge_graph(item)
        item.knowledge_base = target
        item.tenant = target.tenant
        item.save(update_fields=["knowledge_base", "tenant", "updated_at"])
        chunks = []
        for chunk in Chunk.objects.filter(knowledge=item):
            delete_chunk_index(chunk.id, chunk.seq_id)
            chunk.knowledge_base = target
            chunk.tenant = target.tenant
            chunk.relation_chunks = None
            chunk.indirect_relation_chunks = None
            chunk.save(update_fields=["knowledge_base", "tenant", "updated_at"])
            index_chunk(chunk)
            chunks.append(chunk)
        try:
            rebuild_knowledge_graph(item, chunks)
        except Exception:
            metadata = dict(item.metadata or {})
            warnings = list(metadata.get("processing_warnings") or [])
            warnings.append({"stage": "graph_move_rebuild", "message": f"graph rebuild skipped after move from {old_kb_id}"})
            metadata["processing_warnings"] = warnings
            item.metadata = metadata
            item.save(update_fields=["metadata", "updated_at"])
        try:
            enqueue_wiki_ingest(item)
        except Exception:
            metadata = dict(item.metadata or {})
            warnings = list(metadata.get("processing_warnings") or [])
            warnings.append({"stage": "wiki_move_rebuild", "message": f"wiki rebuild skipped after move from {old_kb_id}"})
            metadata["processing_warnings"] = warnings
            item.metadata = metadata
            item.save(update_fields=["metadata", "updated_at"])
        moved += 1
    return ok({"moved": moved, "knowledge_count": moved, "source_kb_id": source_kb_id, "target_kb_id": target.id, "target_knowledge_base_id": target.id, "task_id": "", "message": "Knowledge move task started"})


def knowledge_batch(request):
    ids = request.GET.get("ids", "")
    items = Knowledge.objects.filter(id__in=[x for x in ids.split(",") if x], deleted_at__isnull=True)
    return ok({"items": [knowledge_dict(item) for item in items]})


def knowledge_search(request):
    user, tenant = auth_context(request)
    if not tenant:
        return fail("unauthorized", 401)
    qs = Knowledge.objects.filter(tenant=tenant, deleted_at__isnull=True)
    qs = apply_knowledge_filters(qs, request.GET)
    page, meta = paginate(qs, request)
    return ok({"items": [knowledge_dict(item) for item in page], **meta})


@csrf_exempt
def knowledge_search_post(request):
    _, tenant = auth_context(request)
    data = parse_body(request)
    kb_ids = data.get("knowledge_base_ids") or data.get("kb_ids") or []
    query = data.get("query") or data.get("q") or ""
    top_k = bounded_int(data.get("top_k"), 10, 1, 100)
    results = hybrid_search(tenant.id, kb_ids, query, top_k)
    return ok({"items": results, "results": results})


def knowledge_stats(request, kb_id):
    kb = get_object_or_404(KnowledgeBase, id=kb_id)
    qs = Knowledge.objects.filter(knowledge_base=kb, deleted_at__isnull=True)
    total = qs.count()
    status_counts = {}
    for status in ["pending", "processing", "finalizing", "completed", "failed", "cancelled"]:
        status_counts[status] = qs.filter(parse_status=status).count()
    processing = qs.filter(parse_status__in=PROCESSING_STATUSES).count()
    chunk_count = Chunk.objects.filter(knowledge_base=kb, deleted_at__isnull=True).count()
    storage_size = sum(size or 0 for size in qs.values_list("storage_size", flat=True))
    return ok(
        {
            "knowledge_base_id": kb.id,
            "knowledge_count": total,
            "document_count": total,
            "total": total,
            "completed": status_counts["completed"],
            "processing": processing,
            "pending": status_counts["pending"],
            "failed": status_counts["failed"],
            "cancelled": status_counts["cancelled"],
            "chunk_count": chunk_count,
            "storage_size": storage_size,
            "status_counts": status_counts,
            "is_processing": processing > 0,
        }
    )


def knowledge_spans(request, knowledge_id):
    from personal_knowledge_base.span_tracker import SpanTracker

    item = get_object_or_404(Knowledge, id=knowledge_id)
    tracker = SpanTracker(knowledge_id)
    spans = tracker.get_spans()

    if not spans:
        return ok({"items": [{"name": "parse", "status": item.parse_status, "started_at": item.created_at.isoformat(), "finished_at": item.processed_at.isoformat() if item.processed_at else None}]})

    return ok({"items": spans})


def knowledge_download(request, knowledge_id):
    item = get_object_or_404(Knowledge, id=knowledge_id)
    filename = item.file_name or f"{item.title or item.id}.txt"
    if not item.file_path:
        response = HttpResponse(item.metadata.get("content", ""), content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = content_disposition_header(True, filename)
        return response
    return FileResponse(default_storage.open(item.file_path, "rb"), as_attachment=True, filename=filename)


def knowledge_preview(request, knowledge_id):
    item = get_object_or_404(Knowledge, id=knowledge_id)
    filename = item.file_name or f"{item.title or item.id}.txt"
    file_type = detect_file_type(filename)
    inline_types = {
        "txt", "md", "markdown", "csv", "json", "log", "pdf",
        "jpg", "jpeg", "png", "gif", "bmp", "webp",
    }
    if item.file_path and file_type in inline_types:
        content_type = mimetypes.guess_type(filename)[0] or ("text/plain; charset=utf-8" if file_type in {"txt", "md", "markdown", "csv", "json", "log"} else "application/octet-stream")
        response = FileResponse(default_storage.open(item.file_path, "rb"), as_attachment=False, filename=filename, content_type=content_type)
        response["Content-Disposition"] = content_disposition_header(False, filename)
        return response

    chunks = Chunk.objects.filter(knowledge=item, deleted_at__isnull=True).order_by("chunk_index")
    preview_text = "\n\n".join(chunk.content for chunk in chunks)
    if not preview_text:
        metadata = item.metadata or {}
        preview_text = metadata.get("content") or metadata.get("summary") or item.error_message or "该文件暂无可预览文本。"
    response = HttpResponse(preview_text, content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = content_disposition_header(False, f"{Path(filename).stem or item.title}.txt")
    return response


# ── Chunk Views ──────────────────────────────────────────────────────────────

@csrf_exempt
def chunks_collection(request, knowledge_id=None, chunk_id=None):
    if knowledge_id == "by-id" and chunk_id:
        knowledge_id = None
    if chunk_id and not knowledge_id:
        chunk = get_object_or_404(Chunk, id=chunk_id)
        if request.method == "GET":
            return ok(chunk_dict(chunk))
        if request.method == "DELETE":
            delete_knowledge_graph(chunk.knowledge)
            delete_chunk_index(chunk.id, chunk.seq_id)
            chunk.delete()
            return ok({})
    if knowledge_id and chunk_id:
        chunk = get_object_or_404(Chunk, id=chunk_id, knowledge_id=knowledge_id)
        if request.method == "GET":
            return ok(chunk_dict(chunk))
        if request.method == "DELETE":
            delete_knowledge_graph(chunk.knowledge)
            delete_chunk_index(chunk.id, chunk.seq_id)
            chunk.delete()
            return ok({})
        data = parse_body(request)
        chunk.content = data.get("content", chunk.content)
        chunk.is_enabled = data.get("is_enabled", chunk.is_enabled)
        chunk.metadata = data.get("metadata", chunk.metadata)
        chunk.save()
        index_chunk(chunk)
        return ok(chunk_dict(chunk))
    if knowledge_id and request.method == "GET":
        chunks = Chunk.objects.filter(knowledge_id=knowledge_id).order_by("chunk_index")
        chunk_type = request.GET.get("chunk_type")
        if chunk_type:
            chunks = chunks.filter(chunk_type=chunk_type)
        page, meta = paginate(chunks, request)
        items = [chunk_dict(c) for c in page]
        return ok(list_response(items, meta, ["chunks"]))
    if knowledge_id and request.method == "DELETE":
        item = Knowledge.objects.filter(id=knowledge_id).first()
        if item:
            delete_knowledge_content(item)
        return ok({})
    return fail("not found", 404)


# ── Tag Views ────────────────────────────────────────────────────────────────

@csrf_exempt
def knowledge_tags(request, kb_id, tag_id=None):
    _, tenant = auth_context(request)
    kb = get_object_or_404(KnowledgeBase, id=kb_id)
    if request.method == "GET":
        tags = KnowledgeTag.objects.filter(knowledge_base=kb).order_by("sort_order", "created_at")
        return ok({"items": [tag_dict(t) for t in tags]})
    if tag_id:
        tag = get_object_or_404(KnowledgeTag, id=tag_id, knowledge_base=kb)
        if request.method == "DELETE":
            tag.delete()
            return ok({})
        data = parse_body(request)
        tag.name = data.get("name", tag.name)
        tag.color = data.get("color", tag.color)
        tag.sort_order = data.get("sort_order", tag.sort_order)
        tag.save()
        return ok(tag_dict(tag))
    data = parse_body(request)
    tag = KnowledgeTag.objects.create(
        tenant=tenant,
        knowledge_base=kb,
        name=data.get("name", "未命名"),
        color=data.get("color", ""),
        sort_order=data.get("sort_order", 0),
    )
    return ok(tag_dict(tag), status=201)


# ── Search Views ─────────────────────────────────────────────────────────────

@csrf_exempt
def kb_hybrid_search(request, kb_id):
    _, tenant = auth_context(request)
    data = parse_body(request) if request.method == "POST" else request.GET
    query = data.get("query") or data.get("q") or ""
    top_k = bounded_int(data.get("top_k") or data.get("limit"), 10, 1, 100)
    results = hybrid_search(tenant.id, [kb_id], query, top_k)
    return ok({"items": results, "results": results})
