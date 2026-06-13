from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    ROLE_USER = "user"
    ROLE_ADMIN = "admin"
    ROLE_CHOICES = (
        (ROLE_USER, "普通用户"),
        (ROLE_ADMIN, "管理员"),
    )

    phone = models.CharField("手机号", max_length=32, unique=True, null=True, blank=True)
    avatar = models.ImageField("头像", upload_to="avatars/%Y/%m/", blank=True)
    role = models.CharField("角色", max_length=16, choices=ROLE_CHOICES, default=ROLE_USER)

    @property
    def is_platform_admin(self):
        return self.is_superuser or self.role == self.ROLE_ADMIN


class StorageQuota(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="storage_quota")
    used_size = models.PositiveBigIntegerField(default=0)
    total_size = models.PositiveBigIntegerField(default=settings.DEFAULT_STORAGE_QUOTA_BYTES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def remaining_size(self):
        return max(0, self.total_size - self.used_size)

    @property
    def used_percent(self):
        if self.total_size <= 0:
            return 0
        return round(self.used_size * 100 / self.total_size, 2)

# Create your models here.
