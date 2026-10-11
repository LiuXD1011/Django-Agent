"""Browser device sessions; credentials are digests, never reusable plaintext."""
import uuid

from django.db import models


class DeviceSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("personal_knowledge_base.User", on_delete=models.CASCADE)
    name = models.CharField(max_length=100, default="网页设备")
    client_type = models.CharField(max_length=20, default="web")
    access_digest = models.CharField(max_length=64, unique=True)
    access_expires_at = models.DateTimeField()
    idle_expires_at = models.DateTimeField()
    absolute_expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=32, blank=True, default="")

    class Meta:
        db_table = "device_sessions"
        indexes = [models.Index(fields=["user", "revoked_at"], name="device_user_revoked_idx")]


class DeviceRefreshToken(models.Model):
    """Retain consumed digests until family expiry so replay revokes the family."""
    digest = models.CharField(max_length=64, primary_key=True)
    session = models.ForeignKey(DeviceSession, on_delete=models.CASCADE, related_name="refresh_tokens")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "device_refresh_tokens"
