from django.db import migrations


def _table_exists(connection, table_name):
    with connection.cursor() as cursor:
        tables = connection.introspection.table_names(cursor)
    return table_name in tables


def cleanup_manual_url_knowledge(apps, schema_editor):
    Knowledge = apps.get_model("personal_knowledge_base", "Knowledge")
    Chunk = apps.get_model("personal_knowledge_base", "Chunk")

    stale = Knowledge.objects.filter(type__in=["manual", "url"])
    knowledge_ids = list(stale.values_list("id", flat=True))
    if not knowledge_ids:
        return

    chunk_rows = list(Chunk.objects.filter(knowledge_id__in=knowledge_ids).values_list("id", "seq_id"))
    chunk_ids = [row[0] for row in chunk_rows]
    seq_ids = [row[1] for row in chunk_rows if row[1]]

    connection = schema_editor.connection
    with connection.cursor() as cursor:
        if chunk_ids and _table_exists(connection, "chunks_fts"):
            cursor.execute(f"DELETE FROM chunks_fts WHERE chunk_id IN ({','.join(['%s'] * len(chunk_ids))})", chunk_ids)
        if seq_ids and _table_exists(connection, "chunk_embeddings_vec"):
            cursor.execute(f"DELETE FROM chunk_embeddings_vec WHERE rowid IN ({','.join(['%s'] * len(seq_ids))})", seq_ids)

    try:
        from personal_knowledge_base.graph_rag import GraphNamespace, graph_repository

        namespaces = [
            GraphNamespace(knowledge_base_id=kb_id, knowledge_id=knowledge_id)
            for knowledge_id, kb_id in stale.values_list("id", "knowledge_base_id")
        ]
        if namespaces:
            graph_repository.delete_graph(namespaces)
    except Exception:
        pass

    Chunk.objects.filter(knowledge_id__in=knowledge_ids).delete()
    stale.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("personal_knowledge_base", "0003_modelusage"),
    ]

    operations = [
        migrations.RunPython(cleanup_manual_url_knowledge, migrations.RunPython.noop),
    ]
