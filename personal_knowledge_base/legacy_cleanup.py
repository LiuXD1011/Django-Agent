from django.conf import settings
from django.core.files.storage import default_storage
from django.db import connection, transaction

from .graph_rag import GraphNamespace, graph_repository
from .models import Chunk, Knowledge, KnowledgeImage, KnowledgeProcessingSpan, TaskRecord, WikiFolder, WikiLogEntry, WikiPage, WikiPendingOp


def _table_exists(table_name: str) -> bool:
    return table_name in connection.introspection.table_names()


def purge_legacy_knowledge() -> dict:
    rows = list(Knowledge.objects.values("id", "knowledge_base_id", "file_path"))
    if settings.NEO4J_ENABLE and rows:
        if not graph_repository.available:
            raise RuntimeError("Neo4j is enabled but unavailable; legacy graph cleanup cannot be guaranteed")
        graph_repository.delete_graph(
            [GraphNamespace(knowledge_base_id=row["knowledge_base_id"], knowledge_id=row["id"]) for row in rows]
        )

    paths = {row["file_path"] for row in rows if row["file_path"]}
    if _table_exists("knowledge_images"):
        paths.update(KnowledgeImage.objects.filter(storage_owned=True).values_list("storage_path", flat=True))
    for path in paths:
        if path:
            default_storage.delete(path)

    with transaction.atomic():
        with connection.cursor() as cursor:
            if _table_exists("chunks_fts"):
                cursor.execute("DELETE FROM chunks_fts")
            if _table_exists("chunk_embeddings_vec"):
                cursor.execute("DELETE FROM chunk_embeddings_vec")
        TaskRecord.objects.filter(task_type="process_knowledge").delete()
        WikiPendingOp.objects.all().delete()
        WikiLogEntry.objects.all().delete()
        WikiPage.objects.all().delete()
        WikiFolder.objects.all().delete()
        if _table_exists("knowledge_images"):
            Knowledge.objects.all().delete()
        else:
            # The command is intentionally runnable before migration 0013. The
            # runtime model already knows KnowledgeImage, so Django's collector
            # would query a table that does not exist yet; delete the two actual
            # pre-0013 dependents first and then remove Knowledge directly.
            KnowledgeProcessingSpan.objects.all().delete()
            Chunk.objects.all().delete()
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM knowledges")
    return {"knowledge_deleted": len(rows), "files_deleted": len(paths)}
