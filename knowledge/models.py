import uuid

from django.conf import settings
from django.db import models


def generate_kb_id():
    return f"kb_{uuid.uuid4().hex[:16]}"


class KnowledgeBase(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="knowledge_bases")
    kb_id = models.CharField(max_length=80, unique=True, default=generate_kb_id)
    name = models.CharField(max_length=64)
    description = models.CharField(max_length=512, blank=True)
    status = models.CharField(max_length=16, default="active")
    doc_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class KBDocument(models.Model):
    SOURCE_URL = "url"
    SOURCE_FILE = "file"
    SOURCE_TEXT = "text"
    SOURCE_CHOICES = ((SOURCE_URL, "URL"), (SOURCE_FILE, "文件"), (SOURCE_TEXT, "文本"))
    STATUS_PROCESSING = "processing"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_UNSUPPORTED = "unsupported"
    STATUS_CHOICES = (
        (STATUS_PROCESSING, "入库中"),
        (STATUS_READY, "已入库"),
        (STATUS_FAILED, "解析失败"),
        (STATUS_UNSUPPORTED, "不支持"),
    )

    kb = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="documents")
    source_type = models.CharField(max_length=16, choices=SOURCE_CHOICES)
    source = models.CharField(max_length=1024)
    user_file = models.ForeignKey("drive.UserFile", on_delete=models.SET_NULL, null=True, blank=True)
    title = models.CharField(max_length=512, blank=True)
    content_hash = models.CharField(max_length=64, blank=True)
    chunk_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_READY)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class KBChunk(models.Model):
    document = models.ForeignKey(KBDocument, on_delete=models.CASCADE, related_name="chunks")
    kb = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="chunks")
    chunk_index = models.PositiveIntegerField(default=0)
    content = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["chunk_index"]
        indexes = [models.Index(fields=["kb", "chunk_index"])]


class WikiPage(models.Model):
    TYPE_OVERVIEW = "overview"
    TYPE_SOURCE = "source"
    TYPE_CHOICES = (
        (TYPE_OVERVIEW, "总览"),
        (TYPE_SOURCE, "来源页"),
    )
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_STALE = "stale"
    STATUS_CHOICES = (
        (STATUS_READY, "已生成"),
        (STATUS_FAILED, "生成失败"),
        (STATUS_STALE, "已过期"),
    )

    kb = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="wiki_pages")
    page_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    slug = models.SlugField(max_length=160)
    title = models.CharField(max_length=512)
    content = models.TextField(blank=True)
    summary = models.TextField(blank=True)
    source_document = models.ForeignKey(
        KBDocument,
        on_delete=models.SET_NULL,
        related_name="wiki_pages",
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_READY)
    error_message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    content_hash = models.CharField(max_length=64, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["page_type", "title"]
        constraints = [
            models.UniqueConstraint(fields=["kb", "slug"], name="knowledge_wikipage_kb_slug_uniq"),
        ]
        indexes = [
            models.Index(fields=["kb", "page_type", "status"], name="knowledge_w_kb_id_5e175b_idx"),
            models.Index(fields=["source_document", "page_type"], name="knowledge_w_source_f3f75c_idx"),
        ]

    def __str__(self):
        return self.title


class WikiLink(models.Model):
    TYPE_WIKILINK = "wikilink"

    source_page = models.ForeignKey(WikiPage, on_delete=models.CASCADE, related_name="outgoing_links")
    target_title = models.CharField(max_length=512)
    target_page = models.ForeignKey(
        WikiPage,
        on_delete=models.SET_NULL,
        related_name="incoming_links",
        null=True,
        blank=True,
    )
    link_type = models.CharField(max_length=32, default=TYPE_WIKILINK)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["source_page", "link_type"], name="knowledge_w_source_2d6eba_idx"),
            models.Index(fields=["target_page"], name="knowledge_w_target_8305fe_idx"),
        ]

    def __str__(self):
        return self.target_title


class WikiBuildJob(models.Model):
    TYPE_FULL = "full"
    TYPE_DOCUMENT = "document"
    TYPE_CHOICES = (
        (TYPE_FULL, "全量刷新"),
        (TYPE_DOCUMENT, "文档刷新"),
    )
    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_RUNNING, "运行中"),
        (STATUS_SUCCESS, "成功"),
        (STATUS_FAILED, "失败"),
    )

    kb = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="wiki_build_jobs")
    document = models.ForeignKey(KBDocument, on_delete=models.SET_NULL, null=True, blank=True)
    job_type = models.CharField(max_length=16, choices=TYPE_CHOICES, default=TYPE_FULL)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_RUNNING)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["kb", "status", "-started_at"], name="knowledge_w_kb_id_ea64ad_idx")]

    def __str__(self):
        return f"{self.kb} {self.job_type} {self.status}"

# Create your models here.
