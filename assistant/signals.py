from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import ConversationMemory


@receiver(post_save, sender=ConversationMemory)
def sync_conversation_memory_index(sender, instance, **kwargs):
    from .memory import upsert_memory_index

    upsert_memory_index(instance)


@receiver(post_delete, sender=ConversationMemory)
def cleanup_conversation_memory_index(sender, instance, **kwargs):
    from .memory import delete_memory_index

    delete_memory_index(instance.id)
