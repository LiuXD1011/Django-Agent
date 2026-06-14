import os
import uuid

from django.conf import settings
from django.db import models


def stored_file_path(instance, filename):
    suffix = os.path.splitext(filename)[1].lower()
    return f"storage/{instance.owner_id}/{uuid.uuid4().hex}{suffix}"


class StoredFile(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="stored_files")
    content_hash = models.CharField(max_length=128, db_index=True)
    original_name = models.CharField(max_length=255)
    suffix = models.CharField(max_length=32, blank=True)
    mime_type = models.CharField(max_length=128, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    file = models.FileField(upload_to=stored_file_path)
    ref_count = models.PositiveIntegerField(default=0)
    detected_mime = models.CharField(max_length=128, blank=True)
    content_family = models.CharField(max_length=32, blank=True)
    is_binary = models.BooleanField(default=False)
    inspection_metadata = models.JSONField(default=dict, blank=True)
    last_inspected_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["owner", "content_hash"])]

    def __str__(self):
        return self.original_name


class UserFile(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="files")
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="children")
    stored_file = models.ForeignKey(StoredFile, on_delete=models.PROTECT, null=True, blank=True, related_name="user_files")
    name = models.CharField(max_length=255)
    is_folder = models.BooleanField(default=False)
    file_size = models.PositiveBigIntegerField(default=0)
    suffix = models.CharField(max_length=32, blank=True)
    mime_type = models.CharField(max_length=128, blank=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_folder", "name"]
        indexes = [
            models.Index(fields=["user", "parent", "is_deleted"]),
            models.Index(fields=["user", "name"]),
        ]

    def __str__(self):
        return self.name


class UploadSession(models.Model):
    STATUS_PENDING = "pending"
    STATUS_UPLOADING = "uploading"
    STATUS_MERGED = "merged"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_PENDING, "待上传"),
        (STATUS_UPLOADING, "上传中"),
        (STATUS_MERGED, "已合并"),
        (STATUS_FAILED, "失败"),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="upload_sessions")
    parent = models.ForeignKey(UserFile, on_delete=models.SET_NULL, null=True, blank=True)
    filename = models.CharField(max_length=255)
    content_hash = models.CharField(max_length=128)
    file_size = models.PositiveBigIntegerField(default=0)
    chunk_size = models.PositiveBigIntegerField(default=0)
    chunk_count = models.PositiveIntegerField(default=0)
    received_chunks = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_message = models.TextField(blank=True)
    stored_file = models.ForeignKey(StoredFile, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def progress_percent(self):
        if self.chunk_count <= 0:
            return 0
        return round(len(set(self.received_chunks)) * 100 / self.chunk_count, 2)

    def chunk_dir(self):
        return settings.MEDIA_ROOT / "chunks" / str(self.id)

# Create your models here.
