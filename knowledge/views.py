import hashlib
import json
import logging
import mimetypes
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import FileResponse, HttpResponse, JsonResponse, StreamingHttpResponse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.csrf import csrf_exempt

from personal_knowledge_base.chunking.config import ChunkingConfig, validate_upload_extension
from personal_knowledge_base.chunking_state import (
    backfill_completed_effective_chunking_configs,
    prepare_kb_chunking_states,
    projected_chunking_config,
)
from personal_knowledge_base.document_processing import detect_file_type, process_knowledge
from personal_knowledge_base.document_processing import process_graph as rebuild_knowledge_graph
from personal_knowledge_base.graph_rag import (
    DEFAULT_EXTRACT_CONFIG,
    delete_kb_graph,
    delete_knowledge_graph,
    validate_extract_config,
)
from personal_knowledge_base.multimodal import cleanup_knowledge_images
from personal_knowledge_base.models import (
    Chunk,
    Knowledge,
    KnowledgeBase,
    KnowledgeImage,
    KnowledgeTag,
    TaskRecord,
)
from personal_knowledge_base.responses import fail, ok
from personal_knowledge_base.process_config import (
    InvalidProcessConfig,
    parse_json_reparse_request,
    parse_multipart_process_config,
)
from personal_knowledge_base.chunk_mutations import ReadOnlyChunkMutation, delete_chunk, update_chunk
from personal_knowledge_base.search import delete_chunk_index, hybrid_search_ex, index_chunk
from personal_knowledge_base.serializers import (
    DEFAULT_INDEXING_STRATEGY,
    chunk_dict,
    kb_dict,
    knowledge_dict,
    knowledge_list_dict,
    normalize_indexing_strategy,
    tag_dict,
)
from personal_knowledge_base.tasks import enqueue
from personal_knowledge_base.view_security import (
    tenant_chunk_or_404,
    tenant_chunk_queryset,
    tenant_object_or_404,
    tenant_required,
)
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


def _opt_bounded(value, lo, hi):
    """可选整数：缺省/非法返回 None（交由检索层用默认值），否则夹在 [lo, hi]。"""
    if value is None or value == "":
        return None
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return None


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


def tenant_knowledge_queryset_or_404(ids, tenant, knowledge_base=None):
    qs = Knowledge.objects.filter(
        tenant=tenant,
        deleted_at__isnull=True,
        knowledge_base__tenant=tenant,
        knowledge_base__deleted_at__isnull=True,
    )
    if knowledge_base is not None:
        qs = qs.filter(knowledge_base=knowledge_base)
    for knowledge_id in ids:
        tenant_object_or_404(qs, tenant, id=knowledge_id)
    return qs.filter(id__in=ids)


def tenant_knowledge_or_404(tenant, **lookup):
    return tenant_object_or_404(
        Knowledge,
        tenant,
        deleted_at__isnull=True,
        knowledge_base__tenant=tenant,
        knowledge_base__deleted_at__isnull=True,
        **lookup,
    )


def with_process_config(metadata, process_config, include_empty=False):
    metadata = dict(metadata or {})
    if process_config is None and not include_empty:
        return metadata
    config = process_config or {}
    metadata["process_config"] = config
    metadata["process_overrides"] = config
    return metadata


def normalize_kb_payload(data, existing=None, partial=False):
    if not isinstance(data, dict):
        return None, fail("knowledge base payload must be an object", 400)
    kb_type = data.get("type", existing.type if existing else "document")
    if kb_type == "faq":
        return None, fail("FAQ knowledge bases are no longer supported", 400)
    if kb_type not in KB_TYPES and kb_type != "wiki":
        return None, fail("unsupported knowledge base type", 400)

    config = data.get("config") or data
    if not isinstance(config, dict):
        return None, fail("knowledge base config must be an object", 400)
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

    chunking_config = None
    if not partial or "chunking_config" in config:
        try:
            chunking_config = asdict(ChunkingConfig.from_mapping(config.get("chunking_config")))
        except (TypeError, ValueError, OverflowError) as exc:
            return None, fail(str(exc), 400)

    payload = {
        "type": "document",
        "indexing_strategy": strategy,
        "wiki_config": wiki_config,
        "extract_config": extract_config,
    }
    if chunking_config is not None:
        payload["chunking_config"] = chunking_config
    return payload, None


def delete_knowledge_content(item, cleanup_wiki=True):
    if cleanup_wiki:
        try:
            cleanup_wiki_for_knowledge(item)
        except Exception:
            pass
    delete_knowledge_graph(item)
    chunks = Chunk.objects.filter(
        tenant=item.tenant,
        knowledge=item,
        knowledge__tenant=item.tenant,
        knowledge__deleted_at__isnull=True,
        knowledge_base__tenant=item.tenant,
        knowledge_base__deleted_at__isnull=True,
    )
    for chunk in chunks:
        delete_chunk_index(chunk.id, chunk.seq_id)
    chunks.delete()
    cleanup_knowledge_images(item)


def matching_process_tasks(knowledge_id):
    target = str(knowledge_id)
    return [
        (task_id, payload, progress)
        for task_id, payload, progress in TaskRecord.objects.filter(task_type="process_knowledge").values_list("id", "payload", "progress")
        if isinstance(payload, dict) and str(payload.get("knowledge_id") or "") == target
    ]


def retire_knowledge_for_delete(item):
    deleted_at = timezone.now()
    Knowledge.objects.filter(id=item.id, tenant=item.tenant).update(
        parse_status="cancelled",
        deleted_at=deleted_at,
        updated_at=deleted_at,
    )
    item.parse_status = "cancelled"
    item.deleted_at = deleted_at
    task_ids = [task_id for task_id, _, _ in matching_process_tasks(item.id)]
    TaskRecord.objects.filter(id__in=task_ids).delete()
    for task_id in task_ids:
        cache.delete(f"task:{task_id}")


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
    return asdict(ChunkingConfig())


# ── Knowledge Base Views ─────────────────────────────────────────────────────

@csrf_exempt
@tenant_required
def knowledge_bases(request, kb_id=None):
    user = request.auth_user
    tenant = request.auth_tenant
    if kb_id:
        kb = tenant_object_or_404(KnowledgeBase, tenant, id=kb_id, deleted_at__isnull=True)
        if request.method == "GET":
            return ok(kb_dict(kb))
        if request.method == "DELETE":
            delete_kb_graph(kb)
            cleanup_wiki_for_kb(kb)
            kb.deleted_at = timezone.now()
            kb.save(update_fields=["deleted_at", "updated_at"])
            return ok({})
        data = parse_body(request)
        with transaction.atomic():
            kb = tenant_object_or_404(
                KnowledgeBase.objects.select_for_update(),
                tenant,
                id=kb_id,
                deleted_at__isnull=True,
            )
            config = data.get("config") or data
            normalized, error = normalize_kb_payload(data, kb, partial=True)
            if error:
                return error
            if (
                "chunking_config" in normalized
                and normalized["chunking_config"] != projected_chunking_config(kb.chunking_config)
            ):
                backfill_completed_effective_chunking_configs(kb)
            for field in ["name", "description"]:
                if field in data:
                    setattr(kb, field, data[field])
            for field in ["image_processing_config"]:
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
        page = prepare_kb_chunking_states(page)
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
        chunking_config=normalized["chunking_config"],
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
@tenant_required
def kb_pin(request, kb_id):
    kb = tenant_object_or_404(KnowledgeBase, request.auth_tenant, id=kb_id, deleted_at__isnull=True)
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
@tenant_required
def kb_copy(request):
    user = request.auth_user
    tenant = request.auth_tenant
    data = parse_body(request)
    src = tenant_object_or_404(KnowledgeBase, tenant, id=data.get("source_id"), deleted_at__isnull=True)
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


@tenant_required
def kb_move_targets(request, kb_id):
    tenant = request.auth_tenant
    source = tenant_object_or_404(KnowledgeBase, tenant, id=kb_id, deleted_at__isnull=True)
    qs = KnowledgeBase.objects.filter(tenant=tenant, type=source.type, deleted_at__isnull=True).exclude(id=kb_id)
    return ok({"items": [kb_dict(kb) for kb in prepare_kb_chunking_states(qs)]})


# ── Knowledge Views ──────────────────────────────────────────────────────────

@csrf_exempt
@tenant_required
def knowledge_collection(request, kb_id):
    kb = tenant_object_or_404(KnowledgeBase, request.auth_tenant, id=kb_id, deleted_at__isnull=True)
    if request.method == "GET":
        base_qs = Knowledge.objects.filter(tenant=request.auth_tenant, knowledge_base=kb, deleted_at__isnull=True)
        status_counts = {
            row["parse_status"]: row["count"]
            for row in base_qs.values("parse_status").annotate(count=Count("id"))
        }
        tag_counts = {
            row["tag_id"]: row["count"]
            for row in base_qs.values("tag_id").annotate(count=Count("id"))
        }
        qs = apply_knowledge_filters(base_qs.order_by("-updated_at"), request.GET)
        page, meta = paginate(qs, request)
        return ok({
            "items": [knowledge_list_dict(item) for item in page],
            **meta,
            "status_counts": status_counts,
            "tag_counts": tag_counts,
            "processing_records": [knowledge_list_dict(item) for item in base_qs.order_by("-updated_at")[:200]],
        })
    if request.method == "DELETE":
        knowledge_qs = Knowledge.objects.filter(tenant=request.auth_tenant, knowledge_base=kb)
        for item in knowledge_qs:
            delete_knowledge_content(item)
        knowledge_qs.update(deleted_at=timezone.now())
        cleanup_wiki_for_kb(kb)
        return ok({})
    return fail("method not allowed", 405)


@csrf_exempt
@tenant_required
def knowledge_file(request, kb_id):
    tenant = request.auth_tenant
    kb = tenant_object_or_404(KnowledgeBase, tenant, id=kb_id, deleted_at__isnull=True)
    uploaded = request.FILES.get("file")
    if not uploaded:
        return fail("file is required", 400)
    tag_id = request.POST.get("tag_id", "")
    if tag_id:
        tenant_object_or_404(
            KnowledgeTag,
            tenant,
            id=tag_id,
            knowledge_base=kb,
            deleted_at__isnull=True,
        )
    try:
        file_type = validate_upload_extension(uploaded.name)
    except ValueError:
        return fail("不支持的文件类型", 400, "unsupported_file_type", {"file_name": uploaded.name, "file_type": detect_file_type(uploaded.name)})
    try:
        process_config = parse_multipart_process_config(request.POST, kb.chunking_config)
    except InvalidProcessConfig:
        return fail("invalid process configuration", 400, "invalid_process_config")
    data = uploaded.read()
    file_hash = hashlib.sha256(data).hexdigest()
    existing = Knowledge.objects.filter(
        tenant=tenant,
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
                    tenant=tenant,
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
                    tag_id=tag_id,
                    metadata=with_process_config({}, process_config, include_empty=True),
                )
            break
        except IntegrityError:
            default_storage.delete(path)
            existing = Knowledge.objects.filter(
                tenant=tenant,
                knowledge_base=kb,
                file_hash=file_hash,
                file_name=uploaded.name,
                deleted_at__isnull=True,
            ).order_by("-created_at").first()
            if existing:
                return ok({"knowledge": knowledge_dict(existing), "task_id": "", "deduplicated": True}, status=200)
            return fail("file conflicts with an existing record", 409, "file_conflict")
        except Exception as exc:
            if "database is locked" in str(exc) and attempt < max_retries - 1:
                _time.sleep(2 * (attempt + 1))
                continue
            default_storage.delete(path)
            raise

    if item is None:
        default_storage.delete(path)
        return fail("upload failed after retries", 500)
    try:
        task = enqueue("process_knowledge", lambda: (process_knowledge(item.id), {"knowledge_id": item.id})[1], {"knowledge_id": item.id})
    except Exception:
        logger.exception("Failed to enqueue uploaded knowledge %s", item.id)
        item.delete()
        default_storage.delete(path)
        return fail("failed to queue processing", 503, "processing_enqueue_failed")
    return ok({"knowledge": knowledge_dict(item), "task_id": task.id}, status=201)


@csrf_exempt
@tenant_required
def knowledge_detail(request, knowledge_id):
    item = tenant_knowledge_or_404(request.auth_tenant, id=knowledge_id)
    if request.method == "GET":
        return ok(knowledge_dict(item))
    if request.method == "DELETE":
        retire_knowledge_for_delete(item)
        delete_knowledge_content(item)
        return ok({"id": knowledge_id, "task_id": ""})
    data = parse_body(request)
    tag_id = data.get("tag_id")
    if tag_id:
        tenant_object_or_404(
            KnowledgeTag,
            request.auth_tenant,
            id=tag_id,
            knowledge_base=item.knowledge_base,
            deleted_at__isnull=True,
        )
    for field in ["title", "description", "enable_status", "tag_id"]:
        if field in data:
            setattr(item, field, data[field])
    item.save()
    return ok(knowledge_dict(item))


@csrf_exempt
@tenant_required
def knowledge_reparse(request, knowledge_id):
    item = tenant_knowledge_or_404(request.auth_tenant, id=knowledge_id)
    try:
        _, process_config = parse_json_reparse_request(request, item.knowledge_base.chunking_config)
    except InvalidProcessConfig:
        return fail("invalid process configuration", 400, "invalid_process_config")
    try:
        with transaction.atomic():
            item = tenant_object_or_404(
                Knowledge.objects.select_for_update(),
                request.auth_tenant,
                id=knowledge_id,
                deleted_at__isnull=True,
                knowledge_base__tenant=request.auth_tenant,
                knowledge_base__deleted_at__isnull=True,
            )
            prepare_wiki_for_reparse(item)
            update_fields = ["parse_status", "updated_at"]
            if process_config is not None:
                item.metadata = with_process_config(item.metadata, process_config)
                update_fields.append("metadata")
            item.parse_status = "pending"
            item.save(update_fields=update_fields)
            task = enqueue("process_knowledge", lambda: (process_knowledge(item.id), {"knowledge_id": item.id})[1], {"knowledge_id": item.id})
    except Exception:
        logger.exception("Failed to enqueue reparse for knowledge %s", knowledge_id)
        return fail("failed to queue processing", 503, "processing_enqueue_failed")
    return ok({"knowledge": knowledge_dict(item), "task_id": task.id})


@csrf_exempt
@tenant_required
def knowledge_cancel(request, knowledge_id):
    item = tenant_knowledge_or_404(request.auth_tenant, id=knowledge_id)
    item.parse_status = "cancelled"
    item.save(update_fields=["parse_status", "updated_at"])
    for task_id, payload, progress in matching_process_tasks(item.id):
        if TaskRecord.objects.filter(id=task_id, status__in=["pending", "running"]).update(
            status="cancelled",
            payload={key: value for key, value in payload.items() if key != "_worker_token"},
            error_message="cancelled by user",
            updated_at=timezone.now(),
        ):
            cache.set(f"task:{task_id}", {"status": "cancelled", "progress": progress, "error_message": "cancelled by user"}, timeout=86400)
    return ok(knowledge_dict(item))


@csrf_exempt
@tenant_required
def knowledge_batch_delete(request, kb_id=None):
    data = parse_body(request)
    source_kb_id = kb_id or data.get("kb_id") or data.get("knowledge_base_id") or data.get("source_kb_id")
    ids = normalize_ids(data)
    count = 0
    tenant = request.auth_tenant
    if source_kb_id:
        source = tenant_object_or_404(KnowledgeBase, tenant, id=source_kb_id, deleted_at__isnull=True)
    else:
        source = None
    qs = tenant_knowledge_queryset_or_404(ids, tenant, source)
    with transaction.atomic():
        for item in qs:
            retire_knowledge_for_delete(item)
            delete_knowledge_content(item)
            count += 1
    return ok({"deleted": count, "deleted_count": count, "ids": ids, "kb_id": source_kb_id, "task_id": ""})


@csrf_exempt
@tenant_required
def knowledge_move(request, kb_id=None):
    data = parse_body(request)
    ids = normalize_ids(data)
    source_kb_id = kb_id or data.get("source_kb_id") or data.get("kb_id")
    target_id = data.get("target_kb_id") or data.get("target_knowledge_base_id") or data.get("knowledge_base_id")
    tenant = request.auth_tenant
    target = tenant_object_or_404(KnowledgeBase, tenant, id=target_id, deleted_at__isnull=True)
    moved = 0
    if source_kb_id:
        source = tenant_object_or_404(KnowledgeBase, tenant, id=source_kb_id, deleted_at__isnull=True)
    else:
        source = None
    qs = tenant_knowledge_queryset_or_404(ids, tenant, source)
    with transaction.atomic():
        for item in qs:
            old_kb_id = item.knowledge_base_id
            source_tenant = item.tenant
            cleanup_wiki_for_knowledge(item)
            delete_knowledge_graph(item)
            item.knowledge_base = target
            item.tenant = target.tenant
            item.save(update_fields=["knowledge_base", "tenant", "updated_at"])
            KnowledgeImage.objects.filter(tenant=source_tenant, knowledge=item).update(knowledge_base=target, tenant=target.tenant)
            chunks = []
            for chunk in Chunk.objects.filter(
                tenant=source_tenant,
                knowledge=item,
                knowledge__tenant=source_tenant,
                knowledge__deleted_at__isnull=True,
                knowledge_base__tenant=source_tenant,
                knowledge_base__deleted_at__isnull=True,
            ):
                delete_chunk_index(chunk.id, chunk.seq_id)
                chunk.knowledge_base = target
                chunk.tenant = target.tenant
                chunk.relation_chunks = None
                chunk.indirect_relation_chunks = None
                chunk.save(update_fields=["knowledge_base", "tenant", "updated_at"])
                if chunk.is_enabled and chunk.chunk_type != "image_container":
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


@tenant_required
def knowledge_batch(request):
    ids = normalize_ids({"ids": request.GET.get("ids", "")})
    items = tenant_knowledge_queryset_or_404(ids, request.auth_tenant)
    return ok({"items": [knowledge_dict(item) for item in items]})


@tenant_required
def knowledge_search(request):
    tenant = request.auth_tenant
    qs = Knowledge.objects.filter(tenant=tenant, deleted_at__isnull=True)
    qs = apply_knowledge_filters(qs, request.GET)
    page, meta = paginate(qs, request)
    return ok({"items": [knowledge_dict(item) for item in page], **meta})


def _hybrid_search_with_meta(tenant, kb_ids, data):
    """严格管线检索并附带可观测元信息：候选参数（缺省/非法回退默认）、retrieval meta、延迟。"""
    top_k = bounded_int(data.get("top_k") or data.get("limit"), 10, 1, 100)
    candidate = {
        "keyword_top_k": _opt_bounded(data.get("keyword_top_k"), 1, 400),
        "vector_top_k": _opt_bounded(data.get("vector_top_k"), 1, 400),
        "rerank_top_k": _opt_bounded(data.get("rerank_top_k"), 1, 400),
        "rrf_k": _opt_bounded(data.get("rrf_k"), 1, 10000),
    }
    query = data.get("query") or data.get("q") or ""
    start = time.monotonic()
    results, meta = hybrid_search_ex(tenant.id, kb_ids, query, top_k, **candidate)
    latency_ms = int((time.monotonic() - start) * 1000)
    candidate["rrf_k"] = meta["rrf_k"]  # 回填生效 RRF k
    return top_k, results, meta, candidate, latency_ms


@csrf_exempt
@tenant_required
def knowledge_search_post(request):
    tenant = request.auth_tenant
    data = parse_body(request)
    requested_kb_ids = csv_values(data.get("knowledge_base_ids") or data.get("kb_ids") or [])
    kb_ids = [
        tenant_object_or_404(KnowledgeBase, tenant, id=kb_id, deleted_at__isnull=True).id
        for kb_id in requested_kb_ids
    ]
    top_k, results, meta, candidate, latency_ms = _hybrid_search_with_meta(tenant, kb_ids, data)
    return ok({
        "items": results,
        "results": results,
        "top_k": top_k,
        "retrieval": meta,
        "candidate_params": candidate,
        "observability": {"latency_ms": latency_ms},
    })


@tenant_required
def knowledge_stats(request, kb_id):
    tenant = request.auth_tenant
    kb = tenant_object_or_404(KnowledgeBase, tenant, id=kb_id, deleted_at__isnull=True)
    qs = Knowledge.objects.filter(tenant=tenant, knowledge_base=kb, deleted_at__isnull=True)
    total = qs.count()
    status_counts = {}
    for status in ["pending", "processing", "finalizing", "completed", "failed", "cancelled"]:
        status_counts[status] = qs.filter(parse_status=status).count()
    processing = qs.filter(parse_status__in=PROCESSING_STATUSES).count()
    chunk_count = Chunk.objects.filter(tenant=tenant, knowledge_base=kb, deleted_at__isnull=True).count()
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


@tenant_required
def knowledge_spans(request, knowledge_id):
    from personal_knowledge_base.span_tracker import SpanTracker

    item = tenant_knowledge_or_404(request.auth_tenant, id=knowledge_id)
    tracker = SpanTracker(knowledge_id)
    spans = tracker.get_spans()

    if not spans:
        return ok({"items": [{"name": "parse", "status": item.parse_status, "started_at": item.created_at.isoformat(), "finished_at": item.processed_at.isoformat() if item.processed_at else None}]})

    return ok({"items": spans})


@tenant_required
def knowledge_download(request, knowledge_id):
    item = tenant_knowledge_or_404(request.auth_tenant, id=knowledge_id)
    filename = item.file_name or f"{item.title or item.id}.txt"
    if not item.file_path:
        response = HttpResponse(item.metadata.get("content", ""), content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = content_disposition_header(True, filename)
        return response
    return FileResponse(default_storage.open(item.file_path, "rb"), as_attachment=True, filename=filename)


@tenant_required
def knowledge_preview(request, knowledge_id):
    item = tenant_knowledge_or_404(request.auth_tenant, id=knowledge_id)
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

    chunks = Chunk.objects.filter(tenant=item.tenant, knowledge=item, deleted_at__isnull=True).order_by("chunk_index")
    preview_text = "\n\n".join(chunk.content for chunk in chunks)
    if not preview_text:
        metadata = item.metadata or {}
        preview_text = metadata.get("content") or metadata.get("summary") or item.error_message or "该文件暂无可预览文本。"
    response = HttpResponse(preview_text, content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = content_disposition_header(False, f"{Path(filename).stem or item.title}.txt")
    return response


@tenant_required
def knowledge_image_content(request, knowledge_id, image_id):
    tenant = request.auth_tenant
    image = tenant_object_or_404(
        KnowledgeImage,
        tenant,
        id=image_id,
        knowledge_id=knowledge_id,
        deleted_at__isnull=True,
        knowledge__tenant=tenant,
        knowledge__deleted_at__isnull=True,
        knowledge_base__tenant=tenant,
        knowledge_base__deleted_at__isnull=True,
        knowledge__knowledge_base__tenant=tenant,
        knowledge__knowledge_base__deleted_at__isnull=True,
    )
    if not image.storage_path or not default_storage.exists(image.storage_path):
        return fail("image not found", 404)
    return FileResponse(default_storage.open(image.storage_path, "rb"), content_type=image.mime_type, as_attachment=False)


# ── Chunk Views ──────────────────────────────────────────────────────────────

@csrf_exempt
@tenant_required
def chunks_collection(request, knowledge_id=None, chunk_id=None):
    tenant = request.auth_tenant
    if knowledge_id == "by-id" and chunk_id:
        knowledge_id = None
    if chunk_id:
        lookup = {"id": chunk_id}
        if knowledge_id:
            lookup["knowledge_id"] = knowledge_id
        chunk = tenant_chunk_or_404(tenant, **lookup)
        if request.method == "GET":
            return ok(chunk_dict(chunk))
        if request.method == "DELETE":
            try:
                delete_chunk(chunk)
            except ReadOnlyChunkMutation as exc:
                return fail(exc.message, 409, exc.code)
            return ok({})
        if request.method in {"PUT", "PATCH"}:
            data = parse_body(request)
            try:
                chunk = update_chunk(chunk, data)
            except ReadOnlyChunkMutation as exc:
                return fail(exc.message, 409, exc.code)
            return ok(chunk_dict(chunk))
        return fail("method not allowed", 405, "method_not_allowed")
    if knowledge_id and request.method == "GET":
        knowledge = tenant_knowledge_or_404(tenant, id=knowledge_id)
        chunks = tenant_chunk_queryset(tenant).filter(knowledge=knowledge).order_by("chunk_index")
        chunk_type = request.GET.get("chunk_type")
        if chunk_type:
            chunks = chunks.filter(chunk_type=chunk_type)
        page, meta = paginate(chunks, request)
        items = [chunk_dict(c) for c in page]
        return ok(list_response(items, meta, ["chunks"]))
    if knowledge_id and request.method == "DELETE":
        item = tenant_knowledge_or_404(tenant, id=knowledge_id)
        delete_knowledge_content(item)
        return ok({})
    if knowledge_id:
        return fail("method not allowed", 405, "method_not_allowed")
    return fail("not found", 404)


# ── Tag Views ────────────────────────────────────────────────────────────────

@csrf_exempt
@tenant_required
def knowledge_tags(request, kb_id, tag_id=None):
    tenant = request.auth_tenant
    kb = tenant_object_or_404(KnowledgeBase, tenant, id=kb_id, deleted_at__isnull=True)
    if tag_id:
        tag = tenant_object_or_404(
            KnowledgeTag,
            tenant,
            id=tag_id,
            knowledge_base=kb,
            deleted_at__isnull=True,
        )
        if request.method == "GET":
            return ok(tag_dict(tag))
        if request.method == "DELETE":
            tag.delete()
            return ok({})
        data = parse_body(request)
        tag.name = data.get("name", tag.name)
        tag.color = data.get("color", tag.color)
        tag.sort_order = data.get("sort_order", tag.sort_order)
        tag.save()
        return ok(tag_dict(tag))
    if request.method == "GET":
        tags = KnowledgeTag.objects.filter(
            tenant=tenant,
            knowledge_base=kb,
            deleted_at__isnull=True,
        ).order_by("sort_order", "created_at")
        return ok({"items": [tag_dict(t) for t in tags]})
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
@tenant_required
def kb_hybrid_search(request, kb_id):
    tenant = request.auth_tenant
    kb = tenant_object_or_404(KnowledgeBase, tenant, id=kb_id, deleted_at__isnull=True)
    data = parse_body(request) if request.method == "POST" else request.GET
    top_k, results, meta, candidate, latency_ms = _hybrid_search_with_meta(tenant, [kb.id], data)
    return ok({
        "items": results,
        "results": results,
        "top_k": top_k,
        "retrieval": meta,
        "candidate_params": candidate,
        "observability": {"latency_ms": latency_ms},
    })
