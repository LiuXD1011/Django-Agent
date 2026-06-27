import uuid

from django.db import models


def uuid_str():
    return str(uuid.uuid4())


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True


class Tenant(TimeStampedModel):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    api_key = models.CharField(max_length=256, unique=True)
    retriever_engines = models.JSONField(default=list)
    status = models.CharField(max_length=50, default="active")
    business = models.CharField(max_length=255, default="default")
    storage_quota = models.BigIntegerField(default=10737418240)
    storage_used = models.BigIntegerField(default=0)
    agent_config = models.JSONField(null=True, blank=True)
    context_config = models.JSONField(null=True, blank=True)
    conversation_config = models.JSONField(null=True, blank=True)
    web_search_config = models.JSONField(null=True, blank=True)
    parser_engine_config = models.JSONField(null=True, blank=True)
    storage_engine_config = models.JSONField(null=True, blank=True)
    credentials = models.JSONField(null=True, blank=True)
    chat_history_config = models.JSONField(null=True, blank=True)
    retrieval_config = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "tenants"


class User(TimeStampedModel):
    id = models.CharField(max_length=36, primary_key=True, default=uuid_str)
    username = models.CharField(max_length=100, unique=True)
    email = models.EmailField(unique=True)
    password_hash = models.CharField(max_length=255)
    avatar = models.CharField(max_length=500, blank=True, default="")
    tenant = models.ForeignKey(Tenant, null=True, blank=True, on_delete=models.SET_NULL)
    is_active = models.BooleanField(default=True)
    can_access_all_tenants = models.BooleanField(default=False)
    is_system_admin = models.BooleanField(default=False)
    preferences = models.JSONField(default=dict)

    class Meta:
        db_table = "users"


class AuthToken(TimeStampedModel):
    id = models.CharField(max_length=36, primary_key=True, default=uuid_str)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    token = models.TextField(unique=True)
    token_type = models.CharField(max_length=50)
    expires_at = models.DateTimeField()
    is_revoked = models.BooleanField(default=False)

    class Meta:
        db_table = "auth_tokens"


class TenantMember(TimeStampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, default="owner")
    status = models.CharField(max_length=20, default="active")
    invited_by = models.CharField(max_length=36, blank=True, default="")
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tenant_members"
        unique_together = ("user", "tenant")


class ModelConfig(TimeStampedModel):
    id = models.CharField(max_length=64, primary_key=True)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255, blank=True, default="")
    type = models.CharField(max_length=50)
    source = models.CharField(max_length=50)
    description = models.TextField(blank=True, default="")
    parameters = models.JSONField(default=dict)
    is_default = models.BooleanField(default=False)
    is_builtin = models.BooleanField(default=False)
    managed_by = models.CharField(max_length=32, blank=True, default="")
    status = models.CharField(max_length=50, default="active")

    class Meta:
        db_table = "models"


class ModelUsage(TimeStampedModel):
    id = models.CharField(max_length=36, primary_key=True, default=uuid_str)
    tenant = models.ForeignKey(Tenant, null=True, blank=True, on_delete=models.CASCADE)
    model_id = models.CharField(max_length=128, blank=True, default="")
    model_name = models.CharField(max_length=255, blank=True, default="")
    model_type = models.CharField(max_length=50, blank=True, default="")
    provider = models.CharField(max_length=64, blank=True, default="")
    scenario = models.CharField(max_length=64, blank=True, default="")
    success = models.BooleanField(default=True)
    request_count = models.IntegerField(default=1)
    prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    cached_tokens = models.IntegerField(default=0)
    duration_ms = models.IntegerField(default=0)
    error_message = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict)

    class Meta:
        db_table = "model_usage"
        indexes = [
            models.Index(fields=["tenant", "created_at"], name="model_usage_tenant__ad5fe5_idx"),
            models.Index(fields=["tenant", "model_type"], name="model_usage_tenant__b6e49d_idx"),
            models.Index(fields=["tenant", "model_id"], name="model_usage_tenant__40f12b_idx"),
            models.Index(fields=["tenant", "scenario"], name="model_usage_tenant__16d85b_idx"),
        ]


class KnowledgeBase(TimeStampedModel):
    id = models.CharField(max_length=36, primary_key=True, default=uuid_str)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    type = models.CharField(max_length=32, default="document")
    chunking_config = models.JSONField(default=dict)
    image_processing_config = models.JSONField(default=dict)
    embedding_model_id = models.CharField(max_length=64, blank=True, default="")
    summary_model_id = models.CharField(max_length=64, blank=True, default="")
    cos_config = models.JSONField(default=dict)
    storage_provider_config = models.JSONField(null=True, blank=True)
    vlm_config = models.JSONField(default=dict)
    asr_config = models.JSONField(null=True, blank=True)
    extract_config = models.JSONField(null=True, blank=True)
    faq_config = models.JSONField(null=True, blank=True)
    question_generation_config = models.JSONField(null=True, blank=True)
    wiki_config = models.JSONField(null=True, blank=True)
    indexing_strategy = models.JSONField(default=dict)
    is_temporary = models.BooleanField(default=False)
    is_pinned = models.BooleanField(default=False)
    pinned_at = models.DateTimeField(null=True, blank=True)
    vector_store_id = models.CharField(max_length=36, blank=True, default="")
    creator_id = models.CharField(max_length=36, blank=True, default="")

    class Meta:
        db_table = "knowledge_bases"


class Knowledge(TimeStampedModel):
    id = models.CharField(max_length=36, primary_key=True, default=uuid_str)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    knowledge_base = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE)
    type = models.CharField(max_length=50)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    source = models.CharField(max_length=2048)
    parse_status = models.CharField(max_length=50, default="pending")
    enable_status = models.CharField(max_length=50, default="enabled")
    embedding_model_id = models.CharField(max_length=64, blank=True, default="")
    file_name = models.CharField(max_length=255, blank=True, default="")
    file_type = models.CharField(max_length=50, blank=True, default="")
    file_size = models.BigIntegerField(null=True, blank=True)
    file_path = models.TextField(blank=True, default="")
    file_hash = models.CharField(max_length=64, blank=True, default="")
    storage_size = models.BigIntegerField(default=0)
    metadata = models.JSONField(default=dict)
    tag_id = models.CharField(max_length=36, blank=True, default="")
    summary_status = models.CharField(max_length=32, default="none")
    pending_subtasks_count = models.IntegerField(default=0)
    last_faq_import_result = models.JSONField(null=True, blank=True)
    channel = models.CharField(max_length=50, default="web")
    processed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        db_table = "knowledges"
        constraints = [
            models.UniqueConstraint(
                fields=["knowledge_base", "file_hash", "file_name"],
                condition=models.Q(deleted_at__isnull=True, type="file", file_hash__gt="", file_name__gt=""),
                name="uniq_active_kb_file_hash_name",
            )
        ]


class Chunk(TimeStampedModel):
    id = models.CharField(max_length=36, primary_key=True, default=uuid_str)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    knowledge_base = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE)
    knowledge = models.ForeignKey(Knowledge, on_delete=models.CASCADE)
    content = models.TextField()
    chunk_index = models.IntegerField()
    is_enabled = models.BooleanField(default=True)
    start_at = models.IntegerField(default=0)
    end_at = models.IntegerField(default=0)
    pre_chunk_id = models.CharField(max_length=36, blank=True, default="")
    next_chunk_id = models.CharField(max_length=36, blank=True, default="")
    chunk_type = models.CharField(max_length=20, default="text")
    parent_chunk_id = models.CharField(max_length=36, blank=True, default="")
    image_info = models.JSONField(null=True, blank=True)
    video_info = models.JSONField(null=True, blank=True)
    relation_chunks = models.JSONField(null=True, blank=True)
    indirect_relation_chunks = models.JSONField(null=True, blank=True)
    metadata = models.JSONField(null=True, blank=True)
    tag_id = models.CharField(max_length=36, blank=True, default="")
    status = models.IntegerField(default=0)
    content_hash = models.CharField(max_length=64, blank=True, default="")
    flags = models.IntegerField(default=1)
    seq_id = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "chunks"


class Session(TimeStampedModel):
    id = models.CharField(max_length=36, primary_key=True, default=uuid_str)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    title = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    knowledge_base_id = models.CharField(max_length=36, blank=True, default="")
    max_rounds = models.IntegerField(default=5)
    enable_rewrite = models.BooleanField(default=True)
    fallback_strategy = models.CharField(max_length=255, default="fixed")
    fallback_response = models.TextField(default="很抱歉，我暂时无法回答这个问题。")
    keyword_threshold = models.FloatField(default=0.5)
    vector_threshold = models.FloatField(default=0.5)
    rerank_model_id = models.CharField(max_length=64, blank=True, default="")
    embedding_top_k = models.IntegerField(default=10)
    rerank_top_k = models.IntegerField(default=10)
    rerank_threshold = models.FloatField(default=0.65)
    summary_model_id = models.CharField(max_length=64, blank=True, default="")
    summary_parameters = models.JSONField(default=dict)
    agent_config = models.JSONField(null=True, blank=True)
    context_config = models.JSONField(null=True, blank=True)
    agent_id = models.CharField(max_length=36, blank=True, default="")
    user_id = models.CharField(max_length=36, blank=True, default="")
    is_pinned = models.BooleanField(default=False)
    pinned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sessions"


class Message(TimeStampedModel):
    id = models.CharField(max_length=36, primary_key=True, default=uuid_str)
    request_id = models.CharField(max_length=36)
    session = models.ForeignKey(Session, on_delete=models.CASCADE)
    role = models.CharField(max_length=50)
    content = models.TextField()
    rendered_content = models.TextField(blank=True, default="")
    knowledge_references = models.JSONField(default=list)
    agent_steps = models.JSONField(null=True, blank=True)
    mentioned_items = models.JSONField(default=list)
    images = models.JSONField(default=list)
    attachments = models.JSONField(default=list)
    is_completed = models.BooleanField(default=False)
    is_fallback = models.BooleanField(default=False)
    channel = models.CharField(max_length=50, blank=True, default="")
    agent_duration_ms = models.IntegerField(default=0)
    knowledge_id = models.CharField(max_length=36, blank=True, default="")

    class Meta:
        db_table = "messages"


class KnowledgeTag(TimeStampedModel):
    id = models.CharField(max_length=36, primary_key=True, default=uuid_str)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    knowledge_base = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE)
    name = models.CharField(max_length=128)
    color = models.CharField(max_length=32, blank=True, default="")
    sort_order = models.IntegerField(default=0)
    seq_id = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "knowledge_tags"
        unique_together = ("tenant", "knowledge_base", "name")


class GenericResource(TimeStampedModel):
    id = models.CharField(max_length=64, primary_key=True, default=uuid_str)
    tenant = models.ForeignKey(Tenant, null=True, blank=True, on_delete=models.CASCADE)
    resource_type = models.CharField(max_length=64)
    name = models.CharField(max_length=255, blank=True, default="")
    data = models.JSONField(default=dict)
    status = models.CharField(max_length=50, default="active")

    class Meta:
        db_table = "generic_resources"
        indexes = [models.Index(fields=["tenant", "resource_type"])]


class AuditLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    actor_user_id = models.CharField(max_length=36, blank=True, default="")
    actor_role = models.CharField(max_length=32, blank=True, default="")
    action = models.CharField(max_length=64)
    target_type = models.CharField(max_length=32, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")
    target_user_id = models.CharField(max_length=36, blank=True, default="")
    request_path = models.CharField(max_length=512, blank=True, default="")
    request_method = models.CharField(max_length=16, blank=True, default="")
    outcome = models.CharField(max_length=16, default="success")
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_logs"


class TaskRecord(TimeStampedModel):
    id = models.CharField(max_length=36, primary_key=True, default=uuid_str)
    task_type = models.CharField(max_length=64)
    status = models.CharField(max_length=32, default="pending")
    progress = models.FloatField(default=0)
    payload = models.JSONField(default=dict)
    result = models.JSONField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        db_table = "task_records"


class WikiPage(TimeStampedModel):
    id = models.CharField(max_length=36, primary_key=True, default=uuid_str)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    knowledge_base = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE)
    slug = models.CharField(max_length=512)
    title = models.CharField(max_length=512)
    content = models.TextField(blank=True, default="")
    summary = models.TextField(blank=True, default="")
    source_refs = models.JSONField(default=list)
    chunk_refs = models.JSONField(default=list)
    aliases = models.JSONField(default=list)
    in_links = models.JSONField(default=list)
    out_links = models.JSONField(default=list)
    page_metadata = models.JSONField(default=dict)
    page_type = models.CharField(max_length=32, default="page")
    status = models.CharField(max_length=32, default="published")
    folder_id = models.CharField(max_length=36, blank=True, default="")
    parent_slug = models.CharField(max_length=512, blank=True, default="")
    category_path = models.JSONField(default=list)
    wiki_path = models.CharField(max_length=1024, blank=True, default="")
    depth = models.IntegerField(default=0)
    sort_order = models.IntegerField(default=0)
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "wiki_pages"
        unique_together = ("knowledge_base", "slug")
        indexes = [
            models.Index(fields=["knowledge_base", "page_type"], name="wiki_pages_kb_type_idx"),
            models.Index(fields=["knowledge_base", "status"], name="wiki_pages_kb_status_idx"),
        ]


class WikiFolder(TimeStampedModel):
    id = models.CharField(max_length=36, primary_key=True, default=uuid_str)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    knowledge_base = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    parent_id = models.CharField(max_length=36, blank=True, default="")
    path = models.CharField(max_length=1024, blank=True, default="")
    depth = models.IntegerField(default=0)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = "wiki_folders"
        indexes = [models.Index(fields=["knowledge_base", "parent_id"], name="wiki_folders_kb_parent_idx")]


class WikiPendingOp(models.Model):
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    task_type = models.CharField(max_length=64, default="wiki:ingest")
    scope = models.CharField(max_length=64, default="knowledge_base")
    scope_id = models.CharField(max_length=64)
    op = models.CharField(max_length=32)
    dedup_key = models.CharField(max_length=128, blank=True, default="")
    payload = models.JSONField(default=dict)
    fail_count = models.IntegerField(default=0)
    error_message = models.TextField(blank=True, default="")
    enqueued_at = models.DateTimeField(auto_now_add=True)
    claimed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "wiki_pending_ops"
        indexes = [
            models.Index(fields=["task_type", "scope", "scope_id", "id"], name="wiki_pending_scope_idx"),
            models.Index(fields=["tenant", "op"], name="wiki_pending_tenant_op_idx"),
            models.Index(fields=["dedup_key"], name="wiki_pending_dedup_idx"),
        ]


class WikiLogEntry(models.Model):
    id = models.CharField(max_length=36, primary_key=True, default=uuid_str)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    knowledge_base = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE)
    knowledge_id = models.CharField(max_length=36, blank=True, default="")
    action = models.CharField(max_length=32)
    doc_title = models.CharField(max_length=512, blank=True, default="")
    summary = models.TextField(blank=True, default="")
    pages_affected = models.JSONField(default=list)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wiki_log_entries"
        indexes = [
            models.Index(fields=["knowledge_base", "created_at"], name="wiki_log_kb_created_idx"),
            models.Index(fields=["knowledge_id"], name="wiki_log_knowledge_idx"),
        ]


class KnowledgeProcessingSpan(models.Model):
    """文档解析追踪 Span，参考 WeKnora 的 KnowledgeProcessingSpan。"""
    id = models.BigAutoField(primary_key=True)
    knowledge = models.ForeignKey(Knowledge, on_delete=models.CASCADE, related_name="processing_spans")
    attempt = models.IntegerField(default=1)
    span_id = models.CharField(max_length=36, default=uuid_str, unique=True)
    parent_span_id = models.CharField(max_length=36, blank=True, default="")
    name = models.CharField(max_length=128)
    kind = models.CharField(max_length=16, default="stage")  # root | stage | subspan | generation
    status = models.CharField(max_length=16, default="pending")  # pending | running | done | failed | skipped | cancelled
    input_data = models.JSONField(default=dict)
    output_data = models.JSONField(default=dict)
    metadata = models.JSONField(default=dict)
    error_code = models.CharField(max_length=64, blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    error_detail = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.IntegerField(default=0)

    class Meta:
        db_table = "knowledge_processing_spans"
        indexes = [
            models.Index(fields=["knowledge", "attempt"], name="span_knowledge_attempt_idx"),
            models.Index(fields=["parent_span_id"], name="span_parent_idx"),
        ]
