from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import StorageQuota, User


@receiver(post_save, sender=User)
def ensure_storage_quota(sender, instance, created, **kwargs):
    if created:
        StorageQuota.objects.get_or_create(
            user=instance,
            defaults={"total_size": settings.DEFAULT_STORAGE_QUOTA_BYTES},
        )
