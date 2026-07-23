import hashlib

from django.db import transaction

from .models import Chunk
from .search import delete_chunk_index, ensure_search_tables, index_chunk


class ReadOnlyChunkMutation(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _ensure_mutable(chunk: Chunk) -> None:
    if chunk.chunk_type == "parent_text":
        raise ReadOnlyChunkMutation("chunk_parent_read_only", "parent text chunks are read-only")
    if chunk.chunk_type == "image_container":
        raise ReadOnlyChunkMutation("chunk_container_read_only", "image container chunks are read-only")


def _clear_text_anchor(chunk: Chunk) -> None:
    Chunk.objects.filter(tenant_id=chunk.tenant_id, anchor_chunk_id=chunk.id).update(anchor_chunk_id=None)


def _cleanup_text_parent(chunk: Chunk, parent_id: str | None) -> None:
    if not parent_id:
        return
    parent = Chunk.objects.select_for_update().filter(
        id=parent_id,
        tenant_id=chunk.tenant_id,
        knowledge_id=chunk.knowledge_id,
        knowledge_base_id=chunk.knowledge_base_id,
        chunk_type="parent_text",
        deleted_at__isnull=True,
    ).first()
    if not parent:
        Chunk.objects.filter(tenant_id=chunk.tenant_id, context_parent_id=parent_id).update(context_parent_id=None)
        return
    has_enabled_children = Chunk.objects.filter(
        tenant_id=chunk.tenant_id,
        knowledge_id=chunk.knowledge_id,
        knowledge_base_id=chunk.knowledge_base_id,
        context_parent_id=parent_id,
        chunk_type="text",
        is_enabled=True,
        deleted_at__isnull=True,
    ).exists()
    if has_enabled_children:
        return
    Chunk.objects.filter(tenant_id=chunk.tenant_id, context_parent_id=parent_id).update(context_parent_id=None)
    delete_chunk_index(parent.id, parent.seq_id, ensure_tables=False)
    parent.delete()


def _cleanup_media_parent(chunk: Chunk, parent_id: str | None) -> None:
    if not parent_id:
        return
    parent = Chunk.objects.select_for_update().filter(
        id=parent_id,
        tenant_id=chunk.tenant_id,
        knowledge_id=chunk.knowledge_id,
        knowledge_base_id=chunk.knowledge_base_id,
        chunk_type="image_container",
        deleted_at__isnull=True,
    ).first()
    if not parent:
        Chunk.objects.filter(tenant_id=chunk.tenant_id, media_parent_id=parent_id).update(media_parent_id=None)
        return
    has_enabled_children = Chunk.objects.filter(
        tenant_id=chunk.tenant_id,
        knowledge_id=chunk.knowledge_id,
        knowledge_base_id=chunk.knowledge_base_id,
        media_parent_id=parent_id,
        chunk_type__in=("image_ocr", "image_caption"),
        is_enabled=True,
        deleted_at__isnull=True,
    ).exists()
    if has_enabled_children:
        return
    Chunk.objects.filter(tenant_id=chunk.tenant_id, media_parent_id=parent_id).update(media_parent_id=None)
    delete_chunk_index(parent.id, parent.seq_id, ensure_tables=False)
    parent.delete()


def update_chunk(chunk: Chunk, data: dict) -> Chunk:
    _ensure_mutable(chunk)
    ensure_search_tables()
    with transaction.atomic():
        current = Chunk.objects.select_for_update().select_related("knowledge", "knowledge_base").get(id=chunk.id)
        _ensure_mutable(current)
        if "content" in data:
            current.content = data["content"]
            current.content_hash = hashlib.sha256(current.content.encode("utf-8")).hexdigest()
        if "is_enabled" in data:
            current.is_enabled = data["is_enabled"]
        if "metadata" in data:
            current.metadata = data["metadata"]
        current.save(update_fields=["content", "content_hash", "is_enabled", "metadata", "updated_at"])
        index_chunk(current, ensure_tables=False)
        if current.chunk_type == "text" and not current.is_enabled:
            _clear_text_anchor(current)
            _cleanup_text_parent(current, current.context_parent_id)
            current.refresh_from_db()
        if current.chunk_type in {"image_ocr", "image_caption"} and not current.is_enabled:
            _cleanup_media_parent(current, current.media_parent_id)
            current.refresh_from_db()
        return current


def delete_chunk(chunk: Chunk) -> None:
    _ensure_mutable(chunk)
    ensure_search_tables()
    with transaction.atomic():
        current = Chunk.objects.select_for_update().select_related("knowledge", "knowledge_base").get(id=chunk.id)
        _ensure_mutable(current)
        context_parent_id = current.context_parent_id
        media_parent_id = current.media_parent_id
        delete_chunk_index(current.id, current.seq_id, ensure_tables=False)
        if current.chunk_type == "text":
            _clear_text_anchor(current)
        current.delete()
        if current.chunk_type == "text":
            _cleanup_text_parent(current, context_parent_id)
        if current.chunk_type in {"image_ocr", "image_caption"}:
            _cleanup_media_parent(current, media_parent_id)
