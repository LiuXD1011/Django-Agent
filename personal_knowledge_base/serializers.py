from .models import (
    Chunk,
    GenericResource,
    Knowledge,
    KnowledgeBase,
    KnowledgeTag,
    Message,
    ModelConfig,
    Session,
    Tenant,
    TenantMember,
    User,
    WikiFolder,
    WikiPage,
)
from .model_types import canonical_model_type, frontend_model_group


def iso(dt):
    return dt.isoformat() if dt else None


DEFAULT_INDEXING_STRATEGY = {
    "vector_enabled": True,
    "keyword_enabled": True,
    "wiki_enabled": True,
    "graph_enabled": True,
}


def bool_value(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on", "enabled"}


def normalize_indexing_strategy(strategy=None, kb_type="document"):
    raw = strategy if isinstance(strategy, dict) else {}
    normalized = {
        key: bool_value(raw.get(key), default)
        for key, default in DEFAULT_INDEXING_STRATEGY.items()
    }
    if kb_type == "wiki":
        normalized["wiki_enabled"] = True
    return normalized


def kb_capabilities(strategy=None, extract_config=None):
    normalized = normalize_indexing_strategy(strategy)
    return {
        "vector": normalized["vector_enabled"],
        "keyword": normalized["keyword_enabled"],
        "wiki": normalized["wiki_enabled"],
        "graph": normalized["graph_enabled"],
    }


def user_dict(user: User | None):
    if not user:
        return None
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "avatar": user.avatar,
        "tenant_id": user.tenant_id,
        "is_active": user.is_active,
        "can_access_all_tenants": user.can_access_all_tenants,
        "is_system_admin": user.is_system_admin,
        "preferences": user.preferences,
        "created_at": iso(user.created_at),
        "updated_at": iso(user.updated_at),
    }


def tenant_dict(tenant: Tenant | None):
    if not tenant:
        return None
    return {
        "id": tenant.id,
        "name": tenant.name,
        "description": tenant.description,
        "api_key": tenant.api_key,
        "status": tenant.status,
        "business": tenant.business,
        "storage_quota": tenant.storage_quota,
        "storage_used": tenant.storage_used,
        "created_at": iso(tenant.created_at),
        "updated_at": iso(tenant.updated_at),
    }


def membership_dict(member: TenantMember):
    return {
        "tenant_id": member.tenant_id,
        "user_id": member.user_id,
        "role": member.role,
        "status": member.status,
        "joined_at": iso(member.joined_at),
    }


def kb_dict(kb: KnowledgeBase, counts: bool = True):
    indexing_strategy = normalize_indexing_strategy(kb.indexing_strategy, kb.type)
    data = {
        "id": kb.id,
        "name": kb.name,
        "description": kb.description,
        "tenant_id": kb.tenant_id,
        "type": "document" if kb.type in {"wiki", "faq"} else kb.type,
        "chunking_config": kb.chunking_config,
        "image_processing_config": kb.image_processing_config,
        "embedding_model_id": kb.embedding_model_id,
        "summary_model_id": kb.summary_model_id,
        "storage_provider_config": kb.storage_provider_config,
        "vlm_config": kb.vlm_config,
        "asr_config": kb.asr_config,
        "extract_config": kb.extract_config,
        "question_generation_config": kb.question_generation_config,
        "wiki_config": kb.wiki_config,
        "indexing_strategy": indexing_strategy,
        "capabilities": kb_capabilities(indexing_strategy, kb.extract_config),
        "is_temporary": kb.is_temporary,
        "is_pinned": kb.is_pinned,
        "pinned_at": iso(kb.pinned_at),
        "creator_id": kb.creator_id,
        "creator_name": "",
        "vector_store_id": kb.vector_store_id or None,
        "vector_store_name": "SQLite local",
        "vector_store_engine_type": "sqlite-vec",
        "vector_store_source": "env",
        "vector_store_status": "available",
        "created_at": iso(kb.created_at),
        "updated_at": iso(kb.updated_at),
    }
    if counts:
        data["knowledge_count"] = Knowledge.objects.filter(knowledge_base=kb, deleted_at__isnull=True).count()
        data["document_count"] = data["knowledge_count"]
        data["chunk_count"] = Chunk.objects.filter(knowledge_base=kb, deleted_at__isnull=True).count()
        data["processing_count"] = Knowledge.objects.filter(knowledge_base=kb, parse_status__in=["pending", "processing", "finalizing"]).count()
        data["is_processing"] = data["processing_count"] > 0
    return data


def knowledge_dict(item: Knowledge):
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "knowledge_base_id": item.knowledge_base_id,
        "knowledge_base_name": getattr(item, "knowledge_base_name", "") or getattr(item.knowledge_base, "name", ""),
        "type": item.type,
        "title": item.title,
        "description": item.description,
        "source": item.source,
        "parse_status": item.parse_status,
        "enable_status": item.enable_status,
        "embedding_model_id": item.embedding_model_id,
        "file_name": item.file_name,
        "file_type": item.file_type,
        "file_size": item.file_size,
        "file_path": item.file_path,
        "file_hash": item.file_hash,
        "storage_size": item.storage_size,
        "metadata": item.metadata,
        "tag_id": item.tag_id,
        "summary_status": item.summary_status,
        "pending_subtasks_count": item.pending_subtasks_count,
        "channel": item.channel,
        "processed_at": iso(item.processed_at),
        "error_message": item.error_message,
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def chunk_dict(chunk: Chunk):
    return {
        "id": chunk.id,
        "tenant_id": chunk.tenant_id,
        "knowledge_base_id": chunk.knowledge_base_id,
        "knowledge_id": chunk.knowledge_id,
        "content": chunk.content,
        "chunk_index": chunk.chunk_index,
        "is_enabled": chunk.is_enabled,
        "start_at": chunk.start_at,
        "end_at": chunk.end_at,
        "pre_chunk_id": chunk.pre_chunk_id,
        "next_chunk_id": chunk.next_chunk_id,
        "chunk_type": chunk.chunk_type,
        "parent_chunk_id": chunk.parent_chunk_id,
        "image_info": chunk.image_info,
        "video_info": chunk.video_info,
        "relation_chunks": chunk.relation_chunks,
        "indirect_relation_chunks": chunk.indirect_relation_chunks,
        "metadata": chunk.metadata,
        "tag_id": chunk.tag_id,
        "status": chunk.status,
        "flags": chunk.flags,
        "seq_id": chunk.seq_id,
        "created_at": iso(chunk.created_at),
        "updated_at": iso(chunk.updated_at),
    }


def session_dict(session: Session):
    raw_state = session.agent_config if isinstance(session.agent_config, dict) else {}
    state = {
        "agent_enabled": bool_value(raw_state.get("agent_enabled"), False),
        "agent_id": raw_state.get("agent_id") or "",
        "model_id": raw_state.get("model_id") or "",
        "summary_model_id": raw_state.get("summary_model_id") or "",
        "knowledge_base_ids": raw_state.get("knowledge_base_ids") if isinstance(raw_state.get("knowledge_base_ids"), list) else [],
        "web_search_enabled": bool_value(raw_state.get("web_search_enabled"), False),
        "enable_memory": bool_value(raw_state.get("enable_memory"), True),
        "mcp_service_ids": raw_state.get("mcp_service_ids") if isinstance(raw_state.get("mcp_service_ids"), list) else [],
    }
    return {
        "id": session.id,
        "tenant_id": session.tenant_id,
        "title": session.title,
        "description": session.description,
        "knowledge_base_id": session.knowledge_base_id,
        "agent_id": session.agent_id,
        "user_id": session.user_id,
        "is_pinned": session.is_pinned,
        "pinned_at": iso(session.pinned_at),
        "last_request_state": state,
        "agent_config": state,
        "created_at": iso(session.created_at),
        "updated_at": iso(session.updated_at),
    }


def message_dict(message: Message):
    return {
        "id": message.id,
        "request_id": message.request_id,
        "session_id": message.session_id,
        "role": message.role,
        "content": message.content,
        "rendered_content": message.rendered_content,
        "knowledge_references": message.knowledge_references,
        "agent_steps": message.agent_steps,
        "mentioned_items": message.mentioned_items,
        "images": message.images,
        "attachments": message.attachments,
        "is_completed": message.is_completed,
        "is_fallback": message.is_fallback,
        "channel": message.channel,
        "agent_duration_ms": message.agent_duration_ms,
        "knowledge_id": message.knowledge_id,
        "created_at": iso(message.created_at),
        "updated_at": iso(message.updated_at),
    }


def model_dict(model: ModelConfig):
    parameters = dict(model.parameters or {})
    for key in ["api_key", "apikey", "secret_key", "app_secret", "access_key", "token", "password"]:
        if parameters.get(key):
            parameters[key] = "******"
    canonical_type = canonical_model_type(model.type)
    return {
        "id": model.id,
        "tenant_id": model.tenant_id,
        "name": model.name,
        "display_name": model.display_name,
        "type": canonical_type,
        "raw_type": model.type,
        "legacy_type": frontend_model_group(model.type),
        "source": model.source,
        "description": model.description,
        "parameters": parameters,
        "credentials_configured": any((model.parameters or {}).get(key) for key in ["api_key", "apikey", "secret_key", "app_secret", "access_key", "token"]),
        "is_default": model.is_default,
        "is_builtin": model.is_builtin,
        "managed_by": model.managed_by,
        "status": model.status,
        "created_at": iso(model.created_at),
        "updated_at": iso(model.updated_at),
    }


def tag_dict(tag: KnowledgeTag):
    return {
        "id": tag.id,
        "tenant_id": tag.tenant_id,
        "knowledge_base_id": tag.knowledge_base_id,
        "name": tag.name,
        "color": tag.color,
        "sort_order": tag.sort_order,
        "created_at": iso(tag.created_at),
        "updated_at": iso(tag.updated_at),
    }


def resource_dict(resource: GenericResource):
    data = dict(resource.data or {})
    data.setdefault("id", resource.id)
    data.setdefault("tenant_id", resource.tenant_id)
    data.setdefault("name", resource.name)
    data.setdefault("status", resource.status)
    data.setdefault("created_at", iso(resource.created_at))
    data.setdefault("updated_at", iso(resource.updated_at))
    return data


def wiki_page_dict(page: WikiPage):
    return {
        "id": page.id,
        "tenant_id": page.tenant_id,
        "knowledge_base_id": page.knowledge_base_id,
        "slug": page.slug,
        "title": page.title,
        "content": page.content,
        "summary": page.summary,
        "source_refs": page.source_refs,
        "chunk_refs": page.chunk_refs,
        "aliases": page.aliases,
        "in_links": page.in_links,
        "out_links": page.out_links,
        "metadata": page.page_metadata,
        "page_metadata": page.page_metadata,
        "page_type": page.page_type,
        "status": page.status,
        "folder_id": page.folder_id,
        "parent_slug": page.parent_slug,
        "category_path": page.category_path,
        "wiki_path": page.wiki_path,
        "depth": page.depth,
        "sort_order": page.sort_order,
        "version": page.version,
        "created_at": iso(page.created_at),
        "updated_at": iso(page.updated_at),
    }


def wiki_folder_dict(folder: WikiFolder):
    return {
        "id": folder.id,
        "tenant_id": folder.tenant_id,
        "knowledge_base_id": folder.knowledge_base_id,
        "name": folder.name,
        "parent_id": folder.parent_id,
        "path": folder.path,
        "depth": folder.depth,
        "sort_order": folder.sort_order,
        "created_at": iso(folder.created_at),
        "updated_at": iso(folder.updated_at),
    }
