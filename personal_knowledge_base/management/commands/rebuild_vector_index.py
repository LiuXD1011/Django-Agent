from django.core.management.base import BaseCommand
from django.db import connection

from personal_knowledge_base.models import Chunk
from personal_knowledge_base.search import ensure_search_tables, index_chunk


class Command(BaseCommand):
    help = "Rebuild sqlite-vec and FTS5 chunk indexes from stored chunks."

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS chunk_embeddings_vec")
            cursor.execute("DROP TABLE IF EXISTS chunks_fts")
        ensure_search_tables()
        total = 0
        for chunk in Chunk.objects.filter(is_enabled=True).select_related("knowledge", "knowledge_base", "tenant").iterator():
            index_chunk(chunk)
            total += 1
        self.stdout.write(self.style.SUCCESS(f"Rebuilt search indexes for {total} chunks."))
