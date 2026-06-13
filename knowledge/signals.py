from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver

from .models import KBChunk, KBDocument, WikiPage


@receiver(post_delete, sender=KBChunk)
def cleanup_chunk_search_indexes(sender, instance, **kwargs):
    from .services import delete_chunk_indexes

    delete_chunk_indexes(instance.id)


@receiver(post_delete, sender=WikiPage)
def cleanup_wiki_page_search_indexes(sender, instance, **kwargs):
    from .wiki_services import delete_wiki_page_indexes

    delete_wiki_page_indexes(instance.id)


@receiver(pre_delete, sender=KBDocument)
def mark_document_wiki_pages_stale(sender, instance, **kwargs):
    WikiPage.objects.filter(source_document=instance, page_type=WikiPage.TYPE_SOURCE).update(
        source_document=None,
        status=WikiPage.STATUS_STALE,
        error_message="来源文档已删除，页面内容可能已过期。",
    )
