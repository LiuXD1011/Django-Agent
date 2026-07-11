from pathlib import Path

from django.core.files.storage import default_storage
from django.db import migrations
from django.db.models import Q


REMOVED_FILE_TYPES = frozenset({"mp3", "wav", "m4a", "aac", "ogg", "flac", "mp4", "mov", "avi", "mkv", "webm"})


def _table_exists(connection, table_name):
    with connection.cursor() as cursor:
        return table_name in connection.introspection.table_names(cursor)


def _is_removed_file(knowledge):
    file_type = str(knowledge.file_type or "").strip().lower().lstrip(".")
    suffix = Path(knowledge.file_name or "").suffix.lower().lstrip(".")
    return file_type in REMOVED_FILE_TYPES or suffix in REMOVED_FILE_TYPES


def remove_audio_video_data(apps, schema_editor):
    Knowledge = apps.get_model("personal_knowledge_base", "Knowledge")
    Chunk = apps.get_model("personal_knowledge_base", "Chunk")
    ModelConfig = apps.get_model("personal_knowledge_base", "ModelConfig")
    ModelUsage = apps.get_model("personal_knowledge_base", "ModelUsage")

    removed = [item for item in Knowledge.objects.filter(type="file") if _is_removed_file(item)]
    knowledge_ids = [item.id for item in removed]
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

        namespaces = [GraphNamespace(knowledge_base_id=item.knowledge_base_id, knowledge_id=item.id) for item in removed]
        if namespaces:
            graph_repository.delete_graph(namespaces)
    except Exception:
        pass

    for item in removed:
        if item.file_path:
            default_storage.delete(item.file_path)

    if knowledge_ids:
        Chunk.objects.filter(knowledge_id__in=knowledge_ids).delete()
        Knowledge.objects.filter(id__in=knowledge_ids).delete()

    ModelConfig.objects.filter(type__iexact="asr").delete()
    ModelUsage.objects.filter(Q(model_type__iexact="asr") | Q(scenario__iexact="asr") | Q(model_id__icontains="-asr")).delete()


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("personal_knowledge_base", "0011_agentactor_message_actor_fields"),
    ]

    operations = [
        migrations.RunPython(remove_audio_video_data, migrations.RunPython.noop),
        migrations.RemoveField(model_name="chunk", name="video_info"),
    ]
