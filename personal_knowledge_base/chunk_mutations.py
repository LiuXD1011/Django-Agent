import hashlib
import logging

from django.db import transaction

from .models import Chunk
from .search import delete_chunk_index, ensure_search_tables, index_chunk


logger = logging.getLogger(__name__)
SEARCHABLE_CHUNK_TYPES = {"text", "image_ocr", "image_caption"}
MEDIA_CHUNK_TYPES = {"image_ocr", "image_caption"}


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


def _locked_knowledge_chunks(chunk: Chunk) -> list[Chunk]:
    return list(
        Chunk.objects.select_for_update().filter(
            tenant_id=chunk.tenant_id,
            knowledge_id=chunk.knowledge_id,
            knowledge_base_id=chunk.knowledge_base_id,
            deleted_at__isnull=True,
        ).order_by("chunk_index", "id")
    )


def _remove_relationship_id(value, removed_id: str):
    if not isinstance(value, list):
        return value
    return [item for item in value if str(item) != removed_id]


def _valid_media_anchor_id(media: Chunk, chunks: list[Chunk]) -> str | None:
    if media.chunk_type not in MEDIA_CHUNK_TYPES or not media.anchor_chunk_id:
        return None
    target = next((chunk for chunk in chunks if chunk.id == media.anchor_chunk_id), None)
    if not target or target.chunk_type != "text" or not target.is_enabled or target.deleted_at is not None:
        return None
    return target.id


def _clear_removed_relationships(
    chunks: list[Chunk],
    removed_id: str,
    *,
    preserve_removed_anchor: bool = False,
) -> None:
    changed = []
    for chunk in chunks:
        original = (
            chunk.pre_chunk_id,
            chunk.next_chunk_id,
            chunk.anchor_chunk_id,
            chunk.relation_chunks,
            chunk.indirect_relation_chunks,
        )
        relation_chunks = _remove_relationship_id(chunk.relation_chunks, removed_id)
        indirect_relation_chunks = _remove_relationship_id(chunk.indirect_relation_chunks, removed_id)
        if chunk.anchor_chunk_id == removed_id:
            chunk.anchor_chunk_id = None
        if chunk.id == removed_id:
            relation_chunks = []
            indirect_relation_chunks = []
            chunk.pre_chunk_id = ""
            chunk.next_chunk_id = ""
            if not preserve_removed_anchor:
                chunk.anchor_chunk_id = None
        chunk.relation_chunks = relation_chunks
        chunk.indirect_relation_chunks = indirect_relation_chunks
        current = (
            chunk.pre_chunk_id,
            chunk.next_chunk_id,
            chunk.anchor_chunk_id,
            chunk.relation_chunks,
            chunk.indirect_relation_chunks,
        )
        if current != original:
            changed.append(chunk)
    if changed:
        Chunk.objects.bulk_update(
            changed,
            [
                "pre_chunk_id",
                "next_chunk_id",
                "anchor_chunk_id",
                "relation_chunks",
                "indirect_relation_chunks",
            ],
        )


def _relink_searchable_chunks(chunks: list[Chunk], *, removed_id: str | None = None) -> None:
    eligible = sorted(
        (
            chunk
            for chunk in chunks
            if chunk.id != removed_id
            and chunk.is_enabled
            and chunk.deleted_at is None
            and chunk.chunk_type in SEARCHABLE_CHUNK_TYPES
        ),
        key=lambda chunk: (chunk.chunk_index, chunk.id),
    )
    links = {
        chunk.id: (
            eligible[index - 1].id if index else "",
            eligible[index + 1].id if index + 1 < len(eligible) else "",
        )
        for index, chunk in enumerate(eligible)
    }
    changed = []
    for chunk in chunks:
        desired_pre, desired_next = links.get(chunk.id, ("", ""))
        if chunk.pre_chunk_id == desired_pre and chunk.next_chunk_id == desired_next:
            continue
        chunk.pre_chunk_id = desired_pre
        chunk.next_chunk_id = desired_next
        changed.append(chunk)
    if changed:
        Chunk.objects.bulk_update(changed, ["pre_chunk_id", "next_chunk_id"])


def _invalidate_graph_safely(knowledge) -> None:
    try:
        from .graph_rag import delete_knowledge_graph

        delete_knowledge_graph(knowledge)
    except Exception:
        # The DB/index mutation is authoritative. External graph invalidation is
        # best-effort after commit and must not roll back a successful edit.
        logger.exception("Graph invalidation failed for knowledge %s", knowledge.id)


def _schedule_graph_invalidation(knowledge) -> None:
    transaction.on_commit(lambda: _invalidate_graph_safely(knowledge))


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
        content_changed = "content" in data and data["content"] != current.content
        enabled_changed = "is_enabled" in data and data["is_enabled"] != current.is_enabled
        if "content" in data:
            current.content = data["content"]
            current.content_hash = hashlib.sha256(current.content.encode("utf-8")).hexdigest()
        if "is_enabled" in data:
            current.is_enabled = data["is_enabled"]
        if "metadata" in data:
            current.metadata = data["metadata"]
        current.save(update_fields=["content", "content_hash", "is_enabled", "metadata", "updated_at"])
        index_chunk(current, ensure_tables=False)
        if enabled_changed:
            chunks = _locked_knowledge_chunks(current)
            if not current.is_enabled:
                preserve_anchor = bool(_valid_media_anchor_id(current, chunks))
                _clear_removed_relationships(
                    chunks,
                    current.id,
                    preserve_removed_anchor=preserve_anchor,
                )
                if current.chunk_type == "text":
                    _clear_text_anchor(current)
                _relink_searchable_chunks(chunks)
                if current.chunk_type == "text":
                    _cleanup_text_parent(current, current.context_parent_id)
                if current.chunk_type in MEDIA_CHUNK_TYPES:
                    _cleanup_media_parent(current, current.media_parent_id)
            else:
                if (
                    current.chunk_type in MEDIA_CHUNK_TYPES
                    and current.anchor_chunk_id
                    and not _valid_media_anchor_id(current, chunks)
                ):
                    current.anchor_chunk_id = None
                    current.save(update_fields=["anchor_chunk_id", "updated_at"])
                _relink_searchable_chunks(chunks)
            current.refresh_from_db()
        if content_changed or enabled_changed:
            _schedule_graph_invalidation(current.knowledge)
        return current


def delete_chunk(chunk: Chunk) -> None:
    _ensure_mutable(chunk)
    ensure_search_tables()
    with transaction.atomic():
        current = Chunk.objects.select_for_update().select_related("knowledge", "knowledge_base").get(id=chunk.id)
        _ensure_mutable(current)
        knowledge = current.knowledge
        context_parent_id = current.context_parent_id
        media_parent_id = current.media_parent_id
        chunks = _locked_knowledge_chunks(current)
        delete_chunk_index(current.id, current.seq_id, ensure_tables=False)
        if current.chunk_type == "text":
            _clear_text_anchor(current)
        _clear_removed_relationships(chunks, current.id)
        current.delete()
        _relink_searchable_chunks(chunks, removed_id=chunk.id)
        if current.chunk_type == "text":
            _cleanup_text_parent(current, context_parent_id)
        if current.chunk_type in MEDIA_CHUNK_TYPES:
            _cleanup_media_parent(current, media_parent_id)
        _schedule_graph_invalidation(knowledge)
